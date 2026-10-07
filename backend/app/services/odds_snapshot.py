"""
Opening / closing odds snapshots within The Odds API free tier (500 credits per month).

Cost model (one region-equivalent per call, <= 10 bookmakers via `bookmakers=`)
- /events is free and its response headers reveal the remaining quota.
- /odds game lines: 3 markets (h2h, spreads, totals) x 1 = 3 credits for the whole slate.
- /events/{id}/odds props: 1 credit per market per event.

Monthly budget (schedule = `--phase opening` once a day, `--phase closing` every 30 minutes),
assuming ~3 tip-off clusters per game day and ~28 game days per month:
    opening  1/day x 3                              =  3
    closing  3 clusters x 3 (game lines)            =  9
    props    3 clusters x 1 event x 1 market        =  3   (--props-events 1 per closing run)
    --------------------------------------------------------
    ~15 credits/day x 28 game days                  ~ 420  (< 500, ~80 credits of margin)
Fetching props for 3 events in EVERY closing run (the CLI default) costs 3 + 3 x (3 + 3) = 21/day
(~590/month) and would exhaust the quota, so scheduled closing runs should pass `--props-events 1`
(the scheduled-task registration script does) or the guard will stop captures late in the month.
The number of clusters is set by how often `--phase closing` is scheduled and by --window-minutes:
a run only spends credits when an event tips off inside the window and has no snapshot captured
within that window yet, so extra scheduled runs are free. `--min-remaining` is a hard stop.
"""
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Sequence, Set, Tuple

from sqlmodel import Session, select

from app.models import Game, OddsHistory
from app.services.odds_api_service import (
    DEFAULT_BOOKMAKERS,
    GAME_LINE_MARKETS,
    MARKET_TO_STAT,
    OddsApiService,
)
from app.services.odds_ingestion import IngestResult, OddsIngestionService, parse_api_datetime

logger = logging.getLogger(__name__)

PHASES = ("opening", "closing")
DEFAULT_PROPS_EVENTS = {"opening": 0, "closing": 3}
DEFAULT_PROPS_MARKETS = ("player_points",)
DEFAULT_MIN_REMAINING = 25
DEFAULT_WINDOW_MINUTES = 45
GAME_LINES_CREDITS = len(GAME_LINE_MARKETS)


@dataclass(frozen=True)
class PlanStep:
    label: str
    credits: int


@dataclass(frozen=True)
class SnapshotPlan:
    phase: str
    steps: Tuple[PlanStep, ...]

    @property
    def total_credits(self) -> int:
        return sum(step.credits for step in self.steps)


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
    scope = "whole slate" if phase == "opening" else f"events tipping off within {window_minutes} min"
    steps.append(
        PlanStep(
            f"GET /odds markets={','.join(GAME_LINE_MARKETS)} bookmakers={','.join(bookmakers)} ({scope})",
            GAME_LINES_CREDITS,
        )
    )
    for index in range(1, props_events + 1):
        steps.append(
            PlanStep(
                f"GET /events/<event {index}>/odds markets={','.join(props_markets)}",
                len(props_markets),
            )
        )
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
    Events tipping off within the next `window_minutes` (not yet started) that have no closing
    snapshot yet, earliest tip-off first. Pure function: callers supply the captured ids.
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


def events_with_closing_snapshot(
    session: Session, events: Sequence[Dict], window_minutes: int
) -> Set[str]:
    """Event ids that already have an odds_history row captured within `window_minutes` before tip-off."""
    captured: Set[str] = set()
    for event in events:
        event_id = event.get("id")
        tip_off = _commence(event)
        if not event_id or tip_off is None:
            continue
        game = session.exec(select(Game).where(Game.provider_event_id == event_id)).first()
        if game is None:
            continue
        hit = session.exec(
            select(OddsHistory.id)
            .where(OddsHistory.game_id == game.id)
            .where(OddsHistory.captured_at >= tip_off - timedelta(minutes=window_minutes))
            .where(OddsHistory.captured_at <= tip_off)
            .limit(1)
        ).first()
        if hit is not None:
            captured.add(event_id)
    return captured


@dataclass
class SnapshotSummary:
    phase: str
    status: str  # captured | no_events | nothing_due | aborted_low_credits
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
    """Captures one snapshot. Spends credits only when there is something to record."""
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
        captured = events_with_closing_snapshot(session, events, window_minutes)
        targets = select_closing_events(events, now, window_minutes, captured)
        if not targets:
            summary.status = "nothing_due"
            summary.message = (
                f"No event tips off within {window_minutes} min without a closing snapshot "
                "(no credits spent)."
            )
            return summary
    else:
        targets = sorted(events, key=lambda e: (_commence(e) or now, e["id"]))
    summary.events_targeted = len(targets)

    allowed, reason = credit_guard(service.requests_remaining, GAME_LINES_CREDITS, min_remaining)
    if not allowed:
        summary.status = "aborted_low_credits"
        summary.message = f"Aborted before spending: {reason}."
        return summary

    ingestion = OddsIngestionService(session)
    for event in targets:
        tip_off = _commence(event)
        if tip_off and event.get("home_team") and event.get("away_team"):
            ingestion.upsert_game(event["id"], tip_off, event["home_team"], event["away_team"])

    target_ids = {e["id"] for e in targets}
    lines = [q for q in service.fetch_game_lines(bookmakers) if q.event_id in target_ids]
    summary.credits_planned += GAME_LINES_CREDITS
    summary.game_line_quotes = len(lines)
    summary.game_lines = ingestion.ingest_game_quotes(lines, now)

    for event in targets[:props_events]:
        allowed, reason = credit_guard(service.requests_remaining, len(props_markets), min_remaining)
        if not allowed:
            summary.message = f"Props stopped early: {reason}."
            break
        quotes = service.fetch_event_prop_quotes(event["id"], markets=list(props_markets))
        summary.credits_planned += len(props_markets)
        summary.prop_calls += 1
        summary.prop_quotes += len(quotes)
        summary.props = summary.props.merge(ingestion.ingest_prop_quotes(event["id"], quotes, now))

    session.commit()  # persists games created for targets even if no quote rows were inserted
    summary.remaining_after = service.requests_remaining
    return summary


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
    return "\n".join(lines)


def valid_prop_markets(markets: Sequence[str]) -> List[str]:
    unknown = [m for m in markets if m not in MARKET_TO_STAT]
    if unknown:
        raise ValueError(f"unsupported prop market(s): {', '.join(unknown)} (choose from {', '.join(MARKET_TO_STAT)})")
    return list(markets)
