"""
The "Model league" report: where each active model stands against the champion, in numbers and in words.

For every active challenger the live paired evaluation (``model_evaluation.evaluate_challenger``, read-only) gives
the paired sample ("n=12/150"), the log loss of both models, the gain with its 95% interval, the margin-NLL gain, the
Brier gap to the market and the promotion gate in words ("needs 138 more games", "cooldown until ...", "gate
passed"); the last audit row adds what the engine actually decided and when. Role changes (promotions, rollbacks,
retirements, manual or not) are listed below. When there is no evidence yet the report says so plainly instead of
printing empty statistics.
"""
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Dict, List, Optional

from sqlmodel import Session

from app.models import MODEL_ROLE_CHALLENGER, ModelVersion
from app.services import model_evaluation as ev
from app.services import model_promotion, model_registry


def _aware_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


@dataclass
class LeagueEntry:
    model_id: int
    label: str
    role: str
    predictions: int
    final_games: int
    days_live: Optional[float]
    result: Optional[ev.EvaluationResult] = None  # challengers: the live paired evaluation against the champion
    last_decision: Optional[str] = None
    last_evaluated_at: Optional[datetime] = None
    last_reason: Optional[str] = None


@dataclass
class RoleChange:
    at: Optional[datetime]
    decision: str
    model: str
    reason: str


@dataclass
class League:
    now: datetime
    min_games: int
    champion: Optional[LeagueEntry] = None
    challengers: List[LeagueEntry] = field(default_factory=list)
    changes: List[RoleChange] = field(default_factory=list)
    last_proposal: Optional[datetime] = None
    last_proposal_summary: Optional[str] = None


def build_league(session: Session, now: Optional[datetime] = None, config: Optional[ev.EvaluationConfig] = None) -> League:
    now = _aware_utc(now) if now is not None else datetime.now(timezone.utc)
    config = config or ev.default_config()
    league = League(now=now, min_games=config.min_games)
    champion = model_registry.get_champion(session)
    if champion is None:
        return league

    rows: Dict[int, model_promotion.LeagueRow] = {row.model_id: row for row in model_promotion.league_rows(session)}
    challengers = [row for row in model_registry.list_active(session) if row.role == MODEL_ROLE_CHALLENGER and row.id != champion.id]
    if config.n_challengers is None:
        config = replace(config, n_challengers=len(challengers))

    def entry_for(model: ModelVersion, result: Optional[ev.EvaluationResult]) -> LeagueEntry:
        row = rows[model.id]
        first = ev.first_prediction_time(session, model.id)
        days = None if first is None else max(0.0, (now - first).total_seconds() / 86400.0)
        return LeagueEntry(
            model.id, row.label, row.role, row.predictions, row.final_games, days, result,
            row.last_decision, row.last_evaluated_at, row.last_reason,
        )

    league.champion = entry_for(champion, None)
    for model in challengers:
        result = ev.evaluate_challenger(session, model, champion, now, config)
        entry = entry_for(model, result)
        if entry.days_live is not None:
            entry.days_live = result.days_live  # for the previous champion this counts from its demotion
        league.challengers.append(entry)

    labels = {row.model_id: row.label for row in rows.values()}
    for change in model_promotion.role_changes(session, limit=10):
        league.changes.append(
            RoleChange(change.evaluated_at, change.decision, labels.get(change.challenger_id, f"model {change.challenger_id}"), change.reason or "")
        )
    proposal = model_promotion.last_proposal(session)
    if proposal is not None:
        league.last_proposal, league.last_proposal_summary = proposal.evaluated_at, proposal.reason
    return league


# ------------------------------------------------------------------------------------------------- text

def _date(moment: Optional[datetime]) -> str:
    return "n/a" if moment is None else _aware_utc(moment).strftime("%Y-%m-%d")


def _gain(gain: ev.Gain) -> str:
    interval = "" if gain.ci_low is None else f" (95% CI {gain.ci_low:+.4f} .. {gain.ci_high:+.4f})"
    return f"{gain.mean:+.4f}{interval}"


def format_league(league: League) -> str:
    lines = ["Model league (live paired evaluation against the champion; gain = champion minus challenger, positive = challenger better)"]
    if league.champion is None:
        lines.append("  No champion registered.")
        return "\n".join(lines)

    champion = league.champion
    live = "" if champion.days_live is None else f", predicting for {champion.days_live:.0f} days"
    lines.append(f"  champion    {champion.label}: {champion.predictions} predictions ({champion.final_games} on final games){live}")
    if not league.challengers:
        lines.append("  No active challengers: the champion runs alone until the weekly proposal registers one.")

    for entry in league.challengers:
        result = entry.result
        days = "no predictions yet" if entry.days_live is None else f"{entry.days_live:.1f} days live"
        since = " (previous champion: games since its demotion)" if result.previous_champion else ""
        lines.append(f"  challenger  {entry.label}: {days}, paired n={result.n_games}/{league.min_games}{since}")
        if result.n_games == 0:
            lines.append("      no paired games yet: not enough data to compare it with the champion.")
        else:
            lines.append(
                f"      log loss    champion {result.champion.log_loss:.4f} | challenger {result.challenger.log_loss:.4f} | "
                f"gain {_gain(result.log_loss_gain)}"
            )
            lines.append(f"      margin NLL  gain {_gain(result.margin_nll_gain)}")
            if result.market is None:
                lines.append("      vs market   no game with a Pinnacle closing pair yet")
            else:
                lines.append(
                    f"      vs market   Brier gap champion {result.market.gap_champion:+.4f} | challenger "
                    f"{result.market.gap_challenger:+.4f} | difference {result.market.gap_difference:+.4f} over {result.market.n} game(s)"
                    + ("" if result.market.n >= result.thresholds["market_min_games"] else f" (guard applies from {result.thresholds['market_min_games']})")
                )
            if result.n_games < 2 or result.log_loss_gain.ci_low is None:
                lines.append("      too few games for a confidence interval.")
        late = f", {result.n_late_excluded} late prediction(s) excluded" if result.n_late_excluded else ""
        lines.append(f"      gate        {result.gate_text}{late}")
        last = "no evaluation recorded yet" if entry.last_decision is None else f"{entry.last_decision} on {_date(entry.last_evaluated_at)}"
        lines.append(f"      last audit  {last}; live verdict: {result.decision}")

    lines.append("")
    lines.append("Promotion and retirement history")
    if not league.changes:
        lines.append("  No promotion, rollback or retirement yet.")
    for change in league.changes:
        lines.append(f"  {_date(change.at)}  {change.decision:<8} {change.model}: {change.reason}")
    if league.last_proposal is not None:
        lines.append(f"  last candidate proposal {_date(league.last_proposal)}: {league.last_proposal_summary}")
    else:
        lines.append("  no candidate proposal has run yet.")
    return "\n".join(lines)
