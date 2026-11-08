"""
``line_move`` (D-71): the live paper test of the line-move model. PAPER ONLY.

The model (``historical_backtest`` D-68 ridge regressions, refit for the live season by
``scripts/register_line_move.py``) predicts how far Pinnacle's line will move from now to the close, for spreads and
totals. The strategy takes the side the close is predicted to move toward when ``|predicted move|`` clears the
market's threshold, flat 1 unit, and is judged by Pinnacle CLV and ROI.

Leak safety (the reason this exists): the features include each team's PREVIOUS game, so a decision is allowed only
once both previous games are final and ingested AND a capture of the game's quotes happened at or after the
bettable instant ``ready_at = max over both teams (previous tip + GAME_DURATION) + SAFETY_MARGIN`` (the same rule as
the offline evaluation in ``line_movement``). A price captured before that instant could predate the previous
result while the model already knows it.

One decision per (game, market), at the first tick where the game is decidable: a ``model_prediction`` is written
(side = the predicted direction, line = Pinnacle's current main line, projection = the predicted close-minus-current
move) and a ``simulated_bet`` only when the threshold is cleared and a price exists at Pinnacle's line. Later ticks
skip the market (``already_decided``), which mirrors the one-shot offline evaluation and makes it one bet per game
and market at most. Never at or after tip-off. ``model_prob`` = Pinnacle's de-vigged probability of the side plus
``Phi(|pred| / sigma) - 0.5`` (the move on the probability scale), ``ev_per_unit`` = ``model_prob * price - 1``.

The model version is a ``shadow`` row (it has no h2h probability, so it stays out of the league and the promotion
gates). Its bets use the staking strategy ``line_move`` with its own bankroll (100 + its settled P/L) and the usual
caps; the champion's strategies never see them. The runner is isolated by the tick: a failure rolls back only this.
"""
import logging
import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

import numpy as np
from sqlalchemy import func, select
from sqlmodel import Session

from app.analytics import betting_policy as policy
from app.analytics.elo import EloParams
from app.analytics.features import FEATURE_NAMES, FeatureState
from app.analytics.props_engine import devig_two_way
from app.analytics.totals_model import TotalsParams, TotalsState
from app.models import (
    MODEL_ROLE_SHADOW,
    BetSide,
    BetStatus,
    Game,
    MarketType,
    ModelPrediction,
    ModelVersion,
    OddsHistory,
    OddsSnapshotCapture,
    Season,
    SimulatedBet,
    StakingStrategy,
)
from app.services import historical_backtest as bt
from app.services.line_movement import GAME_DURATION, SAFETY_MARGIN, final_time
from app.services.model_registry import ModelRegistryError

logger = logging.getLogger(__name__)

FAMILY_NAME = "line_move"
DEFAULT_THRESHOLDS = {"spreads": 0.25, "totals": 0.5}
DEFAULT_HORIZON_HOURS = 20.0
DEFAULT_MAX_QUOTE_AGE_MINUTES = 360.0
NOT_FINAL_LOOKBACK = timedelta(days=3)  # an earlier game of a team still scheduled/live within this window blocks
MARKETS = (MarketType.spreads, MarketType.totals)
STRATEGY = StakingStrategy.line_move
_SETTLED = (BetStatus.won, BetStatus.lost, BetStatus.push)


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _enum(value) -> str:
    return value.value if hasattr(value, "value") else str(value)


def _line(value) -> Optional[Decimal]:
    return None if value is None else Decimal(str(value)).quantize(Decimal("0.1"))


def _prob(value: float) -> Decimal:
    return Decimal(f"{min(max(value, 1e-5), 1.0 - 1e-5):.5f}")


def _normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _local_day(moment: datetime) -> date:
    return _aware(moment).astimezone().date()


def nba_day(game_time: datetime) -> date:
    """Calendar date of a tip as in ``player_game_log`` (same shift as ``margin_features_model.nba_date``)."""
    return (_aware(game_time) - timedelta(hours=6)).date()


# ------------------------------------------------------------------------------------------------ params

@dataclass(frozen=True)
class LineMoveModel:
    """Numpy-only inference from ``model_version.params`` (see ``build_params``)."""

    spreads: bt.RidgeFit
    totals: bt.RidgeFit
    thresholds: Mapping[str, float]
    sigma_spread: float
    sigma_total: float
    margin_features: Any  # MarginFeaturesModel

    @classmethod
    def from_params(cls, params: Mapping[str, Any]) -> "LineMoveModel":
        from app.services.margin_features_model import MarginFeaturesModel

        try:
            if tuple(params["spread_features"]) != bt.SPREAD_MOVE_FEATURES:
                raise ModelRegistryError(f"line_move spread features {params['spread_features']} != {bt.SPREAD_MOVE_FEATURES}")
            if tuple(params["total_features"]) != bt.TOTAL_MOVE_FEATURES:
                raise ModelRegistryError(f"line_move total features {params['total_features']} != {bt.TOTAL_MOVE_FEATURES}")
            if tuple(params["base_features"]) != FEATURE_NAMES:
                raise ModelRegistryError("line_move was trained on another FEATURE_NAMES list")
            if EloParams.from_dict(params.get("elo_params") or {}) != EloParams():
                raise ModelRegistryError("line_move features use the default EloParams (as the backtest does)")
            if TotalsParams.from_dict(params.get("totals_params") or {}) != TotalsParams():
                raise ModelRegistryError("line_move features use the default TotalsParams (as the backtest does)")
            spreads = bt.RidgeFit.from_dict(params["spreads"])
            totals = bt.RidgeFit.from_dict(params["totals"])
            if len(spreads.coef) != len(bt.SPREAD_MOVE_FEATURES) or len(totals.coef) != len(bt.TOTAL_MOVE_FEATURES):
                raise ModelRegistryError("line_move ridge coefficients do not match the feature lists")
            thresholds = {m: float(params["thresholds"][m]) for m in ("spreads", "totals")}
            sigma_spread, sigma_total = float(params["sigma_spread"]), float(params["sigma_total"])
            if min(thresholds.values()) <= 0 or not (sigma_spread > 0 and sigma_total > 0):
                raise ModelRegistryError("line_move thresholds and sigmas must be positive")
            mf = MarginFeaturesModel(params["margin_features"])
        except ModelRegistryError:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise ModelRegistryError(f"line_move params are incomplete or malformed: {exc!r}") from exc
        return cls(spreads, totals, thresholds, sigma_spread, sigma_total, mf)

    def predict_move(self, market: str, x: np.ndarray, mu_total: float, line: float) -> float:
        """Predicted close - current (home line for spreads, total for totals) for a game with features ``x``."""
        x = np.asarray(x, dtype=float)
        sched = bt.schedule_features(x)
        if market == MarketType.spreads.value:
            mu_elo = x[FEATURE_NAMES.index("elo_edge")] / EloParams().elo_per_point
            mu_mf = float(self.margin_features.predict_matrix(x)[1][0])
            return float(self.spreads.predict(bt.spread_move_features(mu_elo, mu_mf, line, sched))[0])
        return float(self.totals.predict(bt.total_move_features(mu_total, line, sched))[0])


def build_params(exports: Mapping[str, Any], thresholds: Optional[Mapping[str, float]] = None,
                 training: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """``model_version.params`` from ``BacktestResult.exports`` of the live season (``config.export_season``)."""
    missing = [k for k in ("spreads", "totals", "margin_features", "sigma_spread", "sigma_total") if k not in exports]
    if missing:
        raise ValueError(f"backtest exports lack {missing}: the export season has no lines or too little training data")
    params = {
        "family": FAMILY_NAME,
        "base_features": list(FEATURE_NAMES),
        "spread_features": list(bt.SPREAD_MOVE_FEATURES),
        "total_features": list(bt.TOTAL_MOVE_FEATURES),
        "spreads": exports["spreads"].to_dict(),
        "totals": exports["totals"].to_dict(),
        "margin_features": exports["margin_features"],
        "sigma_spread": float(exports["sigma_spread"]),
        "sigma_total": float(exports["sigma_total"]),
        "thresholds": dict(thresholds or DEFAULT_THRESHOLDS),
        "elo_params": {},
        "totals_params": {},
        "entry_rule": {"game_duration_hours": GAME_DURATION.total_seconds() / 3600.0,
                       "safety_margin_minutes": SAFETY_MARGIN.total_seconds() / 60.0,
                       "quote": "first capture at or after the bettable instant"},
        "stake": {"strategy": STRATEGY.value, "units": policy.FLAT_UNITS},
        "training": dict(training or {}),
    }
    LineMoveModel.from_params(params)  # never register what cannot be loaded
    return params


def get_line_move_model(session: Session) -> Optional[ModelVersion]:
    """The newest ``line_move`` shadow row (retired rows are ignored), or None when not registered."""
    return session.execute(
        select(ModelVersion)
        .where(ModelVersion.name == FAMILY_NAME, ModelVersion.role == MODEL_ROLE_SHADOW)
        .order_by(ModelVersion.id.desc())
        .limit(1)
    ).scalar_one_or_none()


# ------------------------------------------------------------------------------------------------ recorder

@dataclass(frozen=True)
class LineMoveDecision:
    game_id: int
    market: str
    side: str
    line: float  # the side's own line (spreads) or the total
    predicted_move: float  # close - current, home line / total
    p_fair: float
    model_prob: float
    pinnacle_price: float
    book: Optional[str]
    price: Optional[float]
    bet: bool
    reason: str  # ok | below_threshold | no_price_at_pinnacle_line | stake_below_min | game_started


@dataclass
class LineMoveSummary:
    now: datetime
    dry_run: bool = False
    model: Optional[str] = None  # "line_move 1" or None when not registered
    games_considered: int = 0
    predictions_written: int = 0
    bets_placed: int = 0
    skipped: Counter = field(default_factory=Counter)
    decisions: List[LineMoveDecision] = field(default_factory=list)

    def message(self) -> str:
        if self.model is None:
            return "line_move: not registered"
        skipped = ", ".join(f"{k}={v}" for k, v in sorted(self.skipped.items())) or "none"
        verb = "would write" if self.dry_run else "wrote"
        return (f"line_move ({self.model}, LIVE TEST): {self.games_considered} game(s), {verb} "
                f"{self.predictions_written} decision(s), bets {self.bets_placed}; skipped: {skipped}")


@dataclass(frozen=True)
class _Quote:
    id: int
    book_key: str
    is_sharp: bool
    market: str
    side: str
    line: Optional[Decimal]
    price: float


class LineMoveRecorder:
    def __init__(self, session: Session, now: Optional[datetime] = None, horizon_hours: float = DEFAULT_HORIZON_HOURS,
                 max_quote_age_minutes: float = DEFAULT_MAX_QUOTE_AGE_MINUTES):
        self.session = session
        self.now = _aware(now) if now is not None else datetime.now(timezone.utc)
        self.horizon = timedelta(hours=horizon_hours)
        self.max_quote_age_minutes = max_quote_age_minutes

    def run(self, dry_run: bool = False) -> LineMoveSummary:
        summary = LineMoveSummary(now=self.now, dry_run=dry_run)
        row = get_line_move_model(self.session)
        if row is None:
            return summary
        summary.model = f"{row.name} {row.version}"
        model = LineMoveModel.from_params(row.params or {})

        from app.services.prediction_recorder import PredictionRecorder

        games = PredictionRecorder(self.session, now=self.now, horizon_hours=self.horizon.total_seconds() / 3600.0)._window_games()
        summary.games_considered = len(games)
        if not games:
            return summary
        decided = self._decided(row.id, [g.id for g in games])
        quotes = PredictionRecorder(
            self.session, now=self.now, max_quote_age_minutes=self.max_quote_age_minutes
        )._load_quotes([g.id for g in games])
        last_capture = self._last_capture([g.id for g in games])
        history, state, totals = self._history()
        history_ids = {g.game_id for g in history}
        last_game = self._last_game_by_team(history)
        tips = self._tips()
        season_ids = {label: sid for sid, label in self.session.execute(select(Season.id, Season.season_label))}
        bankroll, day_stake, game_stake = self._ledger([g.id for g in games])

        try:
            for game in games:
                todo = [m for m in MARKETS if (game.id, m.value) not in decided]
                if not todo:
                    summary.skipped["already_decided"] += 1
                    continue
                reason, ready_at = self._readiness(game, history_ids, last_game, tips)
                if reason is not None:
                    summary.skipped[reason] += 1
                    continue
                captured = last_capture.get(game.id)
                if captured is None or (ready_at is not None and captured < ready_at):
                    summary.skipped["no_capture_after_bettable_instant"] += 1
                    continue
                day = nba_day(game.commence_time)
                x = state.vector(game.home_team_id, game.away_team_id, self._season_id(game, season_ids), day)
                mu_total = totals.predict_mu(game.home_team_id, game.away_team_id, self._season_id(game, season_ids))
                for market in todo:
                    self._decide(game, market, model, row, x, mu_total, quotes.get(game.id, []), summary,
                                 bankroll, day_stake, game_stake, dry_run)
            if not dry_run:
                self.session.commit()
        except Exception:
            self.session.rollback()
            raise
        return summary

    # ------------------------------------------------------------------ inputs

    def _decided(self, model_id: int, game_ids: Sequence[int]) -> Set[Tuple[int, str]]:
        """(game, market) already decided by this model version, or bet by any ``line_move`` version."""
        out: Set[Tuple[int, str]] = set()
        for game_id, market in self.session.execute(
            select(ModelPrediction.game_id, ModelPrediction.market).where(
                ModelPrediction.model_version_id == model_id, ModelPrediction.game_id.in_(list(game_ids))
            )
        ):
            out.add((game_id, _enum(market)))
        for game_id, market in self.session.execute(
            select(ModelPrediction.game_id, ModelPrediction.market)
            .join(SimulatedBet, SimulatedBet.prediction_id == ModelPrediction.id)
            .where(SimulatedBet.strategy == STRATEGY, ModelPrediction.game_id.in_(list(game_ids)))
        ):
            out.add((game_id, _enum(market)))
        return out

    def _last_capture(self, game_ids: Sequence[int]) -> Dict[int, datetime]:
        """Newest capture of each game at or before ``now`` (an odds row or a capture marker)."""
        out: Dict[int, datetime] = {}
        for stmt in (
            select(OddsHistory.game_id, func.max(OddsHistory.captured_at))
            .where(OddsHistory.game_id.in_(list(game_ids)), OddsHistory.player_id.is_(None),
                   OddsHistory.market.in_(MARKETS), OddsHistory.captured_at <= self.now)
            .group_by(OddsHistory.game_id),
            select(OddsSnapshotCapture.game_id, func.max(OddsSnapshotCapture.captured_at))
            .where(OddsSnapshotCapture.game_id.in_(list(game_ids)), OddsSnapshotCapture.captured_at <= self.now)
            .group_by(OddsSnapshotCapture.game_id),
        ):
            for game_id, at in self.session.execute(stmt):
                if at is not None:
                    at = _aware(at)
                    if at <= self.now and (game_id not in out or at > out[game_id]):
                        out[game_id] = at
        return out

    def _history(self):
        """Every ingested final game, and the feature states fed with all of them (all are final before ``now``)."""
        from app.services.elo_service import EloRatingService

        history = EloRatingService(self.session).load_games()
        state, totals = FeatureState(EloParams()), TotalsState(TotalsParams())
        for g in history:
            state.update(g)
            totals.update(g)
        return history, state, totals

    @staticmethod
    def _last_game_by_team(history: Sequence) -> Dict[int, Any]:
        last: Dict[int, Any] = {}
        for g in history:  # chronological
            last[g.home_team_id] = g
            last[g.away_team_id] = g
        return last

    def _tips(self) -> Dict[str, datetime]:
        return {
            nba_id: _aware(commence)
            for nba_id, commence in self.session.execute(
                select(Game.nba_game_id, Game.commence_time).where(Game.nba_game_id.is_not(None))
            )
        }

    def _readiness(self, game: Game, history_ids: Set[str], last_game: Mapping[int, Any],
                   tips: Mapping[str, datetime]) -> Tuple[Optional[str], Optional[datetime]]:
        """(skip reason or None, bettable instant or None when neither team has a previous game)."""
        commence = _aware(game.commence_time)
        teams = (game.home_team_id, game.away_team_id)
        earlier = self.session.execute(
            select(Game).where(
                Game.commence_time < commence,
                Game.commence_time >= commence - NOT_FINAL_LOOKBACK,
                Game.status != "postponed",
                (Game.home_team_id.in_(teams)) | (Game.away_team_id.in_(teams)),
            )
        ).scalars().all()
        for other in earlier:
            if other.id == game.id or _aware(other.commence_time) >= commence:
                continue
            if other.status != "final":
                return "previous_game_not_final", None
            if not other.nba_game_id or other.nba_game_id not in history_ids:
                return "previous_game_not_ingested", None
        day = nba_day(commence)
        ends = []
        for team in teams:
            prev = last_game.get(team)
            if prev is None:
                continue
            if prev.game_date >= day:
                return "history_after_game", None
            ends.append(final_time(prev.game_id, prev.game_date, tips)[0])
        return None, (max(ends) + SAFETY_MARGIN) if ends else None

    @staticmethod
    def _season_id(game: Game, season_ids: Mapping[str, int]) -> int:
        from app.services.odds_ingestion import OddsIngestionService
        from app.services.prediction_recorder import UNKNOWN_SEASON_ID

        return season_ids.get(OddsIngestionService.season_label_for(_aware(game.commence_time).date()), UNKNOWN_SEASON_ID)

    def _ledger(self, game_ids: Sequence[int]):
        bankroll = policy.START_BANKROLL + float(self.session.execute(
            select(func.coalesce(func.sum(SimulatedBet.profit_units), 0))
            .where(SimulatedBet.strategy == STRATEGY, SimulatedBet.status.in_(_SETTLED))
        ).scalar() or 0.0)
        day_stake: Dict[date, float] = defaultdict(float)
        game_stake: Dict[int, float] = defaultdict(float)
        for game_id, stake, placed_at in self.session.execute(
            select(ModelPrediction.game_id, SimulatedBet.stake_units, SimulatedBet.placed_at)
            .join(ModelPrediction, ModelPrediction.id == SimulatedBet.prediction_id)
            .where(SimulatedBet.strategy == STRATEGY, SimulatedBet.placed_at >= self.now - timedelta(days=2))
        ):
            game_stake[game_id] += float(stake)
            if placed_at is not None:
                day_stake[_local_day(placed_at)] += float(stake)
        return [bankroll], day_stake, game_stake

    # ------------------------------------------------------------------ one decision

    @staticmethod
    def _pinnacle_pair(quotes: Sequence, market: str) -> Optional[Tuple[Decimal, float, float]]:
        """(Pinnacle line, price home/over, price away/under) at the most balanced sharp pair, or None."""
        from app.services.prediction_recorder import PredictionRecorder

        same = [q for q in quotes if q.market == market]
        pairs = (PredictionRecorder._sharp_spread_pairs(same) if market == MarketType.spreads.value
                 else PredictionRecorder._sharp_totals_pairs(same))
        if not pairs:
            return None
        line, (a, b) = min(pairs.items(), key=lambda kv: (abs(math.log(kv[1][0] / kv[1][1])), abs(kv[0]), kv[0]))
        return line, a, b

    def _decide(self, game: Game, market_type: MarketType, model: LineMoveModel, row: ModelVersion, x: np.ndarray,
                mu_total: float, quotes: Sequence, summary: LineMoveSummary, bankroll: List[float],
                day_stake: Dict[date, float], game_stake: Dict[int, float], dry_run: bool) -> None:
        market = market_type.value
        pair = self._pinnacle_pair(quotes, market)
        if pair is None:
            summary.skipped[f"{market}_no_pinnacle_pair"] += 1
            return
        line, price_a, price_b = pair
        move = model.predict_move(market, x, mu_total, float(line))
        if market == MarketType.spreads.value:
            side = BetSide.home if move < 0 else BetSide.away  # close below the home line: home gets bet up
            side_line = line if side == BetSide.home else -line
        else:
            side = BetSide.over if move > 0 else BetSide.under
            side_line = line
        first = side in (BetSide.home, BetSide.over)
        fair = devig_two_way(price_a, price_b)
        p_fair = fair[0] if first else fair[1]
        pinnacle_price = price_a if first else price_b
        sigma = model.sigma_spread if market == MarketType.spreads.value else model.sigma_total
        p_model = min(max(p_fair + _normal_cdf(abs(move) / sigma) - 0.5, 0.01), 0.99)

        candidates = [q for q in quotes if q.market == market and q.side == side.value and q.line == side_line]
        best = min(candidates, key=lambda q: (-q.price, q.book_key), default=None)
        reason = "ok"
        stake = 0.0
        if abs(move) < model.thresholds[market]:
            reason = "below_threshold"
        elif best is None:
            reason = "no_price_at_pinnacle_line"
        elif _aware(game.commence_time) <= self.now:
            reason = "game_started"  # hard guard: nothing at or after tip-off
        else:
            today = _local_day(self.now)
            stake = policy.cap_stake(policy.flat_stake(), bankroll[0],
                                     daily_room=policy.daily_room(bankroll[0], day_stake[today]),
                                     game_room=policy.game_room(bankroll[0], game_stake[game.id]))
            if stake <= 0:
                reason = "stake_below_min"
        bet = reason == "ok"
        summary.decisions.append(LineMoveDecision(
            game.id, market, side.value, float(side_line), move, p_fair, p_model, pinnacle_price,
            best.book_key if best else None, best.price if best else None, bet, reason,
        ))
        if reason != "ok":
            summary.skipped[f"{market}_{reason}"] += 1
        summary.predictions_written += 1
        if bet:
            summary.bets_placed += 1
            day_stake[_local_day(self.now)] += stake
            game_stake[game.id] += stake
        if dry_run:
            return
        prediction = ModelPrediction(
            model_version_id=row.id, game_id=game.id, market=market_type, side=side, line=_line(side_line),
            model_prob=_prob(p_model), projection=Decimal(f"{move:.2f}"), predicted_at=self.now,
        )
        self.session.add(prediction)
        self.session.flush()
        if not bet:
            return
        self.session.add(SimulatedBet(
            prediction_id=prediction.id,
            odds_taken_id=best.id,
            price_taken=Decimal(f"{best.price:.4f}"),
            line_taken=_line(best.line),
            fair_prob_at_bet=_prob(p_fair),
            ev_per_unit=Decimal(f"{p_model * best.price - 1.0:.5f}"),
            strategy=STRATEGY,
            stake_units=Decimal(f"{stake:.3f}"),
            bankroll_before=Decimal(f"{bankroll[0]:.3f}"),
            predicted_move=Decimal(f"{move:.2f}"),
            pinnacle_price_at_bet=Decimal(f"{pinnacle_price:.4f}"),
            status=BetStatus.pending,
            placed_at=self.now,
        ))
