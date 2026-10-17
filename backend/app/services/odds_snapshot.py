"""
Opening / closing odds snapshots within The Odds API free tier (500 credits per month).

Cost model (one region-equivalent per call, <= 10 bookmakers via `bookmakers=`)
- /events is free and its response headers reveal the remaining quota.
- /odds game lines: 3 markets (h2h, spreads, totals) x 1 = 3 credits for the whole slate.
- /events/{id}/odds props: 1 credit per market per event.

"Already captured" is tracked with explicit markers in `odds_snapshot_capture`, never inferred from
`odds_history` (a run where no book moved a price inserts 0 rows). A marker is written only after a
successful (HTTP 200) paid call:
- `closing`: the game-lines call covered this game (3 credits, recorded on the first marker of the call).
- `closing_props`: the props call for this game succeeded (len(markets) credits).
- `opening`: informational, repeatable, never affects closing selection (game lines only).
A closing run skips the /odds call when every due game already has a `closing` marker, and picks props
events independently (earliest tip-off first among games lacking a `closing_props` marker), so a
props-only run costs just the props credits.

Scheduling: the `NBA-Odds-Tick` task (scripts/register_tick_task.ps1) starts at user log on and runs
`scripts/run_tick.py` every 15 minutes; app/services/tick.py calls `run_snapshot` for `opening` once per
machine-local day and for `closing` with a 30 minute window and 1 props event per tick. The manual
`scripts/capture_odds_snapshot.py --phase ...` CLI (default window 45 min) stays available for one-off runs.

Monthly budget (opening once a day, closing on every tick), assuming ~3 tip-off clusters per game day
and ~28 game days per month:
    opening  1/day x 3                              =  3
    closing  3 clusters x 3 (game lines)            =  9
    props    3 clusters x 1-2 runs x 1 market       =  3-6  (1 props event per closing run; a game
                                                             can sit inside the 30 min window for two
                                                             15 min ticks, each picking one more event)
    --------------------------------------------------------
    ~15-18 credits/day x 28 game days               ~ 420-504 (quota is 500; `--min-remaining` is the
                                                             hard stop and protects the floor)
The closing default is 1 props event per run; raising it to 3 costs up to 3 + 3 x (3 + 3 x 2) per day
and would exhaust the quota before month end.
The number of clusters is set by how often closing runs (every tick) and by the window minutes:
a run only spends credits when an event tips off inside the window and still lacks its marker, so extra
scheduled runs are free.
"""
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Sequence, Set, Tuple

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.models import (
    CAPTURE_CLOSING,
    CAPTURE_CLOSING_PROPS,
    CAPTURE_KINDS,
    CAPTURE_OPENING,
    Game,
    OddsSnapshotCapture,
)
from app.services.odds_api_service import (
    DEFAULT_BOOKMAKERS,
    GAME_LINE_MARKETS,
    MARKET_TO_STAT,
    GameQuote,
    OddsApiService,
)
from app.services.odds_ingestion import IngestResult, OddsIngestionService, parse_api_datetime

logger = logging.getLogger(__name__)

PHASES = ("opening", "closing")
DEFAULT_PROPS_EVENTS = {"opening": 0, "closing": 1}
DEFAULT_PROPS_MARKETS = ("player_points",)
DEFAULT_MIN_REMAINING = 25
DEFAULT_WINDOW_MINUTES = 45
GAME_LINES_CREDITS = len(GAME_LINE_MARKETS)


@dataclass(frozen=True)
class PlanStep:
    label: str
    credits: int
    skippable: bool = False  # closing game-lines call: skipped when every due game is already marked


@dataclass(frozen=True)
class SnapshotPlan:
    phase: str
    steps: Tuple[PlanStep, ...]

    @property
    def total_credits(self) -> int:
        return sum(step.credits for step in self.steps)

    @property
    def props_only_credits(self) -> int:
        """Cost of a run whose game lines were already captured (the /odds call is skipped)."""
        return sum(step.credits for step in self.steps if not step.skippable)


def plan_snapshot(
    phase: str,
    props_events: int,
    props_markets: Sequence[str],
    bookmakers: Sequence[str] = DEFAULT_BOOKMAKERS,
    window_minutes: int = DEFAULT_WINDOW_MINUTES,
) -> SnapshotPlan:
    """The worst-case calls (and credits) a run can make; used by --dry-run, which touches no network."""
    if phase not in PHASES:
        raise ValueError(f"unknown phase: {phase}")
    steps = [PlanStep("GET /events (free; reveals remaining quota)", 0)]
    if phase == "opening":
        scope = "whole slate"
    else:
        scope = (
            f"events tipping off within {window_minutes} min; "
            "skipped when every due event already has a closing marker"
        )
    steps.append(
        PlanStep(
            f"GET /odds markets={','.join(GAME_LINE_MARKETS)} bookmakers={','.join(bookmakers)} ({scope})",
            GAME_LINES_CREDITS,
            skippable=phase == "closing",
        )
    )
    for index in range(1, props_events + 1):
        label = f"GET /events/<event {index}>/odds markets={','.join(props_markets)}"
        if phase == "closing":
            label += " (only events without a closing_props marker)"
        steps.append(PlanStep(label, len(props_markets)))
    return SnapshotPlan(phase=phase, steps=tuple(steps))


def credit_guard(remaining: Optional[int], cost: int, min_remaining: int) -> Tuple[bool, str]:
    """Allows a call only if the quota left AFTER paying `cost` stays at or above `min_remaining`."""
    if cost <= 0:
        return True, "free call"
    if remaining is None:
        return False, "remaining quota unknown; refusing to spend credits blind"
    if remaining - cost < min_remaining:
        return False, f"{remaining} credits remaining, call costs {cost}, floor is {min_remaining}"
    return True, f"{remaining} credits remaining, call costs {cost}"


def _commence(event: Dict) -> Optional[datetime]:
    return parse_api_datetime(event.get("commence_time"))


def select_closing_events(
    events: Sequence[Dict],
    now: datetime,
    window_minutes: int,
    already_captured: Set[str],
) -> List[Dict]:
    """
    Events tipping off within the next `window_minutes` (not yet started) whose id is not in
    `already_captured`, earliest tip-off first. Pure function: callers supply the marked ids
    (the `closing` marker set for game lines, the `closing_props` marker set for props).
    """
    horizon = now + timedelta(minutes=window_minutes)
    due: List[Tuple[datetime, Dict]] = []
    for event in events:
        event_id = event.get("id")
        tip_off = _commence(event)
        if not event_id or tip_off is None or event_id in already_captured:
            continue
        if now <= tip_off <= horizon:
            due.append((tip_off, event))
    return [event for _, event in sorted(due, key=lambda item: (item[0], item[1]["id"]))]


def events_with_marker(session: Session, events: Sequence[Dict], kind: str) -> Set[str]:
    """Event ids whose game already has a capture marker of `kind` (see odds_snapshot_capture)."""
    if kind not in CAPTURE_KINDS:
        raise ValueError(f"unknown capture kind: {kind}")
    event_ids = [e["id"] for e in events if e.get("id")]
    if not event_ids:
        return set()
    rows = session.exec(
        select(Game.provider_event_id)
        .join(OddsSnapshotCapture, OddsSnapshotCapture.game_id == Game.id)
        .where(Game.provider_event_id.in_(event_ids))
        .where(OddsSnapshotCapture.kind == kind)
    ).all()
    return set(rows)


def record_capture(
    session: Session,
    game_id: int,
    kind: str,
    captured_at: datetime,
    credits_spent: int = 0,
    quotes_seen: int = 0,
    quotes_inserted: int = 0,
) -> Optional[OddsSnapshotCapture]:
    """
    Writes a capture marker. `closing` / `closing_props` are unique per game: when one already
    exists (or another run wins the race on the unique index) nothing is written and None is
    returned, so a duplicate never crashes a run. `opening` markers may repeat.
    """
    if kind not in CAPTURE_KINDS:
        raise ValueError(f"unknown capture kind: {kind}")
    if kind != CAPTURE_OPENING:
        existing = session.exec(
            select(OddsSnapshotCapture.id)
            .where(OddsSnapshotCapture.game_id == game_id)
            .where(OddsSnapshotCapture.kind == kind)
        ).first()
        if existing is not None:
            return None
    marker = OddsSnapshotCapture(
        game_id=game_id,
        kind=kind,
        captured_at=captured_at,
        credits_spent=credits_spent,
        quotes_seen=quotes_seen,
        quotes_inserted=quotes_inserted,
    )
    try:
        with session.begin_nested():
            session.add(marker)
            session.flush()
    except IntegrityError:
        logger.warning(f"odds_snapshot: {kind} marker for game {game_id} already exists; keeping the first.")
        return None
    return marker


@dataclass
class SnapshotSummary:
    phase: str
    status: str  # captured | no_events | nothing_due | aborted_low_credits | call_failed
    message: str = ""
    events_considered: int = 0
    events_targeted: int = 0
    remaining_before: Optional[int] = None
    remaining_after: Optional[int] = None
    game_lines: IngestResult = field(default_factory=IngestResult)
    props: IngestResult = field(default_factory=IngestResult)
    game_line_quotes: int = 0
    prop_quotes: int = 0
    prop_calls: int = 0
    credits_planned: int = 0
    markers_written: int = 0

    @property
    def credits_spent(self) -> Optional[int]:
        if self.remaining_before is None or self.remaining_after is None:
            return None
        return self.remaining_before - self.remaining_after


def run_snapshot(
    session: Session,
    service: OddsApiService,
    phase: str,
    props_events: int,
    props_markets: Sequence[str] = DEFAULT_PROPS_MARKETS,
    min_remaining: int = DEFAULT_MIN_REMAINING,
    window_minutes: int = DEFAULT_WINDOW_MINUTES,
    bookmakers: Sequence[str] = DEFAULT_BOOKMAKERS,
    now: Optional[datetime] = None,
) -> SnapshotSummary:
    """
    Captures one snapshot. Spends credits only when there is something to record, and writes a
    capture marker only after a call returned HTTP 200 (a failed call writes none, so the next
    run retries it).
    """
    if phase not in PHASES:
        raise ValueError(f"unknown phase: {phase}")
    now = now or datetime.now(timezone.utc)
    summary = SnapshotSummary(phase=phase, status="captured")

    events = [e for e in service.fetch_upcoming_events() if e.get("id")]  # free call
    summary.events_considered = len(events)
    summary.remaining_before = service.requests_remaining
    if not events:
        summary.status = "no_events"
        summary.message = "No upcoming NBA events; nothing to capture (no credits spent)."
        return summary

    if phase == "closing":
        lines_targets = select_closing_events(
            events, now, window_minutes, events_with_marker(session, events, CAPTURE_CLOSING)
        )
        props_pool = (
            select_closing_events(
                events, now, window_minutes, events_with_marker(session, events, CAPTURE_CLOSING_PROPS)
            )
            if props_events > 0 and props_markets
            else []
        )
    else:
        lines_targets = sorted(events, key=lambda e: (_commence(e) or now, e["id"]))
        props_pool = lines_targets if props_events > 0 and props_markets else []

    # Games must exist before markers (FK) or quotes can be stored; unresolved teams/seasons are skipped.
    ingestion = OddsIngestionService(session)
    games: Dict[str, Game] = {}
    for event in {e["id"]: e for e in [*lines_targets, *props_pool]}.values():
        tip_off = _commence(event)
        if tip_off and event.get("home_team") and event.get("away_team"):
            game = ingestion.upsert_game(event["id"], tip_off, event["home_team"], event["away_team"])
            if game is not None:
                games[event["id"]] = game
    if phase == "closing":
        # A game we cannot store quotes or markers for would be re-fetched (and re-paid) every run.
        lines_targets = [e for e in lines_targets if e["id"] in games]
        props_pool = [e for e in props_pool if e["id"] in games]
    props_targets = props_pool[:props_events]

    summary.events_targeted = len({e["id"] for e in [*lines_targets, *props_targets]})
    if phase == "closing" and not lines_targets and not props_targets:
        summary.status = "nothing_due"
        summary.message = (
            f"No event tips off within {window_minutes} min without a pending closing capture "
            "(no credits spent)."
        )
        session.commit()
        return summary

    if lines_targets:
        allowed, reason = credit_guard(service.requests_remaining, GAME_LINES_CREDITS, min_remaining)
    else:  # every due game already has its closing marker: props-only run
        allowed, reason = credit_guard(service.requests_remaining, len(props_markets), min_remaining)
    if not allowed:
        summary.status = "aborted_low_credits"
        summary.message = f"Aborted before spending: {reason}."
        session.commit()
        return summary

    if lines_targets:
        quotes = service.fetch_game_lines(bookmakers)
        summary.credits_planned += GAME_LINES_CREDITS
        if not service.last_call_ok:
            summary.status = "call_failed"
            summary.message = "Game-lines call failed; no markers written, the next run will retry."
            session.commit()
            summary.remaining_after = service.requests_remaining
            return summary
        _store_game_lines(session, ingestion, summary, phase, lines_targets, games, quotes, now)
        session.commit()

    for event in props_targets:
        allowed, reason = credit_guard(service.requests_remaining, len(props_markets), min_remaining)
        if not allowed:
            summary.message = f"Props stopped early: {reason}."
            break
        prop_quotes = service.fetch_event_prop_quotes(event["id"], markets=list(props_markets))
        summary.credits_planned += len(props_markets)
        if not service.last_call_ok:
            summary.message = f"Props call failed for event {event['id']}; no marker written, will retry."
            continue
        summary.prop_calls += 1
        summary.prop_quotes += len(prop_quotes)
        result = ingestion.ingest_prop_quotes(event["id"], prop_quotes, now)
        summary.props = summary.props.merge(result)
        if phase == "closing" and record_capture(
            session,
            games[event["id"]].id,
            CAPTURE_CLOSING_PROPS,
            now,
            credits_spent=len(props_markets),
            quotes_seen=len(prop_quotes),
            quotes_inserted=result.inserted,
        ):
            summary.markers_written += 1
        session.commit()

    session.commit()  # persists games created for targets even if no quote rows were inserted
    summary.remaining_after = service.requests_remaining
    return summary


def _store_game_lines(
    session: Session,
    ingestion: OddsIngestionService,
    summary: SnapshotSummary,
    phase: str,
    targets: Sequence[Dict],
    games: Dict[str, Game],
    quotes: Sequence[GameQuote],
    now: datetime,
) -> None:
    """
    Ingests a successful game-lines response and marks every targeted game, even those with 0 new
    rows. The call's credits are recorded on the first marker (earliest tip-off); the others carry 0.
    """
    kind = CAPTURE_CLOSING if phase == "closing" else CAPTURE_OPENING
    by_event: Dict[str, List[GameQuote]] = {}
    for quote in quotes:
        by_event.setdefault(quote.event_id, []).append(quote)

    credits_left = GAME_LINES_CREDITS
    for event in targets:
        event_quotes = by_event.get(event["id"], [])
        result = ingestion.ingest_game_quotes(event_quotes, now) if event_quotes else IngestResult()
        summary.game_line_quotes += len(event_quotes)
        summary.game_lines = summary.game_lines.merge(result)
        game = games.get(event["id"])  # opening may target events whose teams/season did not resolve
        if game is not None and record_capture(
            session,
            game.id,
            kind,
            now,
            credits_spent=credits_left,
            quotes_seen=len(event_quotes),
            quotes_inserted=result.inserted,
        ):
            summary.markers_written += 1
            credits_left = 0


def format_summary(summary: SnapshotSummary) -> str:
    lines = [
        f"Snapshot {summary.phase}: {summary.status}",
        f"  events: {summary.events_considered} upcoming, {summary.events_targeted} targeted",
    ]
    if summary.message:
        lines.append(f"  {summary.message}")
    if summary.status == "captured":
        g, p = summary.game_lines, summary.props
        lines.append(
            f"  game lines: {summary.game_line_quotes} quotes -> inserted {g.inserted}, "
            f"duplicate {g.skipped_duplicate}, unmatched {g.skipped_unmatched}, invalid {g.skipped_invalid}"
        )
        lines.append(
            f"  props: {summary.prop_calls} calls, {summary.prop_quotes} quotes -> inserted {p.inserted}, "
            f"duplicate {p.skipped_duplicate}, unmatched {p.skipped_unmatched}, invalid {p.skipped_invalid}"
        )
        lines.append(f"  markers: {summary.markers_written} written")
        lines.append(f"  credits: ~{summary.credits_planned} estimated")
    spent = summary.credits_spent
    if spent is not None:
        lines.append(f"  quota: {summary.remaining_before} -> {summary.remaining_after} (spent {spent})")
    elif summary.remaining_before is not None:
        lines.append(f"  quota remaining: {summary.remaining_before}")
    return "\n".join(lines)


def format_plan(plan: SnapshotPlan, min_remaining: int) -> str:
    lines = [f"DRY RUN (no network, no DB): phase={plan.phase}"]
    for index, step in enumerate(plan.steps, start=1):
        lines.append(f"  {index}. {step.label} -> {step.credits} credit(s)")
    lines.append(f"  worst-case cost: {plan.total_credits} credits (guard floor: {min_remaining})")
    if plan.props_only_credits != plan.total_credits:
        lines.append(
            f"  props-only run (every due game already has a closing marker): {plan.props_only_credits} credits"
        )
    return "\n".join(lines)


def valid_prop_markets(markets: Sequence[str]) -> List[str]:
    unknown = [m for m in markets if m not in MARKET_TO_STAT]
    if unknown:
        raise ValueError(f"unsupported prop market(s): {', '.join(unknown)} (choose from {', '.join(MARKET_TO_STAT)})")
    return list(markets)
