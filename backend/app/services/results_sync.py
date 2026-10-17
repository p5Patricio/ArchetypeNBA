"""
Results sync: final scores for the games we hold odds for, then the incremental Elo update.

``player_game_log`` stays the single source of truth for results (the Elo engine reads it), so the sync reuses
the player-level ``PlayerGameLogs`` endpoint of ``nba_api`` (free, no key) for a *date window* instead of adding
a second, team-level results path:

1. Find ``game`` rows that are still ``scheduled`` and tipped off more than ``RESULT_GRACE`` (3 h) ago. With none
   (and no final game waiting for its rating) the provider is never called, so a tick that has nothing to do
   costs no network.
2. Ingest the player logs of the needed date window (one call; an empty season type returns every game type of
   the window: regular season, NBA Cup, play-in and playoffs). Rows without a W/L result are ignored, so a game
   still in progress can never be stored with a partial box score. Rows of teams that are not in ``team`` are
   skipped instead of creating junk teams.
3. Match each pending game with a result by the pair of teams and the date (NBA ``game_date`` is the US date, so
   the tip-off is shifted to US time and +-1 day is tolerated; the closest date wins). Set ``nba_game_id``,
   ``home_score`` / ``away_score`` (sum of ``pts`` per team) and ``status = 'final'``. A game with no result
   (postponed) stays ``scheduled`` and is retried until it is older than ``LOOKBACK``.
4. ``EloRatingService.update_new_games()`` rates every new game of ``player_game_log``.

Atomicity: the provider is called first (a failure raises ``ResultsProviderError`` and nothing is written); logs
and game updates are written in one transaction that is rolled back on any error. The Elo update commits on its
own afterwards; if it fails, the finalized games are detected on the next call (a final game without rating
rows) and rated then.
"""
import logging
import math
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Mapping, Optional, Protocol, Sequence, Set, Tuple

from sqlalchemy import func, select
from sqlmodel import Session

from app.models import Game, Player, PlayerGameLog, Team, TeamEloRating
from app.services.elo_service import INCLUDED_GAME_TYPES, EloRatingService
from app.services.odds_ingestion import OddsIngestionService

logger = logging.getLogger(__name__)

RESULT_GRACE = timedelta(hours=3)  # a game is expected to be over this long after tip-off
LOOKBACK = timedelta(days=14)  # older unresolved games are no longer chased (postponed or lost)
MATCH_TOLERANCE_DAYS = 1
# Tip-off in UTC minus this offset gives the US date NBA uses as ``game_date``; 6 h covers EST/EDT evenings and
# late West-coast tips, and +-1 day of tolerance absorbs the rest.
US_DATE_OFFSET = timedelta(hours=6)

DEFAULT_TIMEOUT_SECONDS = 40
DEFAULT_RETRIES = 2
DEFAULT_BACKOFF_SECONDS = 2.0
_ID_CHUNK = 500
_REQUIRED_COLUMNS = ("PLAYER_ID", "TEAM_ID", "TEAM_ABBREVIATION", "GAME_ID", "GAME_DATE", "MATCHUP", "WL", "PTS")


class ResultsProviderError(RuntimeError):
    """The results provider could not deliver (network, rate limit, unexpected payload)."""


@dataclass(frozen=True)
class FetchedLogs:
    rows: List[Mapping[str, Any]]  # one mapping per player-game, keyed by the nba_api column names
    api_calls: int = 1


class GameResultsProvider(Protocol):
    def fetch_player_game_logs(self, season_label: str, date_from: date, date_to: date) -> FetchedLogs:
        """Player game logs of every game between the two dates (inclusive). Raises ResultsProviderError."""
        ...


class NbaApiResultsProvider:
    """``nba_api`` PlayerGameLogs for a date window: 40 s timeout, 2 retries with exponential backoff."""

    def __init__(
        self,
        timeout: int = DEFAULT_TIMEOUT_SECONDS,
        retries: int = DEFAULT_RETRIES,
        backoff_seconds: float = DEFAULT_BACKOFF_SECONDS,
        endpoint: Optional[Callable[..., Any]] = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.timeout = timeout
        self.retries = retries
        self.backoff_seconds = backoff_seconds
        self._endpoint = endpoint
        self._sleep = sleep

    def _request(self, season_label: str, date_from: date, date_to: date) -> List[Mapping[str, Any]]:
        endpoint = self._endpoint
        if endpoint is None:
            from nba_api.stats.endpoints import playergamelogs  # lazy: keeps tests and --help free of the import

            endpoint = playergamelogs.PlayerGameLogs
        frames = endpoint(
            season_nullable=season_label,
            date_from_nullable=date_from.strftime("%m/%d/%Y"),
            date_to_nullable=date_to.strftime("%m/%d/%Y"),
            timeout=self.timeout,
        ).get_data_frames()
        return frames[0].to_dict("records")

    def fetch_player_game_logs(self, season_label: str, date_from: date, date_to: date) -> FetchedLogs:
        attempts = 1 + max(0, self.retries)
        last_error: Optional[Exception] = None
        rows: Optional[List[Mapping[str, Any]]] = None
        calls = 0
        for attempt in range(attempts):
            calls += 1
            try:
                rows = self._request(season_label, date_from, date_to)
                break
            except Exception as exc:  # network, timeout, JSON decoding: all retryable
                last_error = exc
                logger.warning(f"results_sync: nba_api attempt {attempt + 1}/{attempts} failed: {type(exc).__name__}: {exc}")
                if attempt < attempts - 1:
                    self._sleep(self.backoff_seconds * (2**attempt))
        if rows is None:
            raise ResultsProviderError(
                f"nba_api PlayerGameLogs {season_label} {date_from}..{date_to} failed after {attempts} attempt(s): "
                f"{type(last_error).__name__}: {last_error}"
            ) from last_error
        if rows:
            missing = [column for column in _REQUIRED_COLUMNS if column not in rows[0]]
            if missing:
                raise ResultsProviderError(f"nba_api PlayerGameLogs payload lacks column(s): {', '.join(missing)}")
        return FetchedLogs(rows=rows, api_calls=calls)


# ------------------------------------------------------------------------------------------------ summary

@dataclass
class ResultsSyncSummary:
    now: datetime
    dry_run: bool = False
    games_pending: int = 0  # scheduled, tipped off > grace ago, inside the look-back
    games_stale: int = 0  # ... older than the look-back: not chased any more
    games_finalized: int = 0
    unmatched: List[str] = field(default_factory=list)  # pending games without a result yet
    logs_inserted: int = 0
    rows_skipped: int = 0  # rows without result, with an unknown team or without a date
    rating_rows_added: int = 0
    elo_rebuilt: bool = False
    elo_catch_up_games: int = 0  # final games that already waited for their rating before this call
    api_calls: int = 0

    @property
    def did_work(self) -> bool:
        return bool(self.games_finalized or self.rating_rows_added or self.logs_inserted)


# --------------------------------------------------------------------------------------------------- helpers

def _aware_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def us_game_date(commence_time: datetime) -> date:
    """The date NBA stamps on a game that tips off at ``commence_time`` (a US calendar date)."""
    return (_aware_utc(commence_time) - US_DATE_OFFSET).date()


def _num(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        number = float(value)
        return default if math.isnan(number) else int(number)
    except (TypeError, ValueError):
        return default


def _float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        number = float(value)
        return default if math.isnan(number) else number
    except (TypeError, ValueError):
        return default


def _parse_date(value: Any) -> Optional[date]:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if value is None:
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _chunks(items: Sequence, size: int = _ID_CHUNK):
    for start in range(0, len(items), size):
        yield items[start : start + size]


# ------------------------------------------------------------------------------------------------ pending games

def find_pending_games(session: Session, now: datetime) -> Tuple[List[Game], int]:
    """
    (games still waiting for a result, count of older ones that are no longer chased). Waiting = scheduled and
    tipped off more than ``RESULT_GRACE`` ago and not more than ``LOOKBACK`` ago, oldest first.
    """
    now = _aware_utc(now)
    ready_before = now - RESULT_GRACE
    rows = session.execute(
        select(Game).where(Game.status == "scheduled", Game.commence_time < now)
    ).scalars().all()
    # SQLite hands back naive datetimes: re-check in Python so the window never depends on the driver.
    due = [g for g in rows if _aware_utc(g.commence_time) < ready_before]
    pending = [g for g in due if _aware_utc(g.commence_time) >= now - LOOKBACK]
    pending.sort(key=lambda g: (_aware_utc(g.commence_time), g.id))
    return pending, len(due) - len(pending)


def count_final_games_without_ratings(session: Session) -> int:
    """
    Final games (with an nba_game_id) that have no row in ``team_elo_rating`` yet. Only game types Elo rates
    (regular season, playoffs, play-in, Cup final) count: a preseason or all-star game never gets ratings and
    would otherwise keep the catch-up pending forever.
    """
    rated = select(TeamEloRating.game_id).where(TeamEloRating.game_id.is_not(None))
    return int(
        session.execute(
            select(func.count(Game.id)).where(
                Game.status == "final",
                Game.nba_game_id.is_not(None),
                func.substr(Game.nba_game_id, 3, 1).in_(INCLUDED_GAME_TYPES),
                Game.nba_game_id.not_in(rated),
            )
        ).scalar_one()
    )


# ------------------------------------------------------------------------------------------------- ingestion

@dataclass
class IngestStats:
    logs_inserted: int = 0
    rows_skipped: int = 0
    players_created: int = 0


def ingest_player_game_logs(session: Session, rows: Sequence[Mapping[str, Any]], season_id: int) -> IngestStats:
    """
    Inserts the player-game rows that are not stored yet (unique on player + game). Flushes, never commits: the
    caller owns the transaction. Same column mapping as ``scripts/bulk_ingest_nba.py::ingest_bulk_game_logs``.
    """
    stats = IngestStats()
    if not rows:
        return stats

    teams = session.execute(select(Team.id, Team.abbreviation)).all()
    team_by_abbr = {abbr: team_id for team_id, abbr in teams}
    team_ids = {team_id for team_id, _ in teams}

    candidates = []
    for row in rows:
        player_id = _num(row.get("PLAYER_ID"))
        game_id = str(row.get("GAME_ID") or "").strip()
        game_date = _parse_date(row.get("GAME_DATE"))
        wl = str(row.get("WL") or "").strip().upper()
        abbr = str(row.get("TEAM_ABBREVIATION") or "").strip()
        team_id = team_by_abbr.get(abbr) or (_num(row.get("TEAM_ID")) if _num(row.get("TEAM_ID")) in team_ids else None)
        if not player_id or not game_id or game_date is None or wl not in ("W", "L") or team_id is None:
            stats.rows_skipped += 1
            continue
        candidates.append((player_id, game_id, game_date, wl, team_id, row))

    game_ids = sorted({c[1] for c in candidates})
    existing = set()
    for chunk in _chunks(game_ids):
        existing.update(
            session.execute(
                select(PlayerGameLog.player_id, PlayerGameLog.game_id).where(PlayerGameLog.game_id.in_(chunk))
            ).all()
        )

    known_players: Set[int] = set()
    wanted_players = sorted({c[0] for c in candidates})
    for chunk in _chunks(wanted_players):
        known_players.update(session.execute(select(Player.id).where(Player.id.in_(chunk))).scalars().all())

    new_logs: List[PlayerGameLog] = []
    for player_id, game_id, game_date, wl, team_id, row in candidates:
        key = (player_id, game_id)
        if key in existing:
            continue
        existing.add(key)
        if player_id not in known_players:
            session.add(
                Player(
                    id=player_id,
                    full_name=str(row.get("PLAYER_NAME") or f"Player {player_id}"),
                    headshot_url=f"https://cdn.nba.com/headshots/nba/latest/1040x760/{player_id}.png",
                )
            )
            known_players.add(player_id)
            stats.players_created += 1
        new_logs.append(
            PlayerGameLog(
                player_id=player_id,
                team_id=team_id,
                season_id=season_id,
                game_id=game_id,
                game_date=game_date,
                matchup=str(row.get("MATCHUP") or ""),
                wl=wl,
                min=_num(row.get("MIN")),
                fgm=_num(row.get("FGM")),
                fga=_num(row.get("FGA")),
                fg_pct=_float(row.get("FG_PCT")),
                fg3m=_num(row.get("FG3M")),
                fg3a=_num(row.get("FG3A")),
                fg3_pct=_float(row.get("FG3_PCT")),
                ftm=_num(row.get("FTM")),
                fta=_num(row.get("FTA")),
                ft_pct=_float(row.get("FT_PCT")),
                oreb=_num(row.get("OREB")),
                dreb=_num(row.get("DREB")),
                reb=_num(row.get("REB")),
                ast=_num(row.get("AST")),
                stl=_num(row.get("STL")),
                blk=_num(row.get("BLK")),
                tov=_num(row.get("TOV")),
                pf=_num(row.get("PF")),
                pts=_num(row.get("PTS")),
                plus_minus=_num(row.get("PLUS_MINUS")),
            )
        )
    if stats.players_created:
        session.flush()  # players first: player_game_log.player_id references them
    session.add_all(new_logs)
    session.flush()
    stats.logs_inserted = len(new_logs)
    return stats


# --------------------------------------------------------------------------------------------------- matching

@dataclass(frozen=True)
class GameResult:
    nba_game_id: str
    game_date: date
    points: Dict[int, int]  # team id -> sum of player pts


def load_results(session: Session, date_from: date, date_to: date) -> Dict[str, GameResult]:
    """Two-team results of ``player_game_log`` between the dates; a team's score is the sum of its players' pts."""
    stmt = (
        select(
            PlayerGameLog.game_id,
            PlayerGameLog.team_id,
            func.min(PlayerGameLog.game_date),
            func.sum(PlayerGameLog.pts),
        )
        .where(
            PlayerGameLog.game_date >= date_from,
            PlayerGameLog.game_date <= date_to,
            PlayerGameLog.wl.in_(("W", "L")),
        )
        .group_by(PlayerGameLog.game_id, PlayerGameLog.team_id)
    )
    by_game: Dict[str, List[Tuple[int, date, int]]] = {}
    for game_id, team_id, game_date, pts in session.execute(stmt).all():
        by_game.setdefault(game_id, []).append((team_id, game_date, int(pts or 0)))
    results: Dict[str, GameResult] = {}
    for game_id, sides in by_game.items():
        if len(sides) != 2:
            continue
        results[game_id] = GameResult(game_id, min(side[1] for side in sides), {side[0]: side[2] for side in sides})
    return results


def match_results(
    pending: Sequence[Game], results: Mapping[str, GameResult], taken: Set[str]
) -> Dict[int, GameResult]:
    """
    game.id -> result. Same two teams and a date within the tolerance; every result serves at most one game and
    the closest dates are assigned first, so two games of one series a few days apart never swap results.
    """
    candidates: List[Tuple[int, int, str]] = []
    for game in pending:
        expected = us_game_date(game.commence_time)
        teams = {game.home_team_id, game.away_team_id}
        for result in results.values():
            if result.nba_game_id in taken or set(result.points) != teams:
                continue
            distance = abs((result.game_date - expected).days)
            if distance <= MATCH_TOLERANCE_DAYS:
                candidates.append((distance, game.id, result.nba_game_id))
    candidates.sort()
    matched: Dict[int, GameResult] = {}
    used: Set[str] = set()
    for _, game_id, nba_game_id in candidates:
        if game_id in matched or nba_game_id in used:
            continue
        matched[game_id] = results[nba_game_id]
        used.add(nba_game_id)
    return matched


# ----------------------------------------------------------------------------------------------------- sync

def _describe(game: Game, abbreviations: Mapping[int, str]) -> str:
    home = abbreviations.get(game.home_team_id, str(game.home_team_id))
    away = abbreviations.get(game.away_team_id, str(game.away_team_id))
    return f"{away} @ {home} {us_game_date(game.commence_time).isoformat()}"


def sync_results(
    session: Session,
    provider: GameResultsProvider,
    now: datetime,
    *,
    dry_run: bool = False,
) -> ResultsSyncSummary:
    """See the module docstring. ``dry_run`` only counts what is pending: no provider call, no writes."""
    now = _aware_utc(now)
    summary = ResultsSyncSummary(now=now, dry_run=dry_run)
    pending, summary.games_stale = find_pending_games(session, now)
    summary.games_pending = len(pending)
    summary.elo_catch_up_games = count_final_games_without_ratings(session)
    if dry_run or (not pending and not summary.elo_catch_up_games):
        return summary

    if pending:
        try:
            _fetch_and_finalize(session, provider, pending, summary)
        except Exception:
            session.rollback()
            raise

    elo = EloRatingService(session).update_new_games()
    summary.rating_rows_added = elo.rows_written
    summary.elo_rebuilt = elo.rebuilt
    return summary


def _fetch_and_finalize(
    session: Session, provider: GameResultsProvider, pending: Sequence[Game], summary: ResultsSyncSummary
) -> None:
    season_service = OddsIngestionService(session)
    by_label: Dict[str, List[Game]] = {}
    for game in pending:
        label = OddsIngestionService.season_label_for(_aware_utc(game.commence_time).date())
        by_label.setdefault(label, []).append(game)

    # Network first, so a provider failure raises before anything is written.
    fetched: List[Tuple[str, List[Game], FetchedLogs, date, date]] = []
    for label, games in by_label.items():
        dates = [us_game_date(g.commence_time) for g in games]
        date_from = min(dates) - timedelta(days=MATCH_TOLERANCE_DAYS)
        date_to = max(dates) + timedelta(days=MATCH_TOLERANCE_DAYS)
        logs = provider.fetch_player_game_logs(label, date_from, date_to)
        summary.api_calls += logs.api_calls
        fetched.append((label, games, logs, date_from, date_to))

    taken = {
        nba_game_id
        for nba_game_id in session.execute(select(Game.nba_game_id).where(Game.nba_game_id.is_not(None))).scalars()
    }
    abbreviations = {team_id: abbr for team_id, abbr in session.execute(select(Team.id, Team.abbreviation)).all()}
    for label, games, logs, date_from, date_to in fetched:
        season_id = season_service.resolve_season_id(_aware_utc(games[0].commence_time))
        stats = ingest_player_game_logs(session, logs.rows, season_id)
        summary.logs_inserted += stats.logs_inserted
        summary.rows_skipped += stats.rows_skipped

        matched = match_results(games, load_results(session, date_from, date_to), taken)
        for game in games:
            result = matched.get(game.id)
            if result is None:
                summary.unmatched.append(_describe(game, abbreviations))
                continue
            game.nba_game_id = result.nba_game_id
            game.home_score = result.points[game.home_team_id]
            game.away_score = result.points[game.away_team_id]
            game.status = "final"
            session.add(game)
            taken.add(result.nba_game_id)
            summary.games_finalized += 1
    session.commit()
