"""
Promotion engine: turns evaluations into roles, and keeps an audit row for everything it does.

``run_evaluation_pass`` evaluates every active challenger against the champion (``model_evaluation``) and, when
asked to apply and ``LEARNING_AUTOPROMOTE`` is on, acts on the decisions:

* ``promote`` / ``rollback``: the challenger becomes the champion and the old champion becomes a challenger (it
  stays registered, which is what makes a rollback possible). The swap is ONE transaction that also holds the
  audit row: the old champion is demoted first (the single-champion unique index allows one champion only), then
  the new one is promoted (``promoted_at``, ``parent_id`` = the old champion, a ``notes`` entry). Any failure in
  between rolls everything back, leaving exactly the old champion, and a ``keep`` audit row says what happened.
  At most ONE promotion per pass: when several challengers qualify the one with the largest lower bound of the
  log-loss gain wins, the others are recorded as ``keep`` and are judged against the new champion later.
* ``retire``: role ``retired`` and ``retired_at``.

With autopromote off the decision is recorded as ``dry_run`` ("autopromote disabled (would promote)") and nothing
changes. With ``apply=False`` nothing is written at all.

A challenger gets an audit row only when it has paired games it had not been evaluated on (comparing with the last
row for the same champion) and none was written for it the same local day, so the table grows with evidence, not
with ticks. ``insufficient_data`` and ``keep`` rows are recorded too: they are the trail of "why not yet".

Manual overrides (``manual_promote`` / ``manual_retire``) bypass the statistical gate but never the invariants (one
champion at a time, atomic swap) and always write an audit row whose reason starts with ``manual:``.
"""
import json
import logging
import time
from dataclasses import asdict, dataclass, field, replace
from datetime import date, datetime, timezone, tzinfo
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy import func, select
from sqlmodel import Session

from app.models import (
    MODEL_ROLE_CHALLENGER,
    MODEL_ROLE_CHAMPION,
    MODEL_ROLE_RETIRED,
    BetSide,
    Game,
    MarketType,
    ModelEvaluation,
    ModelPrediction,
    ModelVersion,
)
from app.services import model_evaluation as ev
from app.services import model_lab, model_registry

logger = logging.getLogger(__name__)

MANUAL_PREFIX = "manual:"
DECISION_PROPOSAL = "proposal"
DECISION_DRY_RUN = "dry_run"

ACTION_SKIPPED = "skipped"  # nothing written
ACTION_RECORDED = "recorded"  # audit row only
ACTION_PROMOTED = "promoted"
ACTION_ROLLED_BACK = "rolled_back"
ACTION_RETIRED = "retired"
ACTION_FAILED = "failed"
ACTION_PREVIEW = "preview"  # apply=False: evaluated, nothing written


class ManualOverrideRefused(RuntimeError):
    """A manual promote/retire was refused (invariant, cooldown, unknown model)."""


def _aware_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _local_day(moment: datetime, local_tz: Optional[tzinfo] = None) -> date:
    return _aware_utc(moment).astimezone(local_tz).date()


def label(model: ModelVersion) -> str:
    return f"{model.name} {model.version}"


def autopromote_enabled() -> bool:
    from app.config import settings

    return bool(settings.LEARNING_AUTOPROMOTE)


# ------------------------------------------------------------------------------------------- audit rows

def last_evaluation(session: Session, challenger_id: int) -> Optional[ModelEvaluation]:
    """The newest automatic evaluation row of a challenger (proposal and manual rows are not evaluations)."""
    rows = session.execute(
        select(ModelEvaluation)
        .where(ModelEvaluation.challenger_id == challenger_id, ModelEvaluation.decision != DECISION_PROPOSAL)
        .order_by(ModelEvaluation.evaluated_at.desc(), ModelEvaluation.id.desc())
    ).scalars()
    for row in rows:
        if not (row.reason or "").startswith(MANUAL_PREFIX):
            return row
    return None


def _evaluation_row(
    result: ev.EvaluationResult, decision: str, reason: str, now: datetime, extra: Dict[str, Any]
) -> ModelEvaluation:
    return ModelEvaluation(
        evaluated_at=now,
        champion_id=result.champion_id,
        challenger_id=result.challenger_id,
        n_games=result.n_games,
        n_market_games=result.n_market_games,
        metrics={**result.to_metrics(), **extra},
        decision=decision,
        reason=reason,
    )


# ------------------------------------------------------------------------------------------ role changes

def _merged_notes(model: ModelVersion, key: str, entry: Dict[str, Any]) -> str:
    """``notes`` stays one JSON object: an existing JSON object is extended, any other text is kept under ``previous``."""
    existing: Dict[str, Any] = {}
    if model.notes:
        try:
            loaded = json.loads(model.notes)
            existing = loaded if isinstance(loaded, dict) else {"previous": model.notes}
        except ValueError:
            existing = {"previous": model.notes}
    existing[key] = entry
    return json.dumps(existing, sort_keys=True, default=str)


def _promote_row(new: ModelVersion, old: Optional[ModelVersion], now: datetime, note: Dict[str, Any]) -> None:
    new.role = MODEL_ROLE_CHAMPION
    new.promoted_at = now
    new.retired_at = None
    if old is not None:
        new.parent_id = old.id
    new.notes = _merged_notes(new, "promotion", note)


def swap_champion(
    session: Session, new: ModelVersion, old: Optional[ModelVersion], now: datetime, note: Dict[str, Any]
) -> None:
    """
    Demote ``old`` to a challenger, then promote ``new``, inside the caller's transaction (flushes, never commits).
    The order matters: the single-champion unique index admits one champion at a time.
    """
    if old is not None:
        old.role = MODEL_ROLE_CHALLENGER
        session.add(old)
        session.flush()
    _promote_row(new, old, now, note)
    session.add(new)
    session.flush()


def retire_model(session: Session, model: ModelVersion, now: datetime, note: Dict[str, Any]) -> None:
    """Retire a non-champion model inside the caller's transaction (flushes, never commits)."""
    if model.role == MODEL_ROLE_CHAMPION:
        raise ManualOverrideRefused(f"{label(model)} is the champion; promote another model before retiring it")
    model.role = MODEL_ROLE_RETIRED
    model.retired_at = now
    model.notes = _merged_notes(model, "retirement", note)
    session.add(model)
    session.flush()


# ------------------------------------------------------------------------------------------------ pass

@dataclass
class PassEntry:
    model_id: int
    model: str  # "name version"
    result: Optional[ev.EvaluationResult]
    due: bool  # had new paired games and no row yet today
    action: str
    decision: Optional[str] = None  # what the audit row says (None when no row was written)
    note: str = ""
    evaluation_id: Optional[int] = None


@dataclass
class EvaluationPass:
    now: datetime
    apply: bool
    autopromote: bool
    champion: Optional[str] = None
    champion_id: Optional[int] = None
    entries: List[PassEntry] = field(default_factory=list)
    message: str = ""

    @property
    def promoted(self) -> List[PassEntry]:
        return [e for e in self.entries if e.action in (ACTION_PROMOTED, ACTION_ROLLED_BACK)]

    @property
    def retired(self) -> List[PassEntry]:
        return [e for e in self.entries if e.action == ACTION_RETIRED]

    @property
    def rows_written(self) -> int:
        return sum(1 for e in self.entries if e.evaluation_id is not None)


def _skip_reason(
    last: Optional[ModelEvaluation], champion_id: int, n_games: int, today: date, local_tz: Optional[tzinfo]
) -> Optional[str]:
    seen = last.n_games if last is not None and last.champion_id == champion_id else 0
    if n_games <= seen:
        return f"no new paired games since the last evaluation ({n_games} games)"
    if last is not None and last.evaluated_at is not None and _local_day(last.evaluated_at, local_tz) == today:
        return "already evaluated today"
    return None


def run_evaluation_pass(
    session: Session,
    now: datetime,
    *,
    apply: bool = True,
    autopromote: Optional[bool] = None,
    config: Optional[ev.EvaluationConfig] = None,
    local_tz: Optional[tzinfo] = None,
) -> EvaluationPass:
    """Evaluate every active challenger and (when ``apply``) record and act on the decisions; see the module doc."""
    now = _aware_utc(now)
    autopromote = autopromote_enabled() if autopromote is None else bool(autopromote)
    outcome = EvaluationPass(now=now, apply=apply, autopromote=autopromote)
    champion = model_registry.get_champion(session)
    if champion is None:
        outcome.message = "no champion registered; nothing to evaluate"
        return outcome
    outcome.champion, outcome.champion_id = label(champion), champion.id

    challengers = [row for row in model_registry.list_active(session) if row.role == MODEL_ROLE_CHALLENGER and row.id != champion.id]
    config = config or ev.default_config()
    if config.n_challengers is None:
        config = replace(config, n_challengers=len(challengers))
    today = _local_day(now, local_tz)

    plans: List[PassEntry] = []
    for challenger in challengers:
        data = ev.collect_paired_games(session, champion.id, challenger.id)
        skip = _skip_reason(last_evaluation(session, challenger.id), champion.id, data.n, today, local_tz)
        if skip is not None and apply:
            outcome.entries.append(PassEntry(challenger.id, label(challenger), None, False, ACTION_SKIPPED, note=skip))
            continue
        result = ev.evaluate_challenger(session, challenger, champion, now, config, data=data)
        entry = PassEntry(challenger.id, label(challenger), result, skip is None, ACTION_PREVIEW if not apply else ACTION_RECORDED)
        if not apply:
            entry.note = f"would {result.decision}" + ("" if skip is None else f" (no row: {skip})")
        plans.append(entry)

    if not apply:
        outcome.entries.extend(plans)
        return outcome

    winner = None
    if autopromote:
        qualified = [p for p in plans if p.result.decision in (ev.DECISION_PROMOTE, ev.DECISION_ROLLBACK)]
        if qualified:
            winner = max(qualified, key=lambda p: (p.result.log_loss_gain.bound_low, -p.model_id))
    models = {row.id: row for row in challengers}

    for plan in plans:
        outcome.entries.append(plan)
        _apply_plan(session, plan, models[plan.model_id], champion, winner, autopromote, now)
    return outcome


def _apply_plan(
    session: Session,
    plan: PassEntry,
    model: ModelVersion,
    champion: ModelVersion,
    winner: Optional[PassEntry],
    autopromote: bool,
    now: datetime,
) -> None:
    result = plan.result
    extra = {"proposed_decision": result.decision, "evaluation_reason": result.reason, "autopromote": autopromote}
    actionable = result.decision in (ev.DECISION_PROMOTE, ev.DECISION_ROLLBACK, ev.DECISION_RETIRE)

    if actionable and not autopromote:
        row = _evaluation_row(result, DECISION_DRY_RUN, f"autopromote disabled (would {result.decision})", now, {**extra, "applied": False})
        _record_only(session, plan, row)
        return
    if result.decision in (ev.DECISION_PROMOTE, ev.DECISION_ROLLBACK) and plan is not winner:
        reason = f"another challenger ({winner.model}) was promoted in this pass; judged against the new champion next time"
        _record_only(session, plan, _evaluation_row(result, ev.DECISION_KEEP, reason, now, {**extra, "applied": False}))
        return
    if not actionable:
        _record_only(session, plan, _evaluation_row(result, result.decision, result.reason, now, {**extra, "applied": False}))
        return

    row = _evaluation_row(result, result.decision, result.reason, now, {**extra, "applied": True})
    note = {"at": now.isoformat(), "decision": result.decision, "reason": result.reason, "champion_id": champion.id}
    try:
        session.add(row)
        session.flush()
        note["evaluation_id"] = row.id
        if result.decision == ev.DECISION_RETIRE:
            retire_model(session, model, now, note)
        else:
            swap_champion(session, model, champion, now, note)
        session.commit()
    except Exception as exc:  # the audit row and the role change are one transaction: neither survives a failure
        session.rollback()
        logger.exception(f"learning: applying {result.decision} for {plan.model} failed and was rolled back")
        failed = _evaluation_row(
            result, ev.DECISION_KEEP, f"{result.decision} failed and was rolled back: {exc!r}", now, {**extra, "applied": False, "failed": True}
        )
        plan.action, plan.note = ACTION_FAILED, f"{result.decision} failed: {exc!r}"
        _record_only(session, plan, failed, action=ACTION_FAILED)
        return
    plan.decision = result.decision
    plan.evaluation_id = row.id
    plan.action = {
        ev.DECISION_RETIRE: ACTION_RETIRED,
        ev.DECISION_ROLLBACK: ACTION_ROLLED_BACK,
        ev.DECISION_PROMOTE: ACTION_PROMOTED,
    }[result.decision]
    plan.note = result.reason


def _record_only(session: Session, plan: PassEntry, row: ModelEvaluation, action: str = ACTION_RECORDED) -> None:
    session.add(row)
    session.commit()
    plan.action = action
    plan.decision = row.decision
    plan.evaluation_id = row.id
    plan.note = plan.note or (row.reason or "")


# ---------------------------------------------------------------------------------------- manual overrides

def _manual_row(
    session: Session, decision: str, reason: str, champion_id: int, challenger_id: int, now: datetime, metrics: Dict[str, Any]
) -> ModelEvaluation:
    paired = ev.collect_paired_games(session, champion_id, challenger_id) if champion_id != challenger_id else None
    row = ModelEvaluation(
        evaluated_at=now,
        champion_id=champion_id,
        challenger_id=challenger_id,
        n_games=0 if paired is None else paired.n,
        n_market_games=0 if paired is None else paired.n_market,
        metrics={"manual": True, **metrics},
        decision=decision,
        reason=f"{MANUAL_PREFIX} {reason}",
    )
    session.add(row)
    session.flush()
    return row


def manual_promote(
    session: Session, model_id: int, reason: str, now: datetime, *, force: bool = False,
    config: Optional[ev.EvaluationConfig] = None,
) -> ModelEvaluation:
    """
    Make ``model_id`` the champion regardless of the statistics. The previous champion is demoted to a challenger in
    the same transaction, so there is never a second champion. Without ``force`` the model must be an active
    challenger and the cooldown since the last promotion must have elapsed; ``force`` lifts both (a retired model
    comes back). Always writes a ``promote`` audit row.
    """
    if not reason or not reason.strip():
        raise ManualOverrideRefused("a reason is required")
    now = _aware_utc(now)
    config = config or ev.default_config()
    target = session.get(ModelVersion, model_id)
    if target is None:
        raise ManualOverrideRefused(f"model {model_id} does not exist")
    champion = model_registry.get_champion(session)
    if champion is not None and champion.id == target.id:
        raise ManualOverrideRefused(f"{label(target)} is already the champion")
    if target.role == MODEL_ROLE_RETIRED and not force:
        raise ManualOverrideRefused(f"{label(target)} is retired; use --force to bring it back as champion")
    if champion is not None and champion.promoted_at is not None and not force:
        elapsed = (now - _aware_utc(champion.promoted_at)).total_seconds() / 86400.0
        if elapsed < config.cooldown_days:
            raise ManualOverrideRefused(
                f"the champion was promoted {elapsed:.1f} days ago (cooldown {config.cooldown_days:g} days); use --force to override"
            )
    previous_role = target.role
    try:
        row = _manual_row(
            session, ev.DECISION_PROMOTE, reason.strip(), champion.id if champion is not None else target.id, target.id, now,
            {"force": force, "previous_role": previous_role, "previous_champion_id": champion.id if champion is not None else None},
        )
        swap_champion(
            session, target, champion, now,
            {"at": now.isoformat(), "decision": "promote", "manual": True, "reason": reason.strip(), "evaluation_id": row.id, "force": force},
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    return row


def manual_retire(session: Session, model_id: int, reason: str, now: datetime) -> ModelEvaluation:
    """Retire a challenger by hand; the champion cannot be retired (promote another model first)."""
    if not reason or not reason.strip():
        raise ManualOverrideRefused("a reason is required")
    now = _aware_utc(now)
    target = session.get(ModelVersion, model_id)
    if target is None:
        raise ManualOverrideRefused(f"model {model_id} does not exist")
    if target.role == MODEL_ROLE_RETIRED:
        raise ManualOverrideRefused(f"{label(target)} is already retired")
    champion = model_registry.get_champion(session)
    if champion is not None and champion.id == target.id:
        raise ManualOverrideRefused(f"{label(target)} is the champion; promote another model before retiring it")
    try:
        row = _manual_row(
            session, ev.DECISION_RETIRE, reason.strip(), champion.id if champion is not None else target.id, target.id, now,
            {"previous_role": target.role},
        )
        retire_model(
            session, target, now,
            {"at": now.isoformat(), "decision": "retire", "manual": True, "reason": reason.strip(), "evaluation_id": row.id},
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    return row


# --------------------------------------------------------------------------------------------- proposals

@dataclass
class ProposalOutcome:
    report: model_lab.LabReport
    registration: Optional[model_lab.RegistrationResult]
    evaluation_id: Optional[int]  # the 'proposal' audit row (None on a dry run)
    summary: str


def _verdicts(report: model_lab.LabReport) -> List[Dict[str, Any]]:
    return [
        {
            "kind": c.kind,
            "label": c.label,
            "passed": c.gate.passed,
            "gain": c.gate.gain,
            "differs": c.gate.differs,
            "reasons": list(c.gate.reasons),
            "holdout": asdict(c.holdout),
            "holdout_gain": asdict(c.holdout_gain),
        }
        for c in report.candidates
    ]


def run_proposal(
    session: Session,
    now: datetime,
    *,
    dry_run: bool = False,
    register: bool = True,
    seed: int = 42,
    n_configs: int = model_lab.DEFAULT_CONFIGS,
    deadline: Optional[float] = None,
    clock: Callable[[], float] = time.monotonic,
    confirm_database: Optional[str] = None,
    max_challengers: int = model_lab.MAX_CHALLENGERS,
) -> ProposalOutcome:
    """
    Run the historical lab and register the gate-passing candidates as challengers (``register=False`` only plans
    them), then write one ``proposal`` audit row with the verdicts, also when nothing passed: the row is the marker
    that keeps the weekly cadence. A dry run writes nothing. Raises ``LabError`` when the lab cannot run.
    """
    now = _aware_utc(now)
    report = model_lab.run_lab_on_database(session, seed=seed, n_configs=n_configs, deadline=deadline, clock=clock)
    champion = model_registry.get_champion(session)
    refused = None
    if dry_run or not register:
        registration = _plan_registration(session, report, max_challengers)
    else:
        try:
            registration = model_lab.register_candidates(
                session, report, confirm_database=confirm_database, max_challengers=max_challengers
            )
        except model_lab.RegistrationRefused as exc:
            refused = str(exc)
            registration = _plan_registration(session, report, max_challengers)

    passed = sum(1 for c in report.candidates if c.gate.passed)
    wrote = register and not dry_run and refused is None
    if refused is not None:
        action = f"not registered ({refused})"
    elif wrote:
        action = f"{len(registration.registered)} registered"
    else:
        action = f"{len(registration.planned)} would be registered"
    summary = f"{len(report.candidates)} candidate(s) evaluated, {passed} passed the historical gate; {action}"
    if report.partial:
        summary += " (time budget reached: partial lab)"

    evaluation_id = None
    if not dry_run and champion is not None:
        registered = registration.registered if wrote else []
        row = ModelEvaluation(
            evaluated_at=now,
            champion_id=champion.id,
            challenger_id=registered[0].id if registered else champion.id,
            n_games=report.n_games,
            n_market_games=0,
            metrics=ev.jsonable(
                {
                    "seed": report.seed,
                    "split": report.split,
                    "partial": report.partial,
                    "configs_evaluated": report.configs_evaluated,
                    "verdicts": _verdicts(report),
                    "registered": [f"{r.name} {r.version}" for r in registered],
                    "planned": [f"{p.name} {p.version}" for p in registration.planned],
                    "skipped": list(registration.skipped),
                    "refused": refused,
                    "notes": list(report.notes),
                    "elapsed_seconds": report.elapsed_seconds,
                }
            ),
            decision=DECISION_PROPOSAL,
            reason=summary,
        )
        session.add(row)
        session.commit()
        evaluation_id = row.id
    return ProposalOutcome(report, registration, evaluation_id, summary)


def _plan_registration(session: Session, report: model_lab.LabReport, max_challengers: int) -> model_lab.RegistrationResult:
    """What registration would do, without writing; full slots are reported as a skip instead of raising."""
    try:
        return model_lab.register_candidates(session, report, dry_run=True, max_challengers=max_challengers)
    except model_lab.RegistrationRefused as exc:
        result = model_lab.RegistrationResult(dry_run=True)
        result.skipped.append(str(exc))
        return result


def last_proposal(session: Session) -> Optional[ModelEvaluation]:
    """The newest ``proposal`` audit row: the marker of the weekly cadence."""
    return session.execute(
        select(ModelEvaluation)
        .where(ModelEvaluation.decision == DECISION_PROPOSAL)
        .order_by(ModelEvaluation.evaluated_at.desc(), ModelEvaluation.id.desc())
        .limit(1)
    ).scalar_one_or_none()


# ------------------------------------------------------------------------------------------------ league

@dataclass
class LeagueRow:
    model_id: int
    label: str
    role: str
    parent_id: Optional[int]
    promoted_at: Optional[datetime]
    retired_at: Optional[datetime]
    predictions: int  # h2h home predictions recorded
    final_games: int  # ... on games that are final now
    last_decision: Optional[str] = None
    last_evaluated_at: Optional[datetime] = None
    last_reason: Optional[str] = None


def league_rows(session: Session) -> List[LeagueRow]:
    """Every registered model: champion first, then challengers, then the retired, with its last evaluation."""
    champion = model_registry.get_champion(session)
    order = {MODEL_ROLE_CHAMPION: 0, MODEL_ROLE_CHALLENGER: 1, MODEL_ROLE_RETIRED: 2}
    models = session.execute(select(ModelVersion)).scalars().all()
    models.sort(key=lambda m: (0 if champion is not None and m.id == champion.id else order.get(m.role, 3), m.id))
    rows = []
    for model in models:
        base = (
            ModelPrediction.model_version_id == model.id,
            ModelPrediction.market == MarketType.h2h,
            ModelPrediction.side == BetSide.home,
            ModelPrediction.player_id.is_(None),
        )
        predictions = int(session.execute(select(func.count(ModelPrediction.id)).where(*base)).scalar_one())
        final = int(
            session.execute(
                select(func.count(func.distinct(ModelPrediction.game_id)))
                .join(Game, Game.id == ModelPrediction.game_id)
                .where(*base, Game.status == "final")
            ).scalar_one()
        )
        last = last_evaluation(session, model.id)
        is_champion = champion is not None and model.id == champion.id
        rows.append(
            LeagueRow(
                model.id, label(model), MODEL_ROLE_CHAMPION if is_champion else model.role, model.parent_id,
                model.promoted_at, model.retired_at, predictions, final,
                None if last is None else last.decision,
                None if last is None else last.evaluated_at,
                None if last is None else last.reason,
            )
        )
    return rows


def role_changes(session: Session, limit: int = 20) -> List[ModelEvaluation]:
    """Audit rows that changed (or were manually forced to change) a role, newest first."""
    return list(
        session.execute(
            select(ModelEvaluation)
            .where(ModelEvaluation.decision.in_((ev.DECISION_PROMOTE, ev.DECISION_ROLLBACK, ev.DECISION_RETIRE)))
            .order_by(ModelEvaluation.evaluated_at.desc(), ModelEvaluation.id.desc())
            .limit(limit)
        ).scalars()
    )


# ---------------------------------------------------------------------------------------------- text

def format_pass(outcome: EvaluationPass) -> str:
    mode = "applied" if outcome.apply else "dry run (nothing written)"
    switch = "on" if outcome.autopromote else "OFF (decisions are recorded, nothing changes)"
    lines = [f"Evaluation pass {outcome.now.isoformat()}: {mode}; autopromote {switch}"]
    if outcome.message:
        lines.append(f"  {outcome.message}")
        return "\n".join(lines)
    lines.append(f"  champion: {outcome.champion}")
    if not outcome.entries:
        lines.append("  no active challengers")
    for entry in outcome.entries:
        result = entry.result
        if result is None:
            lines.append(f"  {entry.model}: skipped - {entry.note}")
            continue
        gain = result.log_loss_gain
        interval = "" if gain.ci_low is None else f" [{gain.ci_low:+.4f}, {gain.ci_high:+.4f}]"
        lines.append(
            f"  {entry.model}: {result.decision} (n={result.n_games}, {result.days_live:.1f} days live, "
            f"log-loss gain {gain.mean:+.4f}{interval}) - {result.gate_text}"
        )
        lines.append(f"      {result.reason}")
        lines.append(f"      -> {entry.action}" + (f" (row {entry.evaluation_id}, {entry.decision})" if entry.evaluation_id else "") + (f": {entry.note}" if entry.action in (ACTION_FAILED, ACTION_PREVIEW) else ""))
    return "\n".join(lines)
