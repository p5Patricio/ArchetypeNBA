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

from app.analytics.props_engine import normalize_player_key, strip_player_suffix
from app.models import (
    BetSide,
    Game,
    MarketType,
    OddsCapturePresence,
    OddsHistory,
    Player,
    PlayerGameLog,
    PlayerSeasonStats,
    Season,
    Sportsbook,
    Team,
)
from app.services.odds_api_service import GAME_LINE_MARKETS, MARKET_TO_STAT, GameQuote, OddsQuote

logger = logging.getLogger(__name__)

SHARP_BOOKS = {"pinnacle"}
EU_BOOKS = {"pinnacle"}  # every other tracked book is a US book

_GAME_MARKETS = {key: MarketType(key) for key in GAME_LINE_MARKETS}
_PROP_MARKETS = {key: MarketType(key) for key in MARKET_TO_STAT}
_PROP_MARKETS["player_pra"] = MarketType.player_pra
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
    unmatched_names: int = 0  # player names that could not be mapped or were ambiguous

    def merge(self, other: "IngestResult") -> "IngestResult":
        return IngestResult(
            self.inserted + other.inserted,
            self.skipped_duplicate + other.skipped_duplicate,
            self.skipped_unmatched + other.skipped_unmatched,
            self.skipped_invalid + other.skipped_invalid,
            self.unmatched_names + other.unmatched_names,
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
        self._global_player_maps: Optional[Tuple[Dict[str, Optional[int]], Dict[str, Optional[int]]]] = None
        self._game_player_maps: Dict[int, Tuple[Dict[str, Optional[int]], Dict[str, Optional[int]]]] = {}

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
                if team.full_name:
                    index.setdefault(_team_key(team.full_name), team)
                canon = canonical_team_name(team.full_name or "")
                if canon:
                    index.setdefault(_team_key(canon), team)
            self._teams = index
        return self._teams

    def resolve_team(self, api_name: str) -> Optional[Team]:
        """Finds the `team` row for an Odds API team name or abbreviation; None when the franchise is unknown."""
        if not api_name:
            return None
        index = self._team_index()
        # Fast path: direct abbreviation lookup (e.g. 'BOS', 'LAL', 'GSW')
        abbr = api_name.strip().upper()
        if abbr in index:
            return index[abbr]

        canon = canonical_team_name(api_name)
        if canon is not None:
            for abbreviation in _TEAM_ABBREVIATIONS.get(canon, ()):
                team = index.get(abbreviation)
                if team is not None:
                    return team
            return index.get(_team_key(canon))
        return index.get(_team_key(api_name))

    @staticmethod
    def season_label_for(day: date) -> str:
        """NBA season label for a calendar date: August onwards belongs to the season starting that year."""
        start_year = day.year if day.month >= 8 else day.year - 1
        return f"{start_year}-{(start_year + 1) % 100:02d}"

    def resolve_season_id(self, commence_time: datetime) -> int:
        """
        Season for a game: a season whose explicit date range covers the game date, else the season with
        the label for that date, else a new inactive season with that label (Oct 1 - Jun 30). Season rows
        in the live database have no dates, so the label is what normally matches. ``is_active`` is never
        changed: it drives the default season of the frontend.
        """
        day = _aware_utc(commence_time).date()
        seasons = list(self.session.exec(select(Season)).all())
        for season in seasons:
            if season.start_date and season.end_date and season.start_date <= day <= season.end_date:
                return season.id

        label = self.season_label_for(day)
        for season in seasons:
            if season.season_label == label:
                return season.id

        start_year = int(label[:4])
        season = Season(
            season_label=label,
            start_date=date(start_year, 10, 1),
            end_date=date(start_year + 1, 6, 30),
            is_active=False,
        )
        self.session.add(season)
        self.session.flush()
        logger.info(f"OddsIngestion: created season {label} for a game on {day}.")
        return season.id

    def upsert_game(
        self, event_id: str, commence_time: datetime, home_team: str, away_team: str
    ) -> Optional[Game]:
        """Creates/updates the game for a provider event. Returns None (and logs) if a team is unresolved."""
        cached = self._games.get(event_id)
        commence = _aware_utc(commence_time)

        game = cached or self.session.exec(
            select(Game).where(Game.provider_event_id == event_id)
        ).first()
        if game is not None:
            changed = False
            if _aware_utc(game.commence_time) != commence:
                game.commence_time = commence
                if game.status == "postponed":
                    game.status = "scheduled"
                changed = True
            season_id = self.resolve_season_id(commence)
            if game.season_id != season_id:  # rows created before the season existed point at the wrong one
                game.season_id = season_id
                changed = True
            if changed:
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

        game = Game(
            provider_event_id=event_id,
            season_id=self.resolve_season_id(commence),
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

    @staticmethod
    def _build_player_maps(
        candidates: Iterable[Tuple[int, str]]
    ) -> Tuple[Dict[str, Optional[int]], Dict[str, Optional[int]]]:
        exact_map: Dict[str, Optional[int]] = {}
        stripped_map: Dict[str, Optional[int]] = {}
        for player_id, full_name in candidates:
            if not full_name:
                continue
            norm = normalize_player_key(full_name)
            stripped = strip_player_suffix(norm)
            exact_map[norm] = None if norm in exact_map and exact_map[norm] != player_id else player_id
            stripped_map[stripped] = None if stripped in stripped_map and stripped_map[stripped] != player_id else player_id
        return exact_map, stripped_map

    def _candidate_players_for_game(self, game: Optional[Game]) -> List[Tuple[int, str]]:
        if game is not None and game.home_team_id and game.away_team_id:
            team_ids = (game.home_team_id, game.away_team_id)
            # Try PlayerSeasonStats
            pss_stmt = (
                sa_select(Player.id, Player.full_name)
                .join(PlayerSeasonStats, PlayerSeasonStats.player_id == Player.id)
                .where(PlayerSeasonStats.team_id.in_(team_ids))
            )
            pss_players = self.session.execute(pss_stmt).all()

            # Also PlayerGameLog
            pgl_stmt = (
                sa_select(Player.id, Player.full_name)
                .join(PlayerGameLog, PlayerGameLog.player_id == Player.id)
                .where(PlayerGameLog.team_id.in_(team_ids))
            )
            pgl_players = self.session.execute(pgl_stmt).all()

            combined = {int(p_id): str(full_name) for p_id, full_name in [*pss_players, *pgl_players] if p_id is not None}
            if combined:
                return list(combined.items())

        # Fallback to all players if no team players found or game is None
        all_players = self.session.execute(sa_select(Player.id, Player.full_name)).all()
        return [(int(p_id), str(full_name)) for p_id, full_name in all_players if p_id is not None]

    def _player_index(self) -> Dict[str, Optional[int]]:
        """normalized name -> player id; None marks an ambiguous name (never guessed)."""
        if self._global_player_maps is None:
            candidates = self._candidate_players_for_game(None)
            self._global_player_maps = self._build_player_maps(candidates)
        return self._global_player_maps[0]

    def resolve_player_id(self, name: str, game: Optional[Game] = None) -> Optional[int]:
        if not name:
            return None
        if game is not None and game.id is not None:
            if game.id not in self._game_player_maps:
                candidates = self._candidate_players_for_game(game)
                self._game_player_maps[game.id] = self._build_player_maps(candidates)
            exact_map, stripped_map = self._game_player_maps[game.id]
        else:
            if self._global_player_maps is None:
                candidates = self._candidate_players_for_game(None)
                self._global_player_maps = self._build_player_maps(candidates)
            exact_map, stripped_map = self._global_player_maps

        norm_name = normalize_player_key(name)
        if norm_name in exact_map:
            return exact_map[norm_name]

        stripped_name = strip_player_suffix(norm_name)
        if stripped_name in stripped_map:
            return stripped_map[stripped_name]

        return None

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

    def find_existing_game(
        self,
        home_team: str,
        away_team: str,
        commence_time: datetime,
        tolerance_hours: float = 6.0,
    ) -> Optional[Game]:
        """
        Locates an existing Game row matching home and away teams within a commence_time tolerance window.
        Never creates a game row. Returns None if unmatched.
        """
        home = self.resolve_team(home_team)
        away = self.resolve_team(away_team)
        if home is None or away is None or home.id == away.id:
            return None

        target = _aware_utc(commence_time)
        candidates = self.session.exec(
            select(Game).where(
                Game.home_team_id == home.id,
                Game.away_team_id == away.id,
            )
        ).all()

        best: Optional[Game] = None
        min_delta: Optional[float] = None
        tolerance_seconds = tolerance_hours * 3600.0

        for g in candidates:
            delta = abs((_aware_utc(g.commence_time) - target).total_seconds())
            if delta <= tolerance_seconds:
                if min_delta is None or delta < min_delta:
                    min_delta = delta
                    best = g

        return best

    def ingest_secondary_game_quotes(
        self,
        quotes: Iterable[GameQuote],
        captured_at: datetime,
        tolerance_hours: float = 6.0,
    ) -> IngestResult:
        """
        Ingests quotes from a secondary feed (e.g. SportsGameOdds).
        Matches events to existing Game rows; NEVER creates a game row.
        Unmatched events are counted in skipped_unmatched and logged.
        """
        result = IngestResult()
        rows: List[dict] = []
        event_game_map: Dict[str, Optional[Game]] = {}

        for q in quotes:
            market = _GAME_MARKETS.get(q.market_key)
            side = _SIDES.get(q.side)
            commence = parse_api_datetime(q.commence_time)
            # book_last_update from lastUpdatedAt when present, fallback to captured_at
            updated = parse_api_datetime(q.book_last_update) or _aware_utc(captured_at)

            if market is None or side is None or commence is None:
                result.skipped_invalid += 1
                continue

            if q.event_id not in event_game_map:
                game = self.find_existing_game(q.home_team, q.away_team, commence, tolerance_hours)
                event_game_map[q.event_id] = game
                if game is None:
                    logger.warning(
                        f"OddsIngestion: unmatched secondary feed event {q.event_id} "
                        f"({q.away_team} @ {q.home_team} at {commence}); skipped (never created)."
                    )

            game = event_game_map[q.event_id]
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

            player_id = self.resolve_player_id(q.player_name, game=game)
            if player_id is None:
                logger.info("OddsIngestion: player name %r unmatched or ambiguous for game %s; quote skipped", q.player_name, game.id)
                result.skipped_unmatched += 1
                result.unmatched_names += 1
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

    def ingest_capture_presence(
        self, capture_id: int, game_id: int, quotes: Iterable[GameQuote], *, commit: bool = False
    ) -> int:
        """
        Records the (book, market, side, line) quotes present in a closing capture payload.
        Bulk-inserted and idempotent: duplicate presence rows within the payload or from a re-ingest
        are ignored.
        """
        rows: List[dict] = []
        for q in quotes:
            market = _GAME_MARKETS.get(q.market_key)
            side = _SIDES.get(q.side)
            if market is None or side is None:
                continue
            book = self.upsert_sportsbook(q.bookmaker_key, q.bookmaker_title)
            line_val = None if q.line is None else Decimal(str(q.line)).quantize(Decimal("0.1"))
            rows.append({
                "capture_id": capture_id,
                "game_id": game_id,
                "sportsbook_id": book.id,
                "market": market,
                "side": side,
                "line": line_val,
            })
        return self._insert_presence_rows(capture_id, rows, commit=commit)

    def _insert_presence_rows(
        self, capture_id: int, rows: List[dict], *, commit: bool = False
    ) -> int:
        if not rows:
            return 0

        deduped: Dict[tuple, dict] = {}
        for r in rows:
            m_val = r["market"].value if hasattr(r["market"], "value") else str(r["market"])
            s_val = r["side"].value if hasattr(r["side"], "value") else str(r["side"])
            key = (r["sportsbook_id"], m_val, s_val, r["line"])
            if key not in deduped:
                deduped[key] = r

        dialect = self.session.get_bind().dialect.name
        fresh: List[dict] = list(deduped.values())
        if dialect != "postgresql":
            # Without NULLS NOT DISTINCT SQLite treats NULL lines as distinct.
            # Pre-filter against existing rows in the DB to emulate NULLS NOT DISTINCT.
            table = OddsCapturePresence.__table__
            stmt = sa_select(
                table.c.sportsbook_id,
                table.c.market,
                table.c.side,
                table.c.line,
            ).where(table.c.capture_id == capture_id)
            existing = set()
            for book_id, market, side, line in self.session.execute(stmt):
                m_val = market.value if hasattr(market, "value") else str(market)
                s_val = side.value if hasattr(side, "value") else str(side)
                line_val = None if line is None else Decimal(str(line)).quantize(Decimal("0.1"))
                existing.add((book_id, m_val, s_val, line_val))
            fresh = [
                r for r in deduped.values()
                if (
                    r["sportsbook_id"],
                    r["market"].value if hasattr(r["market"], "value") else str(r["market"]),
                    r["side"].value if hasattr(r["side"], "value") else str(r["side"]),
                    r["line"],
                ) not in existing
            ]

        if not fresh:
            return 0

        table = OddsCapturePresence.__table__
        make_insert = {"postgresql": pg_insert, "sqlite": sqlite_insert}.get(dialect, generic_insert)
        inserted = 0
        for start in range(0, len(fresh), self._CHUNK):
            chunk = fresh[start : start + self._CHUNK]
            stmt = make_insert(table).values(chunk)
            if dialect in ("postgresql", "sqlite"):
                stmt = stmt.on_conflict_do_nothing()
            if dialect == "postgresql":
                res = self.session.execute(stmt.returning(table.c.id)).all()
                inserted += len(res)
            else:
                self.session.execute(stmt)
                inserted += len(chunk)

        if commit:
            self.session.commit()
        else:
            self.session.flush()
        return inserted


