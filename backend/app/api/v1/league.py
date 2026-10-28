"""
Model League API router: provides a read-only, cached view of the quantitative model league.
"""
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.deps import get_db_session
from app.services.league_cache import LeagueCache
from app.services.league_report import build_league

router = APIRouter()
league_cache = LeagueCache(ttl_seconds=300.0)


class GainResponse(BaseModel):
    mean: float
    ci_low: Optional[float] = None
    ci_high: Optional[float] = None
    bound_low: Optional[float] = None
    bound_high: Optional[float] = None


class ChampionResponse(BaseModel):
    model_id: int
    label: str
    role: str
    predictions: int
    final_games: int
    days_live: Optional[float] = None


class ChallengerResponse(BaseModel):
    model_id: int
    label: str
    role: str
    predictions: int
    final_games: int
    days_live: Optional[float] = None
    paired_n: int
    target_n: int = 150
    champion_log_loss: Optional[float] = None
    challenger_log_loss: Optional[float] = None
    log_loss_gain: Optional[GainResponse] = None
    margin_nll_gain: Optional[GainResponse] = None
    market_brier_gap: Optional[float] = None
    gate_text: str
    decision: str
    last_decision: Optional[str] = None
    last_evaluated_at: Optional[datetime] = None
    last_reason: Optional[str] = None


class RoleChangeResponse(BaseModel):
    at: Optional[datetime] = None
    decision: str
    model: str
    reason: str


class LeagueResponse(BaseModel):
    now: datetime
    min_games: int = 150
    champion: Optional[ChampionResponse] = None
    challengers: List[ChallengerResponse] = Field(default_factory=list)
    changes: List[RoleChangeResponse] = Field(default_factory=list)
    last_proposal: Optional[datetime] = None
    last_proposal_summary: Optional[str] = None


def format_league_response(session: Session) -> LeagueResponse:
    league = build_league(session)
    champion_resp = None
    if league.champion is not None:
        champion_resp = ChampionResponse(
            model_id=league.champion.model_id,
            label=league.champion.label,
            role=league.champion.role,
            predictions=league.champion.predictions,
            final_games=league.champion.final_games,
            days_live=league.champion.days_live,
        )

    challengers_resp = []
    for ch in league.challengers:
        res = ch.result
        log_loss_gain = None
        margin_nll_gain = None
        market_brier_gap = None
        gate_text = ""
        decision = "insufficient_data"
        champ_ll = None
        chall_ll = None

        if res is not None:
            gate_text = res.gate_text
            decision = res.decision
            if res.champion is not None:
                champ_ll = res.champion.log_loss
            if res.challenger is not None:
                chall_ll = res.challenger.log_loss
            if res.log_loss_gain is not None:
                log_loss_gain = GainResponse(
                    mean=res.log_loss_gain.mean,
                    ci_low=res.log_loss_gain.ci_low,
                    ci_high=res.log_loss_gain.ci_high,
                    bound_low=res.log_loss_gain.bound_low,
                    bound_high=res.log_loss_gain.bound_high,
                )
            if res.margin_nll_gain is not None:
                margin_nll_gain = GainResponse(
                    mean=res.margin_nll_gain.mean,
                    ci_low=res.margin_nll_gain.ci_low,
                    ci_high=res.margin_nll_gain.ci_high,
                    bound_low=res.margin_nll_gain.bound_low,
                    bound_high=res.margin_nll_gain.bound_high,
                )
            if res.market is not None:
                market_brier_gap = res.market.market_gap_vs_champion

        challengers_resp.append(
            ChallengerResponse(
                model_id=ch.model_id,
                label=ch.label,
                role=ch.role,
                predictions=ch.predictions,
                final_games=ch.final_games,
                days_live=ch.days_live,
                paired_n=res.n_games if res is not None else 0,
                target_n=league.min_games,
                champion_log_loss=champ_ll,
                challenger_log_loss=chall_ll,
                log_loss_gain=log_loss_gain,
                margin_nll_gain=margin_nll_gain,
                market_brier_gap=market_brier_gap,
                gate_text=gate_text,
                decision=decision,
                last_decision=ch.last_decision,
                last_evaluated_at=ch.last_evaluated_at,
                last_reason=ch.last_reason,
            )
        )

    changes_resp = [
        RoleChangeResponse(
            at=change.at,
            decision=change.decision,
            model=change.model,
            reason=change.reason,
        )
        for change in league.changes
    ]

    return LeagueResponse(
        now=league.now,
        min_games=league.min_games,
        champion=champion_resp,
        challengers=challengers_resp,
        changes=changes_resp,
        last_proposal=league.last_proposal,
        last_proposal_summary=league.last_proposal_summary,
    )


@router.get("/league", response_model=LeagueResponse)
def get_league(session: Session = Depends(get_db_session)) -> LeagueResponse:
    """
    Returns the current model league state: champion, challengers with evaluation
    metrics and promotion gates, role changes history, and candidate proposal information.
    Cached in-memory with a 5-minute TTL. Read-only; never writes to the database.
    """
    return league_cache.get_or_compute(lambda: format_league_response(session))
