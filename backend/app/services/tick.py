"""
One stateless "tick": odds capture, results and settlement, prediction recording, meant to run every 15 minutes.

The PC is switched on at variable hours, so fixed-time tasks miss captures. A single Windows task starts at
log on and repeats every 15 minutes while the user is logged on (``scripts/register_tick_task.ps1``); every
run decides what to do from DB markers alone, so a missed tick costs nothing and a repeated tick spends nothing.

Steps run in order, each isolated (one failing step never prevents the others):
1. ``opening``  once per machine-local calendar day: the whole-slate game-lines call (3 credits), skipped when
                an ``opening`` marker already exists for the day or no event is upcoming (the /events call is free).
2. ``closing``  the existing closing logic with a window of ``window_minutes`` (30 = twice the tick interval, so
                a tip-off cannot slip between two ticks) and ``props_events`` player-prop events.
3. ``results``  final scores from nba_api for games that tipped off more than 3 h ago (network only when such a
                game exists), the incremental Elo update, settlement of the paper bets of final games and the
                closing-line value of the bets whose game has tipped off. Its three stages are isolated from each
                other: a nba_api outage does not stop settlement of games that are already final.
4. ``learn``    the model learning loop (``app.services.model_promotion``): evaluates every challenger against the
                champion when new final games arrived (promoting, retiring or rolling back under the evidence
                gates) and, at most every ``LEARNING_PROPOSAL_DAYS`` days, runs the historical candidate lab and
                registers gate-passing challengers. DB only, a 4 minute budget (the lab gets a deadline and
                returns a partial result) and isolated like every other step. It sits before ``record`` so a
                promotion takes effect for that tick's predictions. ``LEARNING_AUTOPROMOTE`` off = it only
                records what it would do.
5. ``record``   ``PredictionRecorder``: DB only, so it also runs when the capture or results steps failed or were
                skipped. It comes after ``learn`` so predictions use the current champion and ratings that include
                the latest games.
Steps live in an ordered registry of ``(name, callable)`` pairs, so a new step is added by appending to
``DEFAULT_STEPS`` without touching the runner.

Safety
- ``logs/tick.lock`` (pid + start time) stops overlapping ticks; a lock older than 20 minutes is stale and is
  replaced (the task itself is limited to 10 minutes); the lock is always released in ``finally``.
- The Odds API credit guard (``min_remaining``) applies to both capture steps.
- ``missed_closing`` counts games that tipped off in the last 12 hours without a ``closing`` marker, i.e. the
  closing lines lost while the PC was off (final games included: a game that already finished still lost its
  line). Those lines cannot be backfilled on a free plan.

Exit code: 0 when no step failed, 1 otherwise. A step that is deliberately held back (credit guard, nothing to
do, already captured today) is ``skipped``, not an error; a raised exception or a failed paid API call is an error.
"""
import logging
import os
import time
from dataclasses import dataclass, field, replace
from datetime import date, datetime, time as dtime, timedelta, timezone, tzinfo
from pathlib import Path
from typing import Callable, List, Optional, Sequence, Tuple

from sqlalchemy import exists
from sqlmodel import Session, select

from app.config import settings
from app.models import CAPTURE_CLOSING, CAPTURE_OPENING, Game, OddsSnapshotCapture
from app.services import model_evaluation, model_promotion
from app.services.model_lab import LabError
from app.services.odds_snapshot import (
    DEFAULT_MIN_REMAINING,
    DEFAULT_PROPS_MARKETS,
    SnapshotSummary,
    format_plan,
    format_summary,
    plan_snapshot,
    run_snapshot,
)
from app.services.prediction_recorder import PredictionRecorder
from app.services.results_sync import NbaApiResultsProvider, sync_results
from app.services.settlement import fill_clv, settle_bets

logger = logging.getLogger(__name__)

TICK_INTERVAL_MINUTES = 15
DEFAULT_TICK_WINDOW_MINUTES = 30
DEFAULT_TICK_PROPS_EVENTS = 1
MISSED_CLOSING_LOOKBACK_HOURS = 12
LOCK_MAX_AGE = timedelta(minutes=20)
DEFAULT_LOCK_PATH = Path(__file__).resolve().parents[3] / "logs" / "tick.lock"  # <repo>/logs/tick.lock

LEARN_BUDGET_SECONDS = 240.0  # the learn step never holds the tick (and its lock) longer than this
LEARN_PROPOSAL_RESERVE_SECONDS = 45.0  # kept out of the lab deadline for registering (and backfilling) a challenger
LEARN_MIN_PROPOSAL_SECONDS = 60.0  # a proposal is postponed to the next tick when less than this is left

STEP_OK = "ok"
STEP_SKIPPED = "skipped"
STEP_ERROR = "error"


# ---------------------------------------------------------------------------------------------- results

@dataclass
class StepResult:
    name: str
    status: str  # ok | skipped | error
    message: str = ""
    detail: str = ""  # multi-line text shown under the step
    credits: Optional[int] = None  # dry run: worst-case estimate; real run: credits actually spent


@dataclass
class TickSummary:
    now: datetime
    dry_run: bool = False
    status: str = "completed"  # completed | locked
    message: str = ""
    steps: List[StepResult] = field(default_factory=list)
    missed_closing: Optional[int] = None  # None: not computed (locked or the query failed)

    @property
    def exit_code(self) -> int:
        return 1 if any(step.status == STEP_ERROR for step in self.steps) else 0

    def __str__(self) -> str:
        return format_tick_summary(self)


def format_tick_summary(summary: TickSummary) -> str:
    mode = " (dry run: no network, no DB writes)" if summary.dry_run else ""
    lines = [f"Tick {summary.now.isoformat()}{mode}: {summary.status}"]
    if summary.message:
        lines.append(f"  {summary.message}")
    for step in summary.steps:
        lines.append(f"  [{step.status}] {step.name}: {step.message}")
        for extra in step.detail.splitlines():
            lines.append(f"      {extra}")
    credits = [step.credits for step in summary.steps if step.credits is not None]
    if credits:
        label = "worst-case credits" if summary.dry_run else "credits spent"
        lines.append(f"  {label}: {sum(credits)}")
    if summary.missed_closing is not None:
        lines.append(
            f"  missed closing lines (last {MISSED_CLOSING_LOOKBACK_HOURS} h, PC off or tick missed): "
            f"{summary.missed_closing}"
        )
    if summary.status != "locked":
        lines.append(f"  exit code: {summary.exit_code}")
    return "\n".join(lines)


# ------------------------------------------------------------------------------------------------- lock

class TickLock:
    """
    Advisory lock file holding the owner's pid and start time. ``acquire`` is atomic (O_EXCL); an existing
    lock younger than ``max_age`` means another tick is running. The age is the file's mtime, so a corrupt
    or empty lock still expires. Replacing a stale lock is not atomic against a second process doing the
    same, which is acceptable here because the scheduled task already refuses to start a second instance.
    """

    def __init__(self, path: Path, max_age: timedelta = LOCK_MAX_AGE):
        self.path = Path(path)
        self.max_age = max_age
        self._token = f"pid={os.getpid()} started={datetime.now(timezone.utc).isoformat()}\n"
        self._held = False

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(2):
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                age = self._age_seconds()
                if age is not None:
                    if age < self.max_age.total_seconds():
                        return False
                    logger.warning(f"tick: replacing a stale lock ({age / 60:.0f} min old): {self.path}")
                try:
                    self.path.unlink()
                except FileNotFoundError:
                    pass
                except OSError:  # still open by its owner (Windows)
                    return False
                continue
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(self._token)
            self._held = True
            return True
        return False

    def release(self) -> None:
        if not self._held:
            return
        self._held = False
        try:
            if self.path.read_text(encoding="utf-8") == self._token:  # never delete a lock someone else took over
                self.path.unlink()
        except OSError:
            pass

    def _age_seconds(self) -> Optional[float]:
        try:
            return max(0.0, time.time() - os.path.getmtime(self.path))
        except OSError:
            return None


# ----------------------------------------------------------------------------------------------- helpers

def _aware_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def local_day_bounds_utc(now: datetime, local_tz: Optional[tzinfo] = None) -> Tuple[date, datetime, datetime]:
    """(local date, start, end) of the calendar day containing ``now``; ``local_tz`` None = the system zone."""
    day = now.astimezone(local_tz).date()

    def midnight_utc(d: date) -> datetime:
        naive = datetime.combine(d, dtime.min)
        local = naive.replace(tzinfo=local_tz) if local_tz is not None else naive.astimezone()
        return local.astimezone(timezone.utc)

    return day, midnight_utc(day), midnight_utc(day + timedelta(days=1))


def opening_captured_today(session: Session, now: datetime, local_tz: Optional[tzinfo] = None) -> bool:
    """True when an ``opening`` marker was written during the machine-local calendar day of ``now``."""
    _, start, end = local_day_bounds_utc(_aware_utc(now), local_tz)
    row = session.exec(
        select(OddsSnapshotCapture.id)
        .where(OddsSnapshotCapture.kind == CAPTURE_OPENING)
        .where(OddsSnapshotCapture.captured_at >= start)
        .where(OddsSnapshotCapture.captured_at < end)
        .limit(1)
    ).first()
    return row is not None


def count_missed_closing(
    session: Session, now: datetime, lookback_hours: float = MISSED_CLOSING_LOOKBACK_HOURS
) -> int:
    """Games that tipped off in the last ``lookback_hours`` hours and have no closing marker (postponed excluded)."""
    now = _aware_utc(now)
    start = now - timedelta(hours=lookback_hours)
    has_closing = exists().where(
        OddsSnapshotCapture.game_id == Game.id, OddsSnapshotCapture.kind == CAPTURE_CLOSING
    )
    rows = session.exec(
        select(Game.commence_time)
        .where(Game.commence_time >= start, Game.commence_time < now)
        .where(Game.status != "postponed")  # a postponed game never tipped off: no line was lost
        .where(~has_closing)
    ).all()
    # SQLite returns naive datetimes: re-check in Python so the window never depends on the driver.
    return sum(1 for commence in rows if start <= _aware_utc(commence) < now)


# ----------------------------------------------------------------------------------------------- steps

@dataclass(frozen=True)
class TickContext:
    session: Session
    service: object  # OddsApiService (or a fake); never touched on a dry run
    now: datetime
    dry_run: bool
    window_minutes: int
    props_events: int
    min_remaining: int
    local_tz: Optional[tzinfo]
    results_provider: Optional[object] = None  # GameResultsProvider; None builds the nba_api one when it is needed
    clock: Callable[[], float] = time.monotonic  # injectable so the learn budget can be tested
    learn_budget_seconds: float = LEARN_BUDGET_SECONDS


Step = Callable[[TickContext], StepResult]


def _service_ready(ctx: TickContext) -> Optional[StepResult]:
    if not getattr(ctx.service, "is_configured", True):
        return StepResult("", STEP_ERROR, "THE_ODDS_API_KEY is not configured (backend/.env); no capture possible.")
    return None


def _snapshot_result(summary: SnapshotSummary) -> StepResult:
    detail = format_summary(summary)
    message = summary.message or summary.status
    if summary.status == "captured":
        return StepResult("", STEP_OK, f"captured, {summary.markers_written} marker(s) written", detail, summary.credits_spent)
    if summary.status == "call_failed":
        return StepResult("", STEP_ERROR, message, detail, summary.credits_spent)
    return StepResult("", STEP_SKIPPED, f"{summary.status}: {message}", detail, summary.credits_spent)  # no_events | nothing_due | aborted_low_credits


def opening_step(ctx: TickContext) -> StepResult:
    day, _, _ = local_day_bounds_utc(ctx.now, ctx.local_tz)
    if opening_captured_today(ctx.session, ctx.now, ctx.local_tz):
        return StepResult("", STEP_SKIPPED, f"opening already captured for {day.isoformat()}")
    if ctx.dry_run:
        plan = plan_snapshot("opening", 0, DEFAULT_PROPS_MARKETS)
        return StepResult(
            "", STEP_OK, f"would capture the opening slate for {day.isoformat()} if events are upcoming",
            format_plan(plan, ctx.min_remaining), plan.total_credits,
        )
    not_ready = _service_ready(ctx)
    if not_ready is not None:
        return not_ready
    summary = run_snapshot(
        ctx.session, ctx.service, "opening", props_events=0, min_remaining=ctx.min_remaining, now=ctx.now
    )
    result = _snapshot_result(summary)
    if summary.status == "captured" and summary.markers_written == 0:
        # A paid call that left no marker would be repeated by the next tick: make it loud.
        return replace(result, status=STEP_ERROR, message="paid opening call wrote no marker (no game resolved); it will retry")
    return result


def closing_step(ctx: TickContext) -> StepResult:
    if ctx.dry_run:
        plan = plan_snapshot("closing", ctx.props_events, DEFAULT_PROPS_MARKETS, window_minutes=ctx.window_minutes)
        return StepResult(
            "", STEP_OK, f"would capture closing lines for events tipping off within {ctx.window_minutes} min",
            format_plan(plan, ctx.min_remaining), plan.total_credits,
        )
    not_ready = _service_ready(ctx)
    if not_ready is not None:
        return not_ready
    summary = run_snapshot(
        ctx.session,
        ctx.service,
        "closing",
        props_events=ctx.props_events,
        min_remaining=ctx.min_remaining,
        window_minutes=ctx.window_minutes,
        now=ctx.now,
    )
    return _snapshot_result(summary)


def _guarded(ctx: TickContext, label: str, errors: List[str], action):
    """Runs one stage of a multi-stage step; a failure is recorded and leaves a usable session for the next stage."""
    try:
        return action()
    except Exception as exc:
        logger.exception(f"tick: stage {label} failed")
        try:
            ctx.session.rollback()
        except Exception:
            logger.exception("tick: rollback after a failed results stage also failed")
        errors.append(f"{label}: {type(exc).__name__}: {exc}")
        return None


def results_step(ctx: TickContext) -> StepResult:
    nothing = "nothing to do: no unresolved game, unsettled bet or missing CLV"
    if ctx.dry_run:
        pending = sync_results(ctx.session, None, ctx.now, dry_run=True)
        settle = settle_bets(ctx.session, ctx.now, dry_run=True)
        clv = fill_clv(ctx.session, ctx.now, dry_run=True)
        clv_bets = clv.filled + clv.line_moved
        if not (pending.games_pending or pending.elo_catch_up_games or settle.total_settled or clv_bets):
            return StepResult("", STEP_SKIPPED, nothing)
        lookup = f"would look up results of {pending.games_pending} game(s)" + (
            " (1 nba_api call)" if pending.games_pending else ""
        )
        message = (
            f"{lookup}, rate {pending.elo_catch_up_games} final game(s) waiting for Elo, "
            f"settle {settle.total_settled} bet(s), fill CLV for {clv_bets} bet(s)"
        )
        return StepResult("", STEP_OK, message)

    errors: List[str] = []
    provider = ctx.results_provider if ctx.results_provider is not None else NbaApiResultsProvider()
    sync = _guarded(ctx, "sync", errors, lambda: sync_results(ctx.session, provider, ctx.now))
    settled = _guarded(ctx, "settle", errors, lambda: settle_bets(ctx.session, ctx.now))
    clv = _guarded(ctx, "clv", errors, lambda: fill_clv(ctx.session, ctx.now))

    finalized = sync.games_finalized if sync else 0
    n_settled = settled.total_settled if settled else 0
    n_clv = clv.filled if clv else 0
    detail: List[str] = []
    if sync is not None:
        elo_note = " (full rebuild)" if sync.elo_rebuilt else ""
        detail.append(
            f"nba_api calls: {sync.api_calls}, player logs added: {sync.logs_inserted}, "
            f"Elo rating rows added: {sync.rating_rows_added}{elo_note}"
        )
        if sync.unmatched:
            detail.append(f"no result yet for {len(sync.unmatched)} game(s): " + "; ".join(sync.unmatched))
        if sync.games_stale:
            detail.append(f"{sync.games_stale} older unresolved game(s) are no longer chased")
    if settled is not None and settled.total_settled:
        counts = ", ".join(f"{name}={count}" for name, count in sorted(settled.settled.items()))
        detail.append(f"settled: {counts}, P/L {settled.profit_units:+} u")
    if clv is not None and (clv.line_moved or clv.no_closing_marker):
        detail.append(
            f"CLV: {clv.line_moved} bet(s) closed at another line, {clv.no_closing_marker} without a closing capture"
        )
    for error in errors:
        detail.append(f"ERROR {error}")
    detail_text = "\n".join(detail)

    message = f"{finalized} game(s) finalized, {n_settled} bet(s) settled, CLV filled for {n_clv} bet(s)"
    if errors:
        return StepResult("", STEP_ERROR, f"{message}; {len(errors)} stage(s) failed", detail_text)
    did_work = finalized or n_settled or n_clv or (sync is not None and (sync.did_work or sync.api_calls))
    if not did_work:
        return StepResult("", STEP_SKIPPED, nothing, detail_text)
    return StepResult("", STEP_OK, message, detail_text)


def _days(delta: timedelta) -> str:
    return f"{delta.total_seconds() / 86400.0:.1f} day(s)"


def learn_step(ctx: TickContext) -> StepResult:
    """
    Evaluate the challengers (DB only) and, when the weekly cadence says so, propose new ones. The two stages are
    isolated from each other. A dry run reads the database and reports what it would do: it writes nothing and does
    not run the lab. The whole step stays inside ``ctx.learn_budget_seconds``: the lab gets a deadline that leaves a
    reserve for registering a challenger, and a proposal is postponed (no marker is written, so the next tick
    retries it) when too little of the budget is left.
    """
    deadline = ctx.clock() + ctx.learn_budget_seconds
    autopromote = bool(settings.LEARNING_AUTOPROMOTE)
    messages: List[str] = []
    detail: List[str] = []
    errors: List[str] = []

    outcome = _guarded(
        ctx, "evaluate", errors,
        lambda: model_promotion.run_evaluation_pass(
            ctx.session, ctx.now, apply=not ctx.dry_run, autopromote=autopromote,
            config=model_evaluation.EvaluationConfig.from_settings(settings), local_tz=ctx.local_tz,
        ),
    )
    did_work = False
    if outcome is not None:
        did_work = _describe_pass(ctx, outcome, messages, detail)
    did_work = _learn_proposal(ctx, deadline, autopromote, messages, detail, errors) or did_work

    message = "; ".join(messages) or "nothing to do"
    for error in errors:
        detail.append(f"ERROR {error}")
    detail_text = "\n".join(detail)
    if errors:
        return StepResult("", STEP_ERROR, f"{message}; {len(errors)} stage(s) failed", detail_text)
    return StepResult("", STEP_OK if did_work else STEP_SKIPPED, message, detail_text)


def _describe_pass(ctx: TickContext, outcome, messages: List[str], detail: List[str]) -> bool:
    """Adds the evaluation pass to the step text; True when it did (or, on a dry run, would do) something."""
    if outcome.message:
        messages.append(outcome.message)
        return False
    if not outcome.entries:
        messages.append("no active challengers")
        return False
    detail.append(model_promotion.format_pass(outcome))
    ready = [entry for entry in outcome.entries if entry.due]
    if ctx.dry_run:
        messages.append(f"would evaluate {len(outcome.entries)} challenger(s), {len(ready)} with new paired games")
        return bool(ready)
    changes = [
        f"{entry.model} {entry.action}"
        for entry in outcome.entries
        if entry.action in (model_promotion.ACTION_PROMOTED, model_promotion.ACTION_ROLLED_BACK, model_promotion.ACTION_RETIRED)
    ]
    messages.append(
        f"evaluated {len(ready)} of {len(outcome.entries)} challenger(s), {outcome.rows_written} audit row(s)"
        + (": " + ", ".join(changes) if changes else "")
    )
    return bool(outcome.rows_written)


def _learn_proposal(
    ctx: TickContext, deadline: float, autopromote: bool, messages: List[str], detail: List[str], errors: List[str]
) -> bool:
    """The weekly candidate proposal; True when it ran (or, on a dry run, would run)."""
    try:
        last = model_promotion.last_proposal(ctx.session)
    except Exception as exc:
        logger.exception("tick: learn could not read the proposal marker")
        ctx.session.rollback()
        errors.append(f"proposal marker: {type(exc).__name__}: {exc}")
        return False
    age = None if last is None or last.evaluated_at is None else ctx.now - _aware_utc(last.evaluated_at)
    if age is not None and age < timedelta(days=settings.LEARNING_PROPOSAL_DAYS):
        messages.append(f"proposal not due (last one {_days(age)} ago)")
        return False
    since = "" if age is None else f" (last proposal {_days(age)} ago)"
    if ctx.dry_run:
        messages.append("would run the candidate lab" + since)
        return True
    remaining = deadline - ctx.clock()
    if remaining < LEARN_MIN_PROPOSAL_SECONDS:
        messages.append(f"proposal postponed: {max(0.0, remaining):.0f}s of the learn budget left")
        return False

    url = ctx.session.get_bind().url
    try:
        proposal = model_promotion.run_proposal(
            ctx.session,
            ctx.now,
            register=autopromote,
            seed=int(ctx.now.strftime("%G%V")),  # a new Elo search every ISO week, reproducible from the audit row
            deadline=deadline - LEARN_PROPOSAL_RESERVE_SECONDS,
            clock=ctx.clock,
            # The scheduled tick is the deliberate act that the lab's registration guard asks a human for.
            confirm_database=None if url.get_backend_name() == "sqlite" else url.database,
            max_challengers=settings.LEARNING_MAX_CHALLENGERS,
        )
    except LabError as exc:  # too little history, no Elo model: a note, retried on the next tick
        ctx.session.rollback()
        messages.append(f"the candidate lab cannot run yet: {exc}")
        return False
    except Exception as exc:
        logger.exception("tick: learn proposal failed")
        try:
            ctx.session.rollback()
        except Exception:
            logger.exception("tick: rollback after a failed learn proposal also failed")
        errors.append(f"proposal: {type(exc).__name__}: {exc}")
        return False
    messages.append("proposal: " + proposal.summary)
    for candidate in proposal.report.candidates:
        verdict = "passes the historical gate" if candidate.gate.passed else "; ".join(candidate.gate.reasons)
        detail.append(f"candidate {candidate.label}: hold-out gain {candidate.gate.gain:+.4f}, {verdict}")
    if not autopromote:
        detail.append("autopromote is off: candidates are reported, not registered")
    return True


def record_step(ctx: TickContext) -> StepResult:
    summary = PredictionRecorder(ctx.session, now=ctx.now).run(dry_run=ctx.dry_run)
    verb = "would write" if ctx.dry_run else "wrote"
    bets = ", ".join(f"{name}={count}" for name, count in sorted(summary.bets_placed.items())) or "none"
    skipped = ", ".join(f"{reason}={count}" for reason, count in sorted(summary.skipped.items())) or "none"
    message = (
        f"{summary.games_considered} game(s) in horizon, {summary.games_processed} processed; "
        f"{verb} {summary.predictions_written} prediction(s) ({summary.predictions_existing} existing); bets: {bets}"
    )
    shadows = [m for m in summary.models.values() if m.role != "champion"]
    if shadows:
        message += "; shadow: " + ", ".join(f"{m.name} {m.version}={m.predictions_written}" for m in shadows)
    return StepResult("", STEP_OK, message, f"skipped: {skipped}")


# Ordered registry: append a (name, callable) pair to add a step.
DEFAULT_STEPS: List[Tuple[str, Step]] = [
    ("opening", opening_step),
    ("closing", closing_step),
    ("results", results_step),
    ("learn", learn_step),
    ("record", record_step),
]


def default_steps(skip: Sequence[str] = ()) -> List[Tuple[str, Step]]:
    unknown = set(skip) - {name for name, _ in DEFAULT_STEPS}
    if unknown:
        raise ValueError(f"unknown step(s) to skip: {', '.join(sorted(unknown))}")
    return [(name, fn) for name, fn in DEFAULT_STEPS if name not in set(skip)]


def _run_step(name: str, step: Step, ctx: TickContext) -> StepResult:
    try:
        return replace(step(ctx), name=name)
    except Exception as exc:  # isolation: a failing step never stops the next ones
        logger.exception(f"tick: step {name} failed")
        try:
            ctx.session.rollback()  # leave a usable session for the next step
        except Exception:
            logger.exception("tick: rollback after a failed step also failed")
        return StepResult(name, STEP_ERROR, f"{type(exc).__name__}: {exc}")


# ----------------------------------------------------------------------------------------------- runner

def run_tick(
    session: Session,
    odds_service,
    now: datetime,
    *,
    dry_run: bool = False,
    window_minutes: int = DEFAULT_TICK_WINDOW_MINUTES,
    props_events: int = DEFAULT_TICK_PROPS_EVENTS,
    steps: Optional[Sequence[Tuple[str, Step]]] = None,
    min_remaining: int = DEFAULT_MIN_REMAINING,
    local_tz: Optional[tzinfo] = None,
    lock_path: Optional[Path] = None,
    results_provider: Optional[object] = None,
) -> TickSummary:
    """
    Runs every step once and returns the summary. A dry run takes no lock, never touches ``odds_service`` or the
    results provider and issues no INSERT. ``local_tz`` (default: the system zone) decides what "today" means for
    the opening step. ``results_provider`` (default: nba_api) is only used when a game awaits its result.
    """
    now = _aware_utc(now)
    summary = TickSummary(now=now, dry_run=dry_run)

    lock: Optional[TickLock] = None
    if not dry_run:
        lock = TickLock(lock_path if lock_path is not None else DEFAULT_LOCK_PATH)
        if not lock.acquire():
            summary.status = "locked"
            summary.message = f"another tick holds {lock.path}; nothing done"
            logger.warning(f"tick: {summary.message}")
            return summary

    try:
        try:
            summary.missed_closing = count_missed_closing(session, now)
        except Exception:
            logger.exception("tick: could not count missed closing lines")
            session.rollback()
        if summary.missed_closing:
            logger.warning(
                f"tick: {summary.missed_closing} game(s) tipped off in the last {MISSED_CLOSING_LOOKBACK_HOURS} h "
                "without a closing capture (PC off or tick missed); those lines cannot be backfilled."
            )

        ctx = TickContext(
            session, odds_service, now, dry_run, window_minutes, props_events, min_remaining, local_tz, results_provider
        )
        for name, step in default_steps() if steps is None else steps:
            result = _run_step(name, step, ctx)
            logger.info(f"tick: step {result.name} -> {result.status}: {result.message}")
            summary.steps.append(result)
    finally:
        if lock is not None:
            lock.release()
    return summary
