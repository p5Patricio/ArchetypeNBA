"""
OddsPapi price paths for finished NBA games: parsing, fixture mapping, storage, missed-close recovery, planning (D-70).

Payload facts (live probe 2026-11-07, ``odd/tasks/oddspapi.md``)
* NBA = sportId 11, tournamentId 132. ``participant1`` is the HOME team (checked against our ``game`` rows).
* ``GET /v4/fixtures?tournamentId=132&from&to`` returns the whole range in one billed request (860 fixtures for
  Jan-Jun 2026). ``trueStartTime`` is the real tip-off (e.g. 19:00:54 for a 19:00 start).
* ``GET /v4/historical-odds`` (free) returns ``bookmakers.<slug>.markets.<marketId>.outcomes.<outcomeId>
  .players."0"`` = a list of ``{createdAt, price (decimal), limit, active, exchangeMeta}``: every price change,
  pre-match AND in-play in the same list, so everything after the tip must be cut.
* Each line is its own market id (catalogue in ``app/data/oddspapi_nba_markets.json``, from ``/v4/markets``):
  moneyline 111 (outcome '1' home, '2' away); "Handicap (incl. overtime)" with ``handicap`` = the HOME line
  (outcome '1' = home at ``h``, '2' = away at ``-h``); "Over Under (incl. overtime)" with ``handicap`` = the total.
  Pinnacle quotes ~10-20 alternative lines at once.
* Pre-match history exists from about February 2026: a 2026-01-15 game answered 404, a 2026-01-25 game had only
  in-play quotes, 2026-02-05 onwards had full pre-match paths (opening 1-3 days before tip).

What is stored: the MAIN line path. At every ``createdAt`` the main line of spreads/totals is the line whose two
sides are both active and closest to even (smallest |ln(p1/p2)|; ties: larger limit, then smaller |line|); a pair of
rows is written whenever the main line or one of its prices changes. Only quotes at or before the cutoff
(``trueStartTime`` when plausible, else the earlier of the listed start and our ``commence_time``) are kept.
* Fixtures mapped to a ``game`` row: ``odds_history`` under ``op_<book>`` (``op_pinnacle`` is NOT ``is_sharp``),
  ``book_last_update`` = ``captured_at`` = ``createdAt``, american price rounded from the decimal.
* Fixtures without a ``game`` row (seasons before the live pipeline), mapped through ``player_game_log``:
  ``oddspapi_quote`` with the exact decimal price.

Missed-close recovery: a game that tipped off without a ``closing`` marker but with ``op_pinnacle`` rows gets a
``closing_oddspapi`` marker; ``market_close`` / ``clv_report`` / ``paper_report`` use it only where asked to and
label it.
"""
import gzip
import json
import logging
import math
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple
from zoneinfo import ZoneInfo

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel import Session

from app.config import settings
from app.models import (
    CAPTURE_CLOSING,
    CAPTURE_CLOSING_ODDSPAPI,
    BetSide,
    Game,
    MarketType,
    OddsHistory,
    OddsPapiFixture,
    OddsPapiQuote,
    OddsPapiRequest,
    OddsSnapshotCapture,
    PlayerGameLog,
    Sportsbook,
)
from app.services.odds_ingestion import OddsIngestionService, parse_api_datetime
from app.services.oddspapi_client import (
    ENDPOINT_FIXTURES,
    BudgetExceeded,
    OddsPapiClient,
    OddsPapiError,
    QuotaExhausted,
    month_start_utc,
)

logger = logging.getLogger(__name__)

NBA_SPORT_ID = 11
NBA_TOURNAMENT_ID = 132
BOOK_PREFIX = "op_"
OP_PINNACLE = "op_pinnacle"
BOOK_TITLES = {"pinnacle": "Pinnacle", "draftkings": "DraftKings", "fanduel": "FanDuel"}
EU_BOOKS = {"pinnacle"}
STATUS_FINISHED = 2
STATUS_CANCELLED = 3

MATCH_TOLERANCE = timedelta(hours=6)  # a team pair never meets twice within 6 h
RESULT_GRACE = timedelta(hours=3)  # same grace as results_sync: a game older than this is over
TRUE_START_WINDOW = (timedelta(hours=-1), timedelta(hours=3))  # trueStartTime must sit near the listed start
LISTING_DEBOUNCE = timedelta(hours=20)  # at most one season listing per day
HISTORY_START = datetime(2026, 1, 1, tzinfo=timezone.utc)  # vendor claim; pre-match paths really start ~2026-02
BACKFILL_WINDOW = (datetime(2026, 1, 1, tzinfo=timezone.utc), datetime(2026, 7, 1, tzinfo=timezone.utc))
EASTERN = ZoneInfo("America/New_York")
MARKETS_FILE = Path(__file__).resolve().parents[1] / "data" / "oddspapi_nba_markets.json"

LABEL_SEASON = "season"
LABEL_BACKFILL = "backfill-2026"
PRIORITY_MISSED_CLOSE = 1
PRIORITY_CURRENT_SEASON = 2
PRIORITY_BACKFILL = 3

_MARKET_OF_TYPE = {"moneyline": MarketType.h2h, "spreads": MarketType.spreads, "totals": MarketType.totals}
_SIDE_NAMES = {"moneyline": ("1", "2"), "spreads": ("1", "2"), "totals": ("Over", "Under")}


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


# ------------------------------------------------------------------------------------------------ catalogue

@dataclass(frozen=True)
class MarketSpec:
    market_type: str  # moneyline | spreads | totals
    handicap: float
    outcomes: Dict[str, str]  # outcomeId -> '1' | '2' | 'Over' | 'Under'


@lru_cache(maxsize=4)
def load_market_catalog(path: Path = MARKETS_FILE) -> Dict[str, MarketSpec]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return {
        mid: MarketSpec(spec["type"], float(spec["handicap"]) + 0.0, dict(spec["outcomes"]))
        for mid, spec in raw["markets"].items()
    }


# ------------------------------------------------------------------------------------------------ prices

def decimal_to_american(price: float) -> int:
    """Decimal odds -> integer American odds (always <= -100 or >= +100)."""
    if price <= 1.0:
        raise ValueError(f"decimal price must exceed 1: {price}")
    if price >= 2.0:
        return max(100, int(round((price - 1.0) * 100.0)))
    return min(-100, int(round(-100.0 / (price - 1.0))))


# ------------------------------------------------------------------------------------------------ fixtures

@dataclass(frozen=True)
class FixtureInfo:
    fixture_id: str
    tournament_id: int
    status_id: int
    start_time: datetime
    true_start_time: Optional[datetime]
    home_name: str
    away_name: str
    home_abbr: Optional[str] = None
    away_abbr: Optional[str] = None


def parse_fixtures(payload: Iterable[dict]) -> Tuple[List[FixtureInfo], int]:
    """Fixtures of a listing; returns (fixtures, invalid count). participant1 is the home team."""
    out: List[FixtureInfo] = []
    invalid = 0
    for item in payload or []:
        start = parse_api_datetime(item.get("startTime")) if isinstance(item, dict) else None
        fid = item.get("fixtureId") if isinstance(item, dict) else None
        home, away = (item.get("participant1Name"), item.get("participant2Name")) if isinstance(item, dict) else (None, None)
        if not (fid and start and home and away):
            invalid += 1
            continue
        out.append(
            FixtureInfo(
                fixture_id=str(fid),
                tournament_id=int(item.get("tournamentId") or 0),
                status_id=int(item.get("statusId") if item.get("statusId") is not None else -1),
                start_time=start,
                true_start_time=parse_api_datetime(item.get("trueStartTime")),
                home_name=str(home),
                away_name=str(away),
                home_abbr=item.get("participant1Abbr"),
                away_abbr=item.get("participant2Abbr"),
            )
        )
    return out, invalid


def close_cutoff(start: datetime, true_start: Optional[datetime], commence: Optional[datetime] = None) -> datetime:
    """
    The last instant a pre-match quote may carry. ``trueStartTime`` (the real tip) when it sits near the listed
    start; otherwise the earlier of the listed start and our ``commence_time`` (in-play quotes begin within minutes
    of the tip, so erring early only drops the last pre-match minutes).
    """
    start = _aware(start)
    if true_start is not None:
        true_start = _aware(true_start)
        if start + TRUE_START_WINDOW[0] <= true_start <= start + TRUE_START_WINDOW[1]:
            return true_start
    candidates = [start] + ([_aware(commence)] if commence is not None else [])
    return min(candidates)


# ------------------------------------------------------------------------------------------------ paths

@dataclass(frozen=True)
class PathQuote:
    bookmaker: str  # vendor slug
    market: MarketType
    side: BetSide
    line: Optional[float]
    price_decimal: float
    created_at: datetime


@dataclass
class PathStats:
    entries_seen: int = 0
    prematch_entries: int = 0
    post_cutoff_entries: int = 0
    invalid_entries: int = 0
    unknown_markets: int = 0  # market ids outside the full-game moneyline/spread/total catalogue (periods, props...)
    quotes: int = 0
    books: List[str] = field(default_factory=list)


def _main_line(lines: Dict[float, Dict[str, Tuple[float, bool, float]]], market_type: str):
    """(line, price side A, price side B) of the current main line, or None when no line has both sides active."""
    a_name, b_name = _SIDE_NAMES[market_type]
    best = None
    for handicap, sides in lines.items():
        a, b = sides.get(a_name), sides.get(b_name)
        if a is None or b is None or not (a[1] and b[1]):
            continue
        score = (abs(math.log(a[0] / b[0])), -min(a[2], b[2]), abs(handicap), handicap)
        if best is None or score < best[0]:
            best = (score, (handicap, a[0], b[0]))
    return None if best is None else best[1]


def _pair(book: str, market_type: str, main, ts: datetime) -> List[PathQuote]:
    handicap, price_a, price_b = main
    if market_type == "moneyline":
        return [
            PathQuote(book, MarketType.h2h, BetSide.home, None, price_a, ts),
            PathQuote(book, MarketType.h2h, BetSide.away, None, price_b, ts),
        ]
    if market_type == "spreads":
        return [
            PathQuote(book, MarketType.spreads, BetSide.home, handicap + 0.0, price_a, ts),
            PathQuote(book, MarketType.spreads, BetSide.away, -handicap + 0.0, price_b, ts),
        ]
    return [
        PathQuote(book, MarketType.totals, BetSide.over, handicap, price_a, ts),
        PathQuote(book, MarketType.totals, BetSide.under, handicap, price_b, ts),
    ]


def main_line_path(
    payload: dict,
    cutoff: datetime,
    catalog: Optional[Dict[str, MarketSpec]] = None,
    bookmakers: Optional[Sequence[str]] = None,
) -> Tuple[List[PathQuote], PathStats]:
    """The main-line pre-match path of every bookmaker in a historical-odds payload (see the module docstring)."""
    catalog = load_market_catalog() if catalog is None else catalog
    cutoff = _aware(cutoff)
    stats = PathStats()
    quotes: List[PathQuote] = []
    books = (payload or {}).get("bookmakers") or {}
    for book in sorted(books):
        if bookmakers and book not in bookmakers:
            continue
        stats.books.append(book)
        events = []
        for market_id, market_node in ((books[book] or {}).get("markets") or {}).items():
            spec = catalog.get(str(market_id))
            if spec is None:
                stats.unknown_markets += 1
                continue
            for outcome_id, outcome_node in ((market_node or {}).get("outcomes") or {}).items():
                name = spec.outcomes.get(str(outcome_id))
                if name is None:
                    stats.unknown_markets += 1
                    continue
                for player_id, entries in ((outcome_node or {}).get("players") or {}).items():
                    if str(player_id) != "0":
                        continue
                    for entry in entries or []:
                        stats.entries_seen += 1
                        ts = parse_api_datetime(entry.get("createdAt")) if isinstance(entry, dict) else None
                        price = entry.get("price") if isinstance(entry, dict) else None
                        if ts is None or not isinstance(price, (int, float)) or price <= 1.0:
                            stats.invalid_entries += 1
                            continue
                        if ts > cutoff:
                            stats.post_cutoff_entries += 1
                            continue
                        stats.prematch_entries += 1
                        active = entry.get("active")
                        events.append((
                            ts, spec.market_type, spec.handicap, name, float(price),
                            True if active is None else bool(active), float(entry.get("limit") or 0.0),
                        ))
        events.sort(key=lambda e: (e[0], e[1], e[2], e[3]))
        state: Dict[str, Dict[float, Dict[str, Tuple[float, bool, float]]]] = defaultdict(lambda: defaultdict(dict))
        emitted: Dict[str, tuple] = {}
        i = 0
        while i < len(events):
            ts = events[i][0]
            touched: Set[str] = set()
            while i < len(events) and events[i][0] == ts:
                _, market_type, handicap, name, price, active, limit = events[i]
                state[market_type][handicap][name] = (price, active, limit)
                touched.add(market_type)
                i += 1
            for market_type in sorted(touched):
                main = _main_line(state[market_type], market_type)
                if main is None or emitted.get(market_type) == main:
                    continue  # a suspended market keeps its last main line; an unchanged one writes nothing
                emitted[market_type] = main
                quotes.extend(_pair(book, market_type, main, ts))
    stats.quotes = len(quotes)
    return quotes, stats


@dataclass(frozen=True)
class OpenClose:
    """First and last main-line pair of one market in a path (sides in the order home/away or over/under)."""

    market: str
    open_at: datetime
    open_line: Optional[float]  # home line for spreads, total for totals, None for h2h
    open_prices: Tuple[float, float]
    close_at: datetime
    close_line: Optional[float]
    close_prices: Tuple[float, float]


PathPair = Tuple[datetime, Optional[float], Tuple[float, float]]  # (created_at, home line / total, (home|over, away|under))


def main_line_pairs(rows: Iterable[Tuple[str, str, Optional[float], float, datetime]]) -> Dict[str, List[PathPair]]:
    """
    market -> chronological main-line pairs from (market, side, line, price_decimal, created_at) rows of ONE book and
    game. Only instants where both sides were written together count (they always are for stored paths).
    """
    first_side = {"h2h": "home", "spreads": "home", "totals": "over"}
    by_market: Dict[str, Dict[datetime, Dict[str, Tuple[Optional[float], float]]]] = defaultdict(lambda: defaultdict(dict))
    for market, side, line, price, ts in rows:
        by_market[market][_aware(ts)][side] = (None if line is None else float(line), float(price))
    out: Dict[str, List[PathPair]] = {}
    for market, by_ts in by_market.items():
        if market not in first_side:
            continue
        a = first_side[market]
        pairs: List[PathPair] = []
        for ts in sorted(by_ts):
            sides = by_ts[ts]
            if len(sides) != 2 or a not in sides:
                continue
            b = next(s for s in sides if s != a)
            pairs.append((ts, sides[a][0], (sides[a][1], sides[b][1])))
        if pairs:
            out[market] = pairs
    return out


def open_close_from_pairs(pairs_by_market: Mapping[str, Sequence[PathPair]]) -> Dict[str, OpenClose]:
    out: Dict[str, OpenClose] = {}
    for market, pairs in pairs_by_market.items():
        if pairs:
            out[market] = OpenClose(market, pairs[0][0], pairs[0][1], pairs[0][2], pairs[-1][0], pairs[-1][1], pairs[-1][2])
    return out


def open_close(rows: Iterable[Tuple[str, str, Optional[float], float, datetime]]) -> Dict[str, OpenClose]:
    """market -> OpenClose (first and last main-line pair) from the rows of ONE book and game (see main_line_pairs)."""
    return open_close_from_pairs(main_line_pairs(rows))


# ------------------------------------------------------------------------------------------------ mapping

@dataclass
class MappingStats:
    seen: int = 0
    new: int = 0
    mapped_game: int = 0
    mapped_nba: int = 0
    unmatched: int = 0
    invalid: int = 0
    reasons: Dict[str, int] = field(default_factory=dict)

    def count(self, reason: str) -> None:
        self.unmatched += 1
        self.reasons[reason] = self.reasons.get(reason, 0) + 1


class FixtureMapper:
    """Maps a fixture to a ``game`` row (teams + tip time within 6 h) or to a ``player_game_log`` game id."""

    def __init__(self, session: Session):
        self.session = session
        self._ingestion = OddsIngestionService(session)

    def team_id(self, name: str, abbr: Optional[str] = None) -> Optional[int]:
        team = self._ingestion.resolve_team(name)
        if team is None and abbr:
            team = self._ingestion.resolve_team(abbr)
        return None if team is None else team.id

    def game_for(self, home_id: int, away_id: int, start: datetime) -> Tuple[Optional[Game], Optional[str]]:
        start = _aware(start)
        games = [
            g for g in self.session.execute(
                select(Game).where(Game.home_team_id == home_id, Game.away_team_id == away_id)
            ).scalars()
            if abs(_aware(g.commence_time) - start) <= MATCH_TOLERANCE
        ]
        if len(games) == 1:
            return games[0], None
        if len(games) > 1:
            return None, "ambiguous_game"
        swapped = self.session.execute(
            select(Game.id, Game.commence_time).where(Game.home_team_id == away_id, Game.away_team_id == home_id)
        ).all()
        if any(abs(_aware(c) - start) <= MATCH_TOLERANCE for _, c in swapped):
            return None, "home_away_mismatch"
        return None, None

    def nba_game_for(self, home_id: int, away_id: int, start: datetime) -> Tuple[Optional[str], Optional[str]]:
        """The ``player_game_log`` game of that Eastern date with exactly these two teams, home side checked."""
        day = _aware(start).astimezone(EASTERN).date()
        rows = self.session.execute(
            select(PlayerGameLog.game_id, PlayerGameLog.team_id, PlayerGameLog.matchup)
            .where(PlayerGameLog.game_date == day, PlayerGameLog.team_id.in_([home_id, away_id]))
            .distinct()
        ).all()
        teams: Dict[str, Set[int]] = defaultdict(set)
        home_matchups: Dict[str, Set[str]] = defaultdict(set)
        for game_id, team_id, matchup in rows:
            teams[game_id].add(team_id)
            if team_id == home_id and matchup:
                home_matchups[game_id].add(matchup)
        both = [gid for gid, ts in teams.items() if ts == {home_id, away_id}]
        if not both:
            return None, None
        if len(both) > 1:
            return None, "ambiguous_nba_game"
        gid = both[0]
        matchups = home_matchups.get(gid, set())
        if matchups and not any("vs." in m for m in matchups):
            return None, "home_away_mismatch"
        return gid, None

    def map_row(self, row: OddsPapiFixture, now: datetime) -> Optional[str]:
        """Fills ``game_id`` / ``nba_game_id`` of an unmapped row; returns the unmatched reason (None = mapped)."""
        if row.home_team_id is None or row.away_team_id is None or row.home_team_id == row.away_team_id:
            return "team_unresolved"
        game, reason = self.game_for(row.home_team_id, row.away_team_id, row.start_time)
        if game is not None:
            row.game_id = game.id
            return None
        if reason is not None:
            return reason
        if _aware(row.start_time) > _aware(now) - RESULT_GRACE:
            return "not_finished"
        nba_id, reason = self.nba_game_for(row.home_team_id, row.away_team_id, row.start_time)
        if nba_id is not None:
            row.nba_game_id = nba_id
            return None
        return reason or "no_game"


def upsert_fixtures(session: Session, infos: Sequence[FixtureInfo], now: datetime) -> MappingStats:
    """Inserts/updates the catalogue rows of a listing and maps every unmapped row. Commits."""
    stats = MappingStats()
    mapper = FixtureMapper(session)
    existing = {
        row.fixture_id: row
        for row in session.execute(
            select(OddsPapiFixture).where(OddsPapiFixture.fixture_id.in_([i.fixture_id for i in infos]))
        ).scalars()
    } if infos else {}
    for info in infos:
        stats.seen += 1
        row = existing.get(info.fixture_id)
        if row is None:
            row = OddsPapiFixture(
                fixture_id=info.fixture_id, tournament_id=info.tournament_id, status_id=info.status_id,
                start_time=info.start_time, true_start_time=info.true_start_time, home_name=info.home_name,
                away_name=info.away_name, listed_at=now,
                home_team_id=mapper.team_id(info.home_name, info.home_abbr),
                away_team_id=mapper.team_id(info.away_name, info.away_abbr),
            )
            stats.new += 1
        else:
            row.status_id, row.start_time, row.true_start_time = info.status_id, info.start_time, info.true_start_time
            row.listed_at = now
        if row.game_id is None and row.nba_game_id is None:
            row.unmatched_reason = mapper.map_row(row, now)
        _count_mapping(row, stats)
        session.add(row)
    session.commit()
    return stats


def remap_unmatched(session: Session, now: datetime) -> MappingStats:
    """Retries the mapping of finished fixtures still unmapped (results or game rows may have arrived since)."""
    stats = MappingStats()
    mapper = FixtureMapper(session)
    rows = session.execute(
        select(OddsPapiFixture).where(
            OddsPapiFixture.game_id.is_(None), OddsPapiFixture.nba_game_id.is_(None),
            OddsPapiFixture.status_id == STATUS_FINISHED,
        )
    ).scalars().all()
    for row in rows:
        stats.seen += 1
        row.unmatched_reason = mapper.map_row(row, now)
        _count_mapping(row, stats)
        session.add(row)
    if rows:
        session.commit()
    return stats


def _count_mapping(row: OddsPapiFixture, stats: MappingStats) -> None:
    if row.game_id is not None:
        stats.mapped_game += 1
    elif row.nba_game_id is not None:
        stats.mapped_nba += 1
    else:
        stats.count(row.unmatched_reason or "no_game")


# ------------------------------------------------------------------------------------------------ storage

@dataclass
class StoreResult:
    status: str  # stored | no_prematch
    target: str  # odds_history | oddspapi_quote
    stats: PathStats
    inserted: int = 0
    duplicate: int = 0


def op_sportsbook(session: Session, book: str) -> Sportsbook:
    """The ``op_<book>`` sportsbook row (created on first use; never sharp: recovered closes are opt-in)."""
    key = f"{BOOK_PREFIX}{book}"
    row = session.execute(select(Sportsbook).where(Sportsbook.key == key)).scalars().first()
    if row is None:
        row = Sportsbook(
            key=key, name=f"{BOOK_TITLES.get(book, book)} (OddsPapi)",
            region="eu" if book in EU_BOOKS else "us", is_sharp=False,
        )
        session.add(row)
        session.flush()
    return row


def store_path(
    session: Session,
    fixture: OddsPapiFixture,
    payload: dict,
    now: datetime,
    bookmakers: Optional[Sequence[str]] = None,
    etag: Optional[str] = None,
) -> StoreResult:
    """Derives and stores the main-line path of a fixture (idempotent) and updates the catalogue row. Commits."""
    game = session.get(Game, fixture.game_id) if fixture.game_id is not None else None
    cutoff = close_cutoff(fixture.start_time, fixture.true_start_time, game.commence_time if game else None)
    quotes, stats = main_line_path(payload, cutoff, bookmakers=bookmakers)
    if game is not None:
        result = _store_odds_history(session, game, quotes, stats)
    else:
        result = _store_fixture_quotes(session, fixture, quotes, stats)
    fixture.path_status = result.status
    fixture.path_fetched_at = now
    fixture.path_etag = etag
    fixture.path_bookmakers = ",".join(stats.books) or None
    fixture.prematch_entries = stats.prematch_entries
    fixture.quotes_stored = len(quotes)
    session.add(fixture)
    session.commit()
    return result


def _store_odds_history(session: Session, game: Game, quotes: List[PathQuote], stats: PathStats) -> StoreResult:
    result = StoreResult("stored" if quotes else "no_prematch", "odds_history", stats)
    if not quotes:
        return result
    books = {book: op_sportsbook(session, book) for book in {q.bookmaker for q in quotes}}
    rows = [
        {
            "game_id": game.id,
            "sportsbook_id": books[q.bookmaker].id,
            "market": q.market,
            "player_id": None,
            "side": q.side,
            "line": None if q.line is None else Decimal(str(q.line)).quantize(Decimal("0.1")),
            "price_american": decimal_to_american(q.price_decimal),
            "book_last_update": q.created_at,
            "captured_at": q.created_at,
        }
        for q in quotes
    ]
    ingest = OddsIngestionService(session)._insert_rows(rows)  # dedupes on the odds_history unique key; commits
    result.inserted, result.duplicate = ingest.inserted, ingest.skipped_duplicate
    return result


def _store_fixture_quotes(
    session: Session, fixture: OddsPapiFixture, quotes: List[PathQuote], stats: PathStats
) -> StoreResult:
    result = StoreResult("stored" if quotes else "no_prematch", "oddspapi_quote", stats)
    if not quotes:
        return result
    if fixture.id is None:
        session.flush()

    def key(book, market, side, line, ts):
        m = market.value if hasattr(market, "value") else str(market)
        s = side.value if hasattr(side, "value") else str(side)
        ln = None if line is None else Decimal(str(line)).quantize(Decimal("0.1"))
        return (book, m, s, ln, _aware(ts).replace(tzinfo=None))

    seen = {
        key(*r)
        for r in session.execute(
            select(OddsPapiQuote.bookmaker, OddsPapiQuote.market, OddsPapiQuote.side, OddsPapiQuote.line,
                   OddsPapiQuote.created_at).where(OddsPapiQuote.fixture_row_id == fixture.id)
        ).all()
    }
    fresh = []
    for q in quotes:
        k = key(q.bookmaker, q.market, q.side, q.line, q.created_at)
        if k in seen:
            result.duplicate += 1
            continue
        seen.add(k)
        fresh.append({
            "fixture_row_id": fixture.id, "bookmaker": q.bookmaker, "market": q.market, "side": q.side,
            "line": k[3], "price_decimal": Decimal(f"{q.price_decimal:.4f}"), "created_at": q.created_at,
        })
    dialect = session.get_bind().dialect.name
    make_insert = {"postgresql": pg_insert, "sqlite": sqlite_insert}.get(dialect)
    table = OddsPapiQuote.__table__
    for start in range(0, len(fresh), 100):
        chunk = fresh[start : start + 100]
        if make_insert is not None:
            stmt = make_insert(table).values(chunk).on_conflict_do_nothing()
            inserted = len(session.execute(stmt.returning(table.c.id)).all())
        else:  # pragma: no cover - other dialects
            session.execute(table.insert().values(chunk))
            inserted = len(chunk)
        result.inserted += inserted
        result.duplicate += len(chunk) - inserted
    session.commit()
    return result


def mark_failed(session: Session, fixture: OddsPapiFixture, status: str, now: datetime) -> None:
    fixture.path_status = status
    fixture.path_fetched_at = now
    session.add(fixture)
    session.commit()


# ------------------------------------------------------------------------------------------------ recovery

def recover_missed_closes(session: Session, now: datetime, dry_run: bool = False) -> List[int]:
    """
    Writes a ``closing_oddspapi`` marker for every game that tipped off without a ``closing`` marker and has an
    ``op_pinnacle`` quote at or before its tip-off. Returns the game ids (that would be) marked. Commits.
    """
    from app.services.odds_snapshot import record_capture  # local import: odds_snapshot imports the Odds API stack

    book = session.execute(select(Sportsbook.id).where(Sportsbook.key == OP_PINNACLE)).scalar()
    if book is None:
        return []
    marked = exists().where(
        OddsSnapshotCapture.game_id == Game.id,
        OddsSnapshotCapture.kind.in_([CAPTURE_CLOSING, CAPTURE_CLOSING_ODDSPAPI]),
    )
    candidates = session.execute(
        select(Game.id, Game.commence_time).where(Game.status != "postponed", ~marked)
    ).all()
    due = {gid: _aware(c) for gid, c in candidates if _aware(c) <= _aware(now)}
    if not due:
        return []
    counts: Dict[int, int] = defaultdict(int)
    for game_id, captured_at in session.execute(
        select(OddsHistory.game_id, OddsHistory.captured_at).where(
            OddsHistory.sportsbook_id == book, OddsHistory.game_id.in_(list(due)), OddsHistory.player_id.is_(None)
        )
    ).all():
        if captured_at is not None and _aware(captured_at) <= due[game_id]:
            counts[game_id] += 1
    games = sorted(counts)
    if dry_run:
        return games
    for game_id in games:
        record_capture(session, game_id, CAPTURE_CLOSING_ODDSPAPI, now, credits_spent=0,
                       quotes_seen=counts[game_id], quotes_inserted=0)
    if games:
        session.commit()
    return games


# ------------------------------------------------------------------------------------------------ planning

@dataclass(frozen=True)
class ListingPlan:
    label: str
    start: datetime
    end: datetime
    reason: str


@dataclass(frozen=True)
class PathPlan:
    fixture_row_id: int
    fixture_id: str
    priority: int
    start_time: datetime
    game_id: Optional[int]
    nba_game_id: Optional[str]


@dataclass
class OddsPapiPlan:
    now: datetime
    monthly_budget: int
    billable_used: int
    reserve: int  # billable requests kept for the daily listings of the rest of the month
    listings: List[ListingPlan] = field(default_factory=list)
    paths: List[PathPlan] = field(default_factory=list)
    paths_due: Dict[int, int] = field(default_factory=dict)  # priority -> all due (before the per-run cap)
    unlinked_final_games: int = 0
    budget_blocked: bool = False  # a needed billable listing was held back by the monthly budget
    notes: List[str] = field(default_factory=list)

    @property
    def billable_remaining(self) -> int:
        return max(0, self.monthly_budget - self.billable_used)

    @property
    def billable_planned(self) -> int:
        return len(self.listings)


def billable_used_this_month(session: Session, now: datetime) -> int:
    return int(
        session.execute(
            select(func.count(OddsPapiRequest.id)).where(
                OddsPapiRequest.billable.is_(True), OddsPapiRequest.requested_at >= month_start_utc(now)
            )
        ).scalar_one()
    )


def days_left_in_month(now: datetime) -> int:
    now = _aware(now)
    first_next = (now.replace(day=1) + timedelta(days=32)).replace(day=1)
    return (first_next.date() - now.date()).days


def _unlinked_final_games(session: Session, now: datetime) -> List[datetime]:
    linked = exists().where(OddsPapiFixture.game_id == Game.id)
    rows = session.execute(
        select(Game.commence_time).where(Game.status == "final", ~linked)
    ).scalars().all()
    limit = _aware(now) - RESULT_GRACE
    return sorted(_aware(c) for c in rows if _aware(c) <= limit)


def _recent_listing(session: Session, now: datetime) -> bool:
    since = _aware(now) - LISTING_DEBOUNCE
    return session.execute(
        select(OddsPapiRequest.id).where(
            OddsPapiRequest.endpoint == ENDPOINT_FIXTURES, OddsPapiRequest.requested_at >= since
        ).limit(1)
    ).first() is not None


def plan_paths(session: Session, now: datetime, max_paths: int, include_backfill: bool = True) -> Tuple[List[PathPlan], Dict[int, int]]:
    """Fixtures whose path should be fetched, by priority then newest first (DB only)."""
    limit = _aware(now) - RESULT_GRACE
    closing = exists().where(
        OddsSnapshotCapture.game_id == OddsPapiFixture.game_id, OddsSnapshotCapture.kind == CAPTURE_CLOSING
    )
    pending = or_(OddsPapiFixture.path_status.is_(None), OddsPapiFixture.path_status == "error")
    rows = session.execute(
        select(OddsPapiFixture, Game.status, closing.label("has_closing"))
        .outerjoin(Game, Game.id == OddsPapiFixture.game_id)
        .where(pending, OddsPapiFixture.status_id == STATUS_FINISHED,
               or_(OddsPapiFixture.game_id.is_not(None), OddsPapiFixture.nba_game_id.is_not(None)))
    ).all()
    plans: List[PathPlan] = []
    for row, game_status, has_closing in rows:
        start = _aware(row.start_time)
        if start > limit or start < HISTORY_START:
            continue
        if row.game_id is not None:
            if game_status != "final":
                continue
            priority = PRIORITY_CURRENT_SEASON if has_closing else PRIORITY_MISSED_CLOSE
        else:
            if not include_backfill:
                continue
            priority = PRIORITY_BACKFILL
        plans.append(PathPlan(row.id, row.fixture_id, priority, start, row.game_id, row.nba_game_id))
    plans.sort(key=lambda p: (p.priority, -p.start_time.timestamp(), p.fixture_id))
    due: Dict[int, int] = defaultdict(int)
    for p in plans:
        due[p.priority] += 1
    return plans[: max(0, max_paths)], dict(due)


def plan_run(
    session: Session, now: datetime, *, max_paths: int, monthly_budget: int, include_backfill: bool = True
) -> OddsPapiPlan:
    """What a run would do, from the database alone (zero network): listings (billed) and paths (free)."""
    now = _aware(now)
    plan = OddsPapiPlan(
        now=now, monthly_budget=monthly_budget, billable_used=billable_used_this_month(session, now),
        reserve=days_left_in_month(now),
    )
    unlinked = _unlinked_final_games(session, now)
    plan.unlinked_final_games = len(unlinked)
    remaining = plan.billable_remaining
    if unlinked:
        if _recent_listing(session, now):
            plan.notes.append(f"{len(unlinked)} final game(s) not in the catalogue; a listing ran in the last 20 h")
        elif remaining < 1:
            plan.budget_blocked = True
            plan.notes.append(
                f"season listing needed but the monthly budget is used up ({plan.billable_used} of {monthly_budget})"
            )
        else:
            start = max(unlinked[0] - timedelta(days=1), HISTORY_START)
            plan.listings.append(ListingPlan(LABEL_SEASON, start, now, f"{len(unlinked)} final game(s) not in the catalogue"))
            remaining -= 1
    if include_backfill:
        has_backfill = session.execute(
            select(OddsPapiFixture.id).where(
                OddsPapiFixture.start_time >= BACKFILL_WINDOW[0], OddsPapiFixture.start_time < BACKFILL_WINDOW[1]
            ).limit(1)
        ).first() is not None
        listed_before = session.execute(
            select(OddsPapiRequest.id).where(
                OddsPapiRequest.label == LABEL_BACKFILL, OddsPapiRequest.status_code == 200
            ).limit(1)
        ).first() is not None
        if not has_backfill and not listed_before:
            if remaining - plan.reserve >= 1:
                plan.listings.append(
                    ListingPlan(LABEL_BACKFILL, BACKFILL_WINDOW[0], BACKFILL_WINDOW[1] - timedelta(seconds=1),
                                "Jan-Jun 2026 fixtures not in the catalogue (priority 3, leftover budget)")
                )
            else:
                plan.notes.append(
                    f"backfill listing held back: {remaining} billable left, {plan.reserve} reserved for daily listings"
                )
    plan.paths, plan.paths_due = plan_paths(session, now, max_paths, include_backfill)
    return plan


def format_plan(plan: OddsPapiPlan) -> str:
    lines = [
        f"OddsPapi budget: {plan.billable_used} of {plan.monthly_budget} billable requests used this UTC month "
        f"({plan.billable_remaining} left, {plan.reserve} reserved for daily listings)",
    ]
    for listing in plan.listings:
        lines.append(
            f"  listing [{listing.label}] GET /v4/fixtures tournamentId={NBA_TOURNAMENT_ID} "
            f"{listing.start:%Y-%m-%d}..{listing.end:%Y-%m-%d} (1 billable): {listing.reason}"
        )
    labels = {PRIORITY_MISSED_CLOSE: "missed close", PRIORITY_CURRENT_SEASON: "current season",
              PRIORITY_BACKFILL: "Jan-Jun 2026 backfill"}
    due = ", ".join(f"p{p} {labels[p]}: {n}" for p, n in sorted(plan.paths_due.items())) or "none"
    lines.append(f"  paths due (free, 5 s apart): {due}; this run: {len(plan.paths)}")
    for p in plan.paths[:10]:
        target = f"game {p.game_id}" if p.game_id is not None else f"nba {p.nba_game_id}"
        lines.append(f"    p{p.priority} {p.fixture_id} {p.start_time:%Y-%m-%d %H:%M}Z -> {target}")
    if len(plan.paths) > 10:
        lines.append(f"    ... {len(plan.paths) - 10} more")
    for note in plan.notes:
        lines.append(f"  note: {note}")
    return "\n".join(lines)


# ------------------------------------------------------------------------------------------------ run

@dataclass
class RunSummary:
    status: str = "ok"  # ok | skipped | budget | quota | error
    message: str = ""
    vendor_limit: Optional[int] = None
    vendor_count: Optional[int] = None
    listings: int = 0
    mapping: MappingStats = field(default_factory=MappingStats)
    paths_fetched: int = 0
    paths_stored: int = 0
    paths_no_prematch: int = 0
    paths_not_found: int = 0
    paths_failed: int = 0
    paths_not_modified: int = 0
    quotes_inserted: int = 0
    closes_recovered: List[int] = field(default_factory=list)
    requests: int = 0
    billable: int = 0
    errors: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)  # the plan's notes (held-back listings and why)


def raw_cache_path(raw_dir: Optional[Path], fixture_id: str, books: Sequence[str]) -> Optional[Path]:
    if raw_dir is None:
        return None
    return Path(raw_dir) / f"{fixture_id}_{'-'.join(books)}.json.gz"


def run_oddspapi(
    session: Session,
    client: OddsPapiClient,
    now: datetime,
    *,
    max_paths: int,
    bookmakers: Sequence[str],
    include_backfill: bool = True,
    min_remaining: int = 25,
    deadline: Optional[float] = None,
    clock: Callable[[], float] = time.monotonic,
    raw_dir: Optional[Path] = None,
) -> RunSummary:
    """
    One budgeted run: vendor quota check (free), the planned listings (billed), mapping, the planned paths (free)
    and the missed-close markers. Never raises for API trouble: the summary carries the status.
    """
    now = _aware(now)
    summary = RunSummary()
    books = [b.strip() for b in bookmakers if b and b.strip()]
    try:
        account = client.account()
        summary.vendor_limit, summary.vendor_count = account.get("request_limit"), account.get("request_count")
    except OddsPapiError as exc:
        summary.errors.append(f"account: {exc}")
    vendor_left = None
    if summary.vendor_limit is not None and summary.vendor_count is not None:
        vendor_left = summary.vendor_limit - summary.vendor_count

    plan = plan_run(session, now, max_paths=max_paths, monthly_budget=client.monthly_budget,
                    include_backfill=include_backfill)
    summary.notes.extend(plan.notes)
    if plan.budget_blocked:
        summary.status = "budget"
    try:
        for listing in plan.listings:
            if vendor_left is not None and vendor_left - 1 < min_remaining:
                summary.errors.append(f"listing [{listing.label}] held back: vendor quota left {vendor_left} < floor {min_remaining}")
                continue
            payload = client.list_fixtures(NBA_TOURNAMENT_ID, listing.start, listing.end, label=listing.label)
            summary.listings += 1
            if vendor_left is not None:
                vendor_left -= 1
            infos, invalid = parse_fixtures(payload)
            stats = upsert_fixtures(session, infos, now)
            stats.invalid += invalid
            _merge_mapping(summary.mapping, stats)
        _merge_mapping(summary.mapping, remap_unmatched(session, now))

        paths, _ = plan_paths(session, now, max_paths, include_backfill)
        for item in paths:
            if deadline is not None and clock() >= deadline:
                summary.errors.append("time budget reached; the rest waits for the next run")
                break
            fixture = session.get(OddsPapiFixture, item.fixture_row_id)
            cache = raw_cache_path(raw_dir, fixture.fixture_id, books)
            etag = fixture.path_etag if cache is not None and cache.exists() and fixture.path_bookmakers == ",".join(sorted(books)) else None
            try:
                response = client.historical_odds(fixture.fixture_id, books, etag=etag)
            except (BudgetExceeded, QuotaExhausted):
                raise
            except OddsPapiError as exc:
                summary.paths_failed += 1
                summary.errors.append(f"{fixture.fixture_id}: {exc}")
                mark_failed(session, fixture, "error", now)
                continue
            summary.paths_fetched += 1
            if response.not_found:
                summary.paths_not_found += 1
                mark_failed(session, fixture, "not_found", now)
                continue
            payload = response.data
            if response.not_modified:
                summary.paths_not_modified += 1
                payload = json.loads(gzip.decompress(cache.read_bytes()))
            elif cache is not None and isinstance(payload, dict):
                try:
                    cache.parent.mkdir(parents=True, exist_ok=True)
                    cache.write_bytes(gzip.compress(json.dumps(payload).encode("utf-8")))
                except OSError as exc:
                    logger.warning(f"oddspapi: could not cache {fixture.fixture_id}: {exc}")
            if not isinstance(payload, dict):
                summary.paths_failed += 1
                mark_failed(session, fixture, "error", now)
                continue
            try:
                result = store_path(session, fixture, payload, now, bookmakers=books, etag=response.etag)
            except Exception as exc:  # one bad payload never stops the run
                logger.exception(f"oddspapi: storing {fixture.fixture_id} failed")
                session.rollback()
                summary.paths_failed += 1
                summary.errors.append(f"{fixture.fixture_id}: store failed: {type(exc).__name__}: {exc}")
                mark_failed(session, session.get(OddsPapiFixture, item.fixture_row_id), "error", now)
                continue
            summary.quotes_inserted += result.inserted
            if result.status == "stored":
                summary.paths_stored += 1
            else:
                summary.paths_no_prematch += 1
    except BudgetExceeded as exc:
        summary.status = "budget"
        summary.errors.append(str(exc))
    except QuotaExhausted as exc:
        summary.status = "quota"
        summary.errors.append(str(exc))
    except OddsPapiError as exc:
        summary.status = "error"
        summary.errors.append(str(exc))

    try:
        summary.closes_recovered = recover_missed_closes(session, now)
    except Exception as exc:
        logger.exception("oddspapi: missed-close recovery failed")
        session.rollback()
        summary.errors.append(f"recovery: {type(exc).__name__}: {exc}")
    summary.requests, summary.billable = client.requests_sent, client.billable_sent
    summary.message = (
        f"{summary.listings} listing(s), {summary.paths_fetched} path(s) fetched "
        f"({summary.paths_stored} stored, {summary.paths_no_prematch} without pre-match quotes, "
        f"{summary.paths_not_found} not found, {summary.paths_failed} failed), {summary.quotes_inserted} quote(s) "
        f"inserted, {len(summary.closes_recovered)} missed close(s) recovered; requests {summary.requests} "
        f"({summary.billable} billable)"
    )
    return summary


def _merge_mapping(total: MappingStats, part: MappingStats) -> None:
    total.seen += part.seen
    total.new += part.new
    total.mapped_game += part.mapped_game
    total.mapped_nba += part.mapped_nba
    total.unmatched += part.unmatched
    total.invalid += part.invalid
    for k, v in part.reasons.items():
        total.reasons[k] = total.reasons.get(k, 0) + v


def format_run(summary: RunSummary) -> str:
    lines = [f"[{summary.status}] {summary.message}"]
    if summary.vendor_limit is not None:
        lines.append(f"  vendor quota: {summary.vendor_count} of {summary.vendor_limit} used (from /v4/account)")
    m = summary.mapping
    if m.seen:
        reasons = ", ".join(f"{k}={v}" for k, v in sorted(m.reasons.items())) or "none"
        lines.append(
            f"  fixtures: {m.seen} seen ({m.new} new): {m.mapped_game} -> game, {m.mapped_nba} -> player_game_log, "
            f"{m.unmatched} unmatched ({reasons}), {m.invalid} invalid"
        )
    if summary.closes_recovered:
        lines.append(f"  closing_oddspapi markers: games {', '.join(map(str, summary.closes_recovered[:20]))}")
    for note in summary.notes:
        lines.append(f"  note: {note}")
    for error in summary.errors[:10]:
        lines.append(f"  ERROR {error}")
    return "\n".join(lines)


# ------------------------------------------------------------------------------------------------ coverage

@dataclass
class Coverage:
    fixtures: int = 0
    by_status: Dict[str, int] = field(default_factory=dict)
    mapped_game: int = 0
    mapped_nba: int = 0
    unmatched: int = 0
    final_games: int = 0
    final_games_with_closing: int = 0
    final_games_recovered: int = 0
    final_games_without_close: int = 0
    billable_this_month: int = 0
    requests_this_month: int = 0


def coverage(session: Session, now: datetime) -> Coverage:
    cov = Coverage()
    for status, game_id, nba_id in session.execute(
        select(OddsPapiFixture.path_status, OddsPapiFixture.game_id, OddsPapiFixture.nba_game_id)
    ).all():
        cov.fixtures += 1
        key = status or "pending"
        cov.by_status[key] = cov.by_status.get(key, 0) + 1
        if game_id is not None:
            cov.mapped_game += 1
        elif nba_id is not None:
            cov.mapped_nba += 1
        else:
            cov.unmatched += 1
    kinds: Dict[int, Set[str]] = defaultdict(set)
    for game_id, kind in session.execute(
        select(OddsSnapshotCapture.game_id, OddsSnapshotCapture.kind).where(
            OddsSnapshotCapture.kind.in_([CAPTURE_CLOSING, CAPTURE_CLOSING_ODDSPAPI])
        )
    ).all():
        kinds[game_id].add(kind)
    for (game_id,) in session.execute(select(Game.id).where(Game.status == "final")).all():
        cov.final_games += 1
        k = kinds.get(game_id, set())
        if CAPTURE_CLOSING in k:
            cov.final_games_with_closing += 1
        elif CAPTURE_CLOSING_ODDSPAPI in k:
            cov.final_games_recovered += 1
        else:
            cov.final_games_without_close += 1
    since = month_start_utc(now)
    for billable, in session.execute(select(OddsPapiRequest.billable).where(OddsPapiRequest.requested_at >= since)).all():
        cov.requests_this_month += 1
        cov.billable_this_month += 1 if billable else 0
    return cov


def format_coverage(cov: Coverage) -> str:
    statuses = ", ".join(f"{k} {v}" for k, v in sorted(cov.by_status.items())) or "none"
    return "\n".join([
        f"Catalogue: {cov.fixtures} fixture(s) ({statuses}); mapped {cov.mapped_game} to game rows, "
        f"{cov.mapped_nba} to player_game_log, {cov.unmatched} unmatched",
        f"Final games: {cov.final_games}; close captured by the tick {cov.final_games_with_closing}, recovered from "
        f"OddsPapi {cov.final_games_recovered}, still without a close {cov.final_games_without_close}",
        f"Requests this UTC month: {cov.requests_this_month} ({cov.billable_this_month} billable)",
    ])


def default_raw_dir() -> Path:
    """Gzipped raw payloads (outside git; lets a 304 revalidation re-derive a path and keeps the alt lines)."""
    import os

    base = Path(os.environ.get("ARCHETYPE_DATA_DIR", str(Path.home() / "ArchetypeNBA-data")))
    return base / "raw" / "oddspapi" / "paths"


def bookmakers_from_settings() -> List[str]:
    books = [b.strip() for b in (settings.ODDSPAPI_BOOKMAKERS or "pinnacle").split(",") if b.strip()]
    return books[:3] or ["pinnacle"]


def used_today(session: Session, start: datetime, end: datetime) -> bool:
    """True when any OddsPapi request was logged in [start, end) (the tick's once-per-local-day gate)."""
    return session.execute(
        select(OddsPapiRequest.id).where(and_(OddsPapiRequest.requested_at >= start, OddsPapiRequest.requested_at < end)).limit(1)
    ).first() is not None
