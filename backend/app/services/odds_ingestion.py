"""
Persists Odds API quotes into the quant schema (sportsbook, game, odds_history).

Design notes
- odds_history is append-only and idempotent: the unique key is
  (game, book, market, player, side, line, book_last_update), so re-ingesting the same
  payload inserts nothing. PostgreSQL enforces it with NULLS NOT DISTINCT; SQLite treats
  NULLs as distinct, so rows with a NULL player/line are pre-filtered in Python there.
- Nothing is invented: a quote whose team, player, market or price cannot be mapped is
  skipped and counted, never repaired.
"""
import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from sqlalchemy import insert as generic_insert
from sqlalchemy import select as sa_select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel import Session, select

from app.analytics.props_engine import normalize_player_key
from app.models import BetSide, Game, MarketType, OddsHistory, Player, Season, Sportsbook, Team
from app.services.odds_api_service import GAME_LINE_MARKETS, MARKET_TO_STAT, GameQuote, OddsQuote

logger = logging.getLogger(__name__)

SHARP_BOOKS = {"pinnacle"}
EU_BOOKS = {"pinnacle"}  # every other tracked book is a US book

_GAME_MARKETS = {key: MarketType(key) for key in GAME_LINE_MARKETS}
_PROP_MARKETS = {key: MarketType(key) for key in MARKET_TO_STAT}
_SIDES = {side.value: side for side in BetSide}

# Odds API franchise name -> abbreviations the `team` table may use. The first entry that exists wins.
_TEAM_ABBREVIATIONS: Dict[str, Tuple[str, ...]] = {
    "Atlanta Hawks": ("ATL",),
    "Boston Celtics": ("BOS",),
    "Brooklyn Nets": ("BKN", "BRK"),
    "Charlotte Hornets": ("CHA", "CHO"),
    "Chicago Bulls": ("CHI",),
    "Cleveland Cavaliers": ("CLE",),
    "Dallas Mavericks": ("DAL",),
    "Denver Nuggets": ("DEN",),
    "Detroit Pistons": ("DET",),
    "Golden State Warriors": ("GSW", "GS"),
    "Houston Rockets": ("HOU",),
    "Indiana Pacers": ("IND",),
    "Los Angeles Clippers": ("LAC",),
    "Los Angeles Lakers": ("LAL",),
    "Memphis Grizzlies": ("MEM",),
    "Miami Heat": ("MIA",),
    "Milwaukee Bucks": ("MIL",),
    "Minnesota Timberwolves": ("MIN",),
    "New Orleans Pelicans": ("NOP", "NO"),
    "New York Knicks": ("NYK", "NY"),
    "Oklahoma City Thunder": ("OKC",),
    "Orlando Magic": ("ORL",),
    "Philadelphia 76ers": ("PHI",),
    "Phoenix Suns": ("PHX", "PHO"),
    "Portland Trail Blazers": ("POR",),
    "Sacramento Kings": ("SAC",),
    "San Antonio Spurs": ("SAS", "SA"),
    "Toronto Raptors": ("TOR",),
    "Utah Jazz": ("UTA", "UTH"),
    "Washington Wizards": ("WAS", "WSH"),
}
_TEAM_ALIASES = {
    "la clippers": "Los Angeles Clippers",
    "la lakers": "Los Angeles Lakers",
}


def _team_key(name: str) -> str:
    return normalize_player_key(name)  # same diacritic/punctuation-insensitive form


_CANONICAL_TEAMS = {_team_key(name): name for name in _TEAM_ABBREVIATIONS}
_CANONICAL_TEAMS.update({_team_key(alias): canon for alias, canon in _TEAM_ALIASES.items()})


def canonical_team_name(name: str) -> Optional[str]:
    """Maps an Odds API team name (incl. aliases such as 'LA Clippers') to its canonical franchise name."""
    return _CANONICAL_TEAMS.get(_team_key(name))


def parse_api_datetime(value: Optional[str]) -> Optional[datetime]:
    """Parses an ISO 8601 timestamp from the API into an aware UTC datetime (None if absent/invalid)."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _naive_utc(value: datetime) -> datetime:
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _aware_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


@dataclass
class IngestResult:
    inserted: int = 0
    skipped_duplicate: int = 0
    skipped_unmatched: int = 0  # team/game or player that could not be resolved
    skipped_invalid: int = 0  # unknown market/side, bad price, missing timestamp

    def merge(self, other: "IngestResult") -> "IngestResult":
        return IngestResult(
            self.inserted + other.inserted,
            self.skipped_duplicate + other.skipped_duplicate,
            self.skipped_unmatched + other.skipped_unmatched,
            self.skipped_invalid + other.skipped_invalid,
        )


_RowKey = Tuple[int, int, str, Optional[int], str, Optional[Decimal], datetime]


class OddsIngestionService:
    # Bound parameters per row: 9 columns; keep each statement under SQLite's 999-variable floor.
    _CHUNK = 100

    def __init__(self, session: Session):
        self.session = session
        self._sportsbooks: Dict[str, Sportsbook] = {}
        self._games: Dict[str, Game] = {}
        self._teams: Optional[Dict[str, Team]] = None
        self._players: Optional[Dict[str, Optional[int]]] = None

    # ------------------------------------------------------------------ dimensions

    def upsert_sportsbook(self, key: str, title: str) -> Sportsbook:
        cached = self._sportsbooks.get(key)
        if cached is not None:
            return cached

        book = self.session.exec(select(Sportsbook).where(Sportsbook.key == key)).first()
        if book is None:
            book = Sportsbook(
                key=key,
                name=title or key,
                region="eu" if key in EU_BOOKS else "us",
                is_sharp=key in SHARP_BOOKS,
            )
            self.session.add(book)
            self.session.flush()
        self._sportsbooks[key] = book
        return book

    def _team_index(self) -> Dict[str, Team]:
        if self._teams is None:
            index: Dict[str, Team] = {}
            for team in self.session.exec(select(Team)).all():
                index[(team.abbreviation or "").upper()] = team
                canon = canonical_team_name(team.full_name or "")
                if canon:
                    index.setdefault(_team_key(canon), team)
            self._teams = index
        return self._teams

    def resolve_team(self, api_name: str) -> Optional[Team]:
        """Finds the `team` row for an Odds API team name; None when the franchise is unknown."""
        canon = canonical_team_name(api_name)
        if canon is None:
            return None
        index = self._team_index()
        for abbreviation in _TEAM_ABBREVIATIONS[canon]:
            team = index.get(abbreviation)
            if team is not None:
                return team
        return index.get(_team_key(canon))

    def resolve_season_id(self, commence_time: datetime) -> Optional[int]:
        """
        Season for a game: the active season (when its date range, if any, covers the game),
        else the season whose range covers the game date, else the active season, else the latest.
        """
        day = _aware_utc(commence_time).date()
        seasons = list(self.session.exec(select(Season)).all())
        if not seasons:
            return None

        def covers(season: Season) -> bool:
            return bool(
                season.start_date and season.end_date and season.start_date <= day <= season.end_date
            )

        active = [s for s in seasons if s.is_active]
        for season in active:
            if (season.start_date is None and season.end_date is None) or covers(season):
                return season.id
        for season in seasons:
            if covers(season):
                return season.id
        if active:
            return active[0].id
        return max(seasons, key=lambda s: (s.start_date or date.min, s.id or 0)).id

    def upsert_game(
        self, event_id: str, commence_time: datetime, home_team: str, away_team: str
    ) -> Optional[Game]:
        """Creates/updates the game for a provider event. Returns None (and logs) if a team or season is unresolved."""
        cached = self._games.get(event_id)
        commence = _aware_utc(commence_time)

        game = cached or self.session.exec(
            select(Game).where(Game.provider_event_id == event_id)
        ).first()
        if game is not None:
            if _aware_utc(game.commence_time) != commence:
                game.commence_time = commence
                self.session.add(game)
                self.session.flush()
            self._games[event_id] = game
            return game

        home = self.resolve_team(home_team)
        away = self.resolve_team(away_team)
        if home is None or away is None or home.id == away.id:
            logger.warning(
                f"OddsIngestion: cannot resolve teams for event {event_id} ({away_team} @ {home_team}); skipping."
            )
            return None

        season_id = self.resolve_season_id(commence)
        if season_id is None:
            logger.warning(f"OddsIngestion: no season available for event {event_id}; skipping.")
            return None

        game = Game(
            provider_event_id=event_id,
            season_id=season_id,
            home_team_id=home.id,
            away_team_id=away.id,
            commence_time=commence,
        )
        self.session.add(game)
        self.session.flush()
        self._games[event_id] = game
        return game

    def _game_for_event(self, event_id: str) -> Optional[Game]:
        game = self._games.get(event_id)
        if game is None:
            game = self.session.exec(select(Game).where(Game.provider_event_id == event_id)).first()
            if game is not None:
                self._games[event_id] = game
        return game

    def _player_index(self) -> Dict[str, Optional[int]]:
        """normalized name -> player id; None marks an ambiguous name (never guessed)."""
        if self._players is None:
            index: Dict[str, Optional[int]] = {}
            for player_id, full_name in self.session.exec(select(Player.id, Player.full_name)).all():
                key = normalize_player_key(full_name)
                index[key] = None if key in index and index[key] != player_id else player_id
            self._players = index
        return self._players

    def resolve_player_id(self, name: str) -> Optional[int]:
        return self._player_index().get(normalize_player_key(name))

    # ------------------------------------------------------------------ ingestion

    def ingest_game_quotes(self, quotes: Iterable[GameQuote], captured_at: datetime) -> IngestResult:
        result = IngestResult()
        rows: List[dict] = []
        for q in quotes:
            market = _GAME_MARKETS.get(q.market_key)
            side = _SIDES.get(q.side)
            updated = parse_api_datetime(q.book_last_update)
            commence = parse_api_datetime(q.commence_time)
            if market is None or side is None or updated is None or commence is None:
                result.skipped_invalid += 1
                continue

            game = self.upsert_game(q.event_id, commence, q.home_team, q.away_team)
            if game is None:
                result.skipped_unmatched += 1
                continue

            book = self.upsert_sportsbook(q.bookmaker_key, q.bookmaker_title)
            row = self._row(game, book, market, None, side, q.line, q.price_american, updated, captured_at)
            if row is None:
                result.skipped_invalid += 1
                continue
            rows.append(row)

        return result.merge(self._insert_rows(rows))

    def ingest_prop_quotes(
        self, event_id: str, quotes: Sequence[OddsQuote], captured_at: datetime
    ) -> IngestResult:
        """Stores prop quotes for an event whose game already exists (see upsert_game / ingest_game_quotes)."""
        result = IngestResult()
        game = self._game_for_event(event_id)
        if game is None:
            logger.warning(f"OddsIngestion: no game for event {event_id}; {len(quotes)} prop quotes skipped.")
            result.skipped_unmatched = len(quotes)
            return result

        rows: List[dict] = []
        for q in quotes:
            market = _PROP_MARKETS.get(q.market_key)
            side = _SIDES.get(q.side)
            updated = parse_api_datetime(q.book_last_update)
            if market is None or side not in (BetSide.over, BetSide.under) or updated is None:
                result.skipped_invalid += 1
                continue

            player_id = self.resolve_player_id(q.player_name)
            if player_id is None:
                result.skipped_unmatched += 1
                continue

            book = self.upsert_sportsbook(q.bookmaker_key, q.bookmaker_key)
            row = self._row(game, book, market, player_id, side, q.line, q.price_american, updated, captured_at)
            if row is None:
                result.skipped_invalid += 1
                continue
            rows.append(row)

        return result.merge(self._insert_rows(rows))

    # ------------------------------------------------------------------ persistence

    @staticmethod
    def _row(
        game: Game,
        book: Sportsbook,
        market: MarketType,
        player_id: Optional[int],
        side: BetSide,
        line: Optional[float],
        price_american: int,
        updated: datetime,
        captured_at: datetime,
    ) -> Optional[dict]:
        if not (price_american <= -100 or price_american >= 100):
            return None
        return {
            "game_id": game.id,
            "sportsbook_id": book.id,
            "market": market,
            "player_id": player_id,
            "side": side,
            "line": None if line is None else Decimal(str(line)).quantize(Decimal("0.1")),
            "price_american": int(price_american),
            "book_last_update": updated,
            "captured_at": _aware_utc(captured_at),
        }

    @staticmethod
    def _key(row: dict) -> _RowKey:
        return (
            row["game_id"],
            row["sportsbook_id"],
            row["market"].value,
            row["player_id"],
            row["side"].value,
            row["line"],
            _naive_utc(row["book_last_update"]),
        )

    def _existing_keys(self, game_ids: Iterable[int]) -> set:
        table = OddsHistory.__table__
        stmt = sa_select(
            table.c.game_id,
            table.c.sportsbook_id,
            table.c.market,
            table.c.player_id,
            table.c.side,
            table.c.line,
            table.c.book_last_update,
        ).where(table.c.game_id.in_(list(game_ids)))
        keys = set()
        for game_id, book_id, market, player_id, side, line, updated in self.session.execute(stmt):
            market_value = market.value if hasattr(market, "value") else market
            side_value = side.value if hasattr(side, "value") else side
            line_value = None if line is None else Decimal(str(line)).quantize(Decimal("0.1"))
            keys.add((game_id, book_id, market_value, player_id, side_value, line_value, _naive_utc(updated)))
        return keys

    def _insert_rows(self, rows: List[dict]) -> IngestResult:
        result = IngestResult()
        if not rows:
            return result

        dialect = self.session.get_bind().dialect.name
        seen: set = set()
        if dialect != "postgresql":
            # Without NULLS NOT DISTINCT the DB cannot dedupe game-market rows (NULL player/line).
            seen = self._existing_keys({r["game_id"] for r in rows})

        fresh: List[dict] = []
        for row in rows:
            key = self._key(row)
            if key in seen:
                result.skipped_duplicate += 1
                continue
            seen.add(key)
            fresh.append(row)

        table = OddsHistory.__table__
        make_insert = {"postgresql": pg_insert, "sqlite": sqlite_insert}.get(dialect, generic_insert)
        for start in range(0, len(fresh), self._CHUNK):
            chunk = fresh[start : start + self._CHUNK]
            stmt = make_insert(table).values(chunk)
            if dialect in ("postgresql", "sqlite"):
                stmt = stmt.on_conflict_do_nothing()
            inserted = len(self.session.execute(stmt.returning(table.c.id)).all())
            result.inserted += inserted
            result.skipped_duplicate += len(chunk) - inserted

        self.session.commit()
        return result

