"""
How much the champion deserves in the `calibrated` strategy's logit blend with Pinnacle (see
``app.analytics.betting_policy.fit_blend_weight``).

Calibration unit: a FINAL game for which the current champion recorded an h2h home prediction strictly before
tip-off AND the sharp book (Pinnacle) had a two-sided h2h quote captured at or before that prediction. The market
side is the sharp book's de-vigged home probability at the prediction time (not the close: the close contains
information the bet could not have used). The outcome is "the home side won".

``model_prediction.fair_decimal`` is NOT the market's price: it is the generated column ``1 / model_prob``, the
model's own fair price, so it cannot supply ``p_fair`` and the Pinnacle pair is read from ``odds_history`` instead.

Read-only; the recorder, the paper report and ``scripts/blend_weight.py`` all call ``compute_blend_weight`` so they
print the same numbers.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import select
from sqlmodel import Session

from app.analytics import betting_policy as policy
from app.models import BetSide, Game, MarketType, ModelPrediction
from app.services import market_close, model_registry


def _aware_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


@dataclass
class CalibrationData:
    game_ids: List[int] = field(default_factory=list)
    p_models: List[float] = field(default_factory=list)
    p_fairs: List[float] = field(default_factory=list)
    outcomes: List[float] = field(default_factory=list)

    @property
    def n(self) -> int:
        return len(self.game_ids)


@dataclass(frozen=True)
class BlendWeight:
    w_used: float = 0.0
    w_hat: float = 0.0
    n: int = 0

    def summary(self) -> str:
        return f"w_used={self.w_used:.3f}, w_hat={self.w_hat:.2f}, n={self.n} games"

    def report_line(self) -> str:
        return (
            f"calibrated blend weight: w_used={self.w_used:.3f}, w_hat={self.w_hat:.2f}, n={self.n} games "
            f"(bets require w_used > 0 and |model - Pinnacle| <= {policy.MAX_DISAGREEMENT * 100:.0f}pp)"
        )


def load_calibration_data(session: Session, model_version_id: int) -> CalibrationData:
    """The calibration games of one model (see the module docstring), ordered by game id."""
    rows = session.execute(
        select(
            ModelPrediction.game_id,
            ModelPrediction.model_prob,
            ModelPrediction.predicted_at,
            Game.commence_time,
            Game.home_score,
            Game.away_score,
        )
        .join(Game, Game.id == ModelPrediction.game_id)
        .where(
            ModelPrediction.model_version_id == model_version_id,
            ModelPrediction.market == MarketType.h2h,
            ModelPrediction.side == BetSide.home,
            ModelPrediction.player_id.is_(None),
            ModelPrediction.predicted_at.is_not(None),
            Game.status == "final",
            Game.home_score.is_not(None),
            Game.away_score.is_not(None),
        )
        .order_by(ModelPrediction.game_id)
    ).all()
    candidates = {
        game_id: (float(prob), _aware_utc(predicted_at), home_score > away_score)
        for game_id, prob, predicted_at, commence, home_score, away_score in rows
        if _aware_utc(predicted_at) < _aware_utc(commence) and home_score != away_score
    }
    data = CalibrationData()
    if not candidates:
        return data
    fair_by_game = market_close.sharp_home_probs_as_of(
        session, {game_id: predicted_at for game_id, (_, predicted_at, _) in candidates.items()}, list(candidates)
    )
    for game_id in sorted(candidates):
        p_fair = fair_by_game.get(game_id)
        if p_fair is None:
            continue
        p_model, _, home_won = candidates[game_id]
        data.game_ids.append(game_id)
        data.p_models.append(p_model)
        data.p_fairs.append(p_fair)
        data.outcomes.append(1.0 if home_won else 0.0)
    return data


def compute_blend_weight(session: Session, model_version_id: Optional[int] = None) -> BlendWeight:
    """``BlendWeight`` of the given model (default: the current champion); zeros when there is no champion."""
    if model_version_id is None:
        champion = model_registry.get_champion(session)
        if champion is None:
            return BlendWeight()
        model_version_id = champion.id
    data = load_calibration_data(session, model_version_id)
    w_used, w_hat, n = policy.fit_blend_weight(data.p_models, data.p_fairs, data.outcomes)
    return BlendWeight(w_used, w_hat, n)
