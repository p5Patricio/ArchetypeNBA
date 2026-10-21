"""
Live shadow evaluation: paired statistics of a challenger against the champion, and the decision they allow.

Unit of evidence. A final game for which BOTH models recorded an h2h home prediction (market 'h2h', side 'home',
no player, no line) strictly BEFORE tip-off. A prediction recorded at or after ``commence_time`` is excluded and
counted (``n_late_excluded``): it could have seen the game, and the recorder is idempotent, so a missing early
prediction is never repaired later. Games only one model predicted are counted too (``n_unpaired``).

Metrics (all per game, then averaged). Log loss (probabilities clipped to [1e-6, 1 - 1e-6]) is the primary one;
Brier and the margin Gaussian negative log-likelihood (expected home margin from ``projection``, sigma from the
model's ``params['sigma']``) are secondary. Every "gain" is champion minus challenger, so POSITIVE = the challenger
is better. Where a game also has a sharp-book (Pinnacle) closing pair captured at or before tip-off, the Brier of
each model is compared with the Brier of the de-vigged market on those games (``market_close``).

Uncertainty. A seeded percentile bootstrap over games (``model_lab.bootstrap_means``; the same indices serve every
metric, so the pairing is preserved). With k active challengers the one-sided bounds use confidence 1 - 0.05 / k
(Bonferroni: k challengers are each tested against the same champion), and the plain two-sided 95% interval is
kept for the report.

Decision, in this order (``evaluate_paired``):

1. ``retire``   the challenger is significantly worse (mean gain < 0 and the one-sided UPPER bound of the log-loss
                gain < 0) with at least RETIRE_MIN_GAMES (100) paired games. It comes before the sample gate on
                purpose: RETIRE_MIN_GAMES is below MIN_GAMES, so evaluating it after ``insufficient_data`` would
                make the 100-game rule unreachable.
2. ``insufficient_data``  fewer than MIN_GAMES (150) paired games or fewer than MIN_DAYS_LIVE (14) days live.
3. ``retire``   older than RETIRE_AGE_DAYS (90) with at least RETIRE_AGE_MIN_GAMES (300) paired games and the
                statistical promotion gate not met. "Age" is the time since the first recorded prediction, or
                since the demotion for the previous champion (which has been predicting for much longer).
4. ``promote``  ALL of: lower bound of the log-loss gain > 0; lower bound of the margin-NLL gain > -0.02; when at
                least MARKET_MIN_GAMES (50) games have a market probability, the challenger's Brier gap to the
                market is not worse than the champion's by more than 0.005; at least COOLDOWN_DAYS (30) days
                since the champion's ``promoted_at``. Everything but the cooldown passing yields ``keep`` with the
                cooldown in the reason. The previous champion returning is labelled ``rollback`` instead.
5. ``keep``     otherwise.

The previous champion (the model a promotion replaced) is judged on the games since its demotion only, and its
days live and age count from the demotion: the games that dethroned it must not retire it a day later.

The thresholds are module constants, overridable through ``Settings`` (``EvaluationConfig.from_settings``).
"""
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import numpy as np
from sqlalchemy import func, select
from sqlmodel import Session

from app.models import MODEL_ROLE_CHALLENGER, BetSide, Game, MarketType, ModelPrediction, ModelVersion
from app.services import market_close, model_registry
from app.services.elo_service import DEFAULT_SIGMA
from app.services.model_lab import BOOTSTRAP_RESAMPLES, bootstrap_means

MIN_GAMES = 150
MIN_DAYS_LIVE = 14
COOLDOWN_DAYS = 30
RETIRE_MIN_GAMES = 100
RETIRE_AGE_DAYS = 90
RETIRE_AGE_MIN_GAMES = 300
MARKET_MIN_GAMES = 50
MARKET_MAX_WORSE = 0.005  # challenger Brier gap to the market minus the champion's
MARGIN_NLL_FLOOR = -0.02  # nats per game: the margin NLL may be this much worse (lower bound of the gain)
ALPHA = 0.05  # family-wise error rate; each of k challengers is tested at ALPHA / k
SEED = 42
PROB_CLIP = 1e-6

DECISION_PROMOTE = "promote"
DECISION_ROLLBACK = "rollback"
DECISION_RETIRE = "retire"
DECISION_KEEP = "keep"
DECISION_INSUFFICIENT = "insufficient_data"

_SECONDS_PER_DAY = 86400.0


@dataclass(frozen=True)
class EvaluationConfig:
    min_games: int = MIN_GAMES
    min_days_live: float = MIN_DAYS_LIVE
    cooldown_days: float = COOLDOWN_DAYS
    retire_min_games: int = RETIRE_MIN_GAMES
    retire_age_days: float = RETIRE_AGE_DAYS
    retire_age_min_games: int = RETIRE_AGE_MIN_GAMES
    market_min_games: int = MARKET_MIN_GAMES
    market_max_worse: float = MARKET_MAX_WORSE
    margin_nll_floor: float = MARGIN_NLL_FLOOR
    alpha: float = ALPHA
    resamples: int = BOOTSTRAP_RESAMPLES
    seed: int = SEED
    n_challengers: Optional[int] = None  # k; None = count the active challengers in the registry

    @classmethod
    def from_settings(cls, settings: Any = None, **overrides: Any) -> "EvaluationConfig":
        """The module thresholds with the ``LEARNING_*`` settings applied (``settings`` defaults to app.config)."""
        if settings is None:
            from app.config import settings as app_settings

            settings = app_settings
        values = {
            "min_games": int(getattr(settings, "LEARNING_MIN_GAMES", MIN_GAMES)),
            "min_days_live": float(getattr(settings, "LEARNING_MIN_DAYS_LIVE", MIN_DAYS_LIVE)),
            "cooldown_days": float(getattr(settings, "LEARNING_COOLDOWN_DAYS", COOLDOWN_DAYS)),
        }
        return cls(**{**values, **overrides})


# ------------------------------------------------------------------------------------------------- data

def _aware_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _sigma_of(model: ModelVersion) -> float:
    sigma = float((model.params or {}).get("sigma") or 0.0)
    return sigma if sigma > 0 else DEFAULT_SIGMA


@dataclass
class PairedData:
    """Aligned per-game arrays (sorted by game id) of the games both models predicted before tip-off."""

    champion_id: int
    challenger_id: int
    game_ids: np.ndarray
    win: np.ndarray  # 1.0 when the home team won
    margin: np.ndarray  # actual home margin
    p_champion: np.ndarray
    p_challenger: np.ndarray
    mu_champion: np.ndarray
    mu_challenger: np.ndarray
    sigma_champion: float
    sigma_challenger: float
    market_p: np.ndarray  # de-vigged sharp closing home probability; NaN where the game has none
    n_late_excluded: int = 0  # both models have a prediction but one was recorded at or after tip-off
    n_unpaired: int = 0  # final games predicted by only one of the two models
    first_prediction_at: Optional[datetime] = None  # the challenger's first recorded h2h home prediction
    since: Optional[datetime] = None  # only games that tipped off at or after this instant are evidence

    @property
    def n(self) -> int:
        return int(len(self.game_ids))

    @property
    def n_market(self) -> int:
        return int(np.count_nonzero(~np.isnan(self.market_p)))


def first_prediction_time(session: Session, model_id: int) -> Optional[datetime]:
    value = session.execute(
        select(func.min(ModelPrediction.predicted_at)).where(
            ModelPrediction.model_version_id == model_id,
            ModelPrediction.market == MarketType.h2h,
            ModelPrediction.side == BetSide.home,
            ModelPrediction.player_id.is_(None),
        )
    ).scalar_one()
    return None if value is None else _aware_utc(value)


def collect_paired_games(
    session: Session, champion_id: int, challenger_id: int, since: Optional[datetime] = None
) -> PairedData:
    """The paired evidence of a champion/challenger couple (see the module docstring), optionally from ``since`` on."""
    if champion_id == challenger_id:
        raise ValueError("a model cannot be paired with itself")
    champion = session.get(ModelVersion, champion_id)
    challenger = session.get(ModelVersion, challenger_id)
    if champion is None or challenger is None:
        raise ValueError(f"unknown model version(s): {champion_id}, {challenger_id}")

    rows = session.execute(
        select(
            ModelPrediction.game_id,
            ModelPrediction.model_version_id,
            ModelPrediction.model_prob,
            ModelPrediction.projection,
            ModelPrediction.predicted_at,
            Game.commence_time,
            Game.home_score,
            Game.away_score,
        )
        .join(Game, Game.id == ModelPrediction.game_id)
        .where(
            ModelPrediction.model_version_id.in_([champion_id, challenger_id]),
            ModelPrediction.market == MarketType.h2h,
            ModelPrediction.side == BetSide.home,
            ModelPrediction.player_id.is_(None),
            ModelPrediction.line.is_(None),
            Game.status == "final",
            Game.home_score.is_not(None),
            Game.away_score.is_not(None),
        )
    ).all()

    # game id -> {"game": (commence, home, away), model id -> earliest usable (predicted_at, p, mu) | None}
    since = None if since is None else _aware_utc(since)
    games: Dict[int, Dict[Any, Any]] = {}
    for game_id, model_id, prob, projection, predicted_at, commence, home_score, away_score in rows:
        if since is not None and _aware_utc(commence) < since:
            continue
        entry = games.setdefault(game_id, {"game": (_aware_utc(commence), int(home_score), int(away_score))})
        entry.setdefault(model_id, None)  # a row exists, whether or not it is usable
        if predicted_at is None or projection is None or _aware_utc(predicted_at) >= entry["game"][0]:
            continue
        candidate = (_aware_utc(predicted_at), float(prob), float(projection))
        if entry[model_id] is None or candidate[0] < entry[model_id][0]:
            entry[model_id] = candidate

    late = unpaired = 0
    kept: List[tuple] = []
    for game_id in sorted(games):
        entry = games[game_id]
        commence, home_score, away_score = entry["game"]
        if home_score == away_score:
            continue
        if champion_id not in entry or challenger_id not in entry:
            unpaired += 1
        elif entry[champion_id] is None or entry[challenger_id] is None:
            late += 1
        else:
            kept.append((game_id, commence, home_score, away_score, entry[champion_id], entry[challenger_id]))

    game_ids = np.array([item[0] for item in kept], dtype=np.int64)
    commence_by_game = {item[0]: item[1] for item in kept}
    closing = market_close.closing_marker_game_ids(session) & set(commence_by_game)
    fair = market_close.sharp_closing_home_probs(session, commence_by_game, sorted(closing))
    return PairedData(
        champion_id=champion_id,
        challenger_id=challenger_id,
        game_ids=game_ids,
        win=np.array([1.0 if item[2] > item[3] else 0.0 for item in kept]),
        margin=np.array([float(item[2] - item[3]) for item in kept]),
        p_champion=np.array([item[4][1] for item in kept]),
        p_challenger=np.array([item[5][1] for item in kept]),
        mu_champion=np.array([item[4][2] for item in kept]),
        mu_challenger=np.array([item[5][2] for item in kept]),
        sigma_champion=_sigma_of(champion),
        sigma_challenger=_sigma_of(challenger),
        market_p=np.array([fair.get(item[0], math.nan) for item in kept]),
        n_late_excluded=late,
        n_unpaired=unpaired,
        first_prediction_at=first_prediction_time(session, challenger_id),
        since=since,
    )


def is_previous_champion(champion: ModelVersion, challenger: ModelVersion) -> bool:
    """True when ``challenger`` is the model ``champion`` replaced (a promotion sets ``parent_id`` to the old champion)."""
    return champion.parent_id is not None and champion.parent_id == challenger.id


def collect_for(session: Session, champion: ModelVersion, challenger: ModelVersion) -> PairedData:
    """
    The evidence the engine judges ``challenger`` on. Normally every paired game; for the previous champion only the
    games since it was demoted. Its earlier games are the very evidence that dethroned it: counting them again would
    make it "significantly worse" the day after the promotion and retire it, so the rollback watch could never
    work. After a demotion it has to earn its way back (or be retired) on fresh games.
    """
    since = champion.promoted_at if is_previous_champion(champion, challenger) else None
    return collect_paired_games(session, champion.id, challenger.id, since=since)


# --------------------------------------------------------------------------------------------- metrics

def log_loss_each(p: np.ndarray, win: np.ndarray) -> np.ndarray:
    p = np.clip(p, PROB_CLIP, 1.0 - PROB_CLIP)
    return -(win * np.log(p) + (1.0 - win) * np.log(1.0 - p))


def brier_each(p: np.ndarray, win: np.ndarray) -> np.ndarray:
    return (p - win) ** 2


def margin_nll_each(mu: np.ndarray, margin: np.ndarray, sigma: float) -> np.ndarray:
    """Gaussian negative log-likelihood of the actual margin, nats per game."""
    return 0.5 * np.log(2.0 * np.pi * sigma**2) + (margin - mu) ** 2 / (2.0 * sigma**2)


@dataclass(frozen=True)
class Scores:
    log_loss: float
    brier: float
    margin_nll: float


@dataclass(frozen=True)
class Gain:
    """Mean of a per-game improvement (champion minus challenger: positive = challenger better) with its bounds."""

    mean: float
    ci_low: Optional[float] = None  # plain two-sided 95% bootstrap interval
    ci_high: Optional[float] = None
    bound_low: Optional[float] = None  # one-sided bounds at confidence 1 - alpha / k
    bound_high: Optional[float] = None


def paired_gain(values: np.ndarray, seed: int, resamples: int, k: int, alpha: float = ALPHA) -> Gain:
    """Mean of ``values`` with bootstrap intervals; the bounds stay None below two games (nothing to resample)."""
    if len(values) == 0:
        return Gain(mean=0.0)
    mean = float(values.mean())
    if len(values) < 2:
        return Gain(mean=mean)
    means = bootstrap_means(values, seed, resamples)
    tail = 100.0 * alpha / max(1, k)
    ci_low, ci_high, bound_low, bound_high = np.percentile(means, [2.5, 97.5, tail, 100.0 - tail])
    return Gain(mean, float(ci_low), float(ci_high), float(bound_low), float(bound_high))


@dataclass(frozen=True)
class MarketComparison:
    """Brier of both models against the de-vigged sharp close on the games that have one."""

    n: int
    brier_market: float
    brier_champion: float
    brier_challenger: float
    gap_champion: float  # Brier(champion) - Brier(market); negative = beats the market
    gap_challenger: float
    gap_difference: float  # gap_challenger - gap_champion; positive = the challenger is further from the market
    brier_gain: Gain  # champion minus challenger Brier on these games


# ------------------------------------------------------------------------------------------------ result

@dataclass
class EvaluationResult:
    champion_id: int
    challenger_id: int
    evaluated_at: datetime
    n_games: int
    n_market_games: int
    n_late_excluded: int
    n_unpaired: int
    days_live: float
    age_days: float
    days_since_promotion: Optional[float]
    cooldown_until: Optional[datetime]
    k: int
    confidence: float  # of the one-sided bounds: 1 - alpha / k
    seed: int
    resamples: int
    thresholds: Dict[str, Any]
    previous_champion: bool
    evidence_since: Optional[datetime]  # set for the previous champion: only games since its demotion count
    champion: Optional[Scores]
    challenger: Optional[Scores]
    log_loss_gain: Gain
    brier_gain: Gain
    margin_nll_gain: Gain
    market: Optional[MarketComparison]
    gates: Dict[str, Optional[bool]]  # name -> passed (None = could not be judged yet)
    gate_text: str  # the gate status in words
    decision: str
    reason: str

    @property
    def statistical_gate_passed(self) -> bool:
        return all(self.gates.get(name) is True for name in ("log_loss", "margin_nll")) and self.gates.get("market") is not False

    def to_metrics(self) -> Dict[str, Any]:
        """Every number behind the decision as JSON-safe data (stored in ``model_evaluation.metrics``)."""
        return jsonable(asdict(self))


def jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    if isinstance(value, datetime):
        return _aware_utc(value).isoformat()
    if isinstance(value, (np.floating, float)):
        return None if math.isnan(float(value)) else float(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.bool_):
        return bool(value)
    return value


def _signed(value: Optional[float]) -> str:
    return "n/a" if value is None else f"{value:+.4f}"


def _market_comparison(data: PairedData, seed: int, resamples: int, k: int, alpha: float) -> Optional[MarketComparison]:
    rows = ~np.isnan(data.market_p)
    if not rows.any():
        return None
    win, market = data.win[rows], data.market_p[rows]
    brier_market = float(brier_each(market, win).mean())
    brier_champion = float(brier_each(data.p_champion[rows], win).mean())
    brier_challenger = float(brier_each(data.p_challenger[rows], win).mean())
    gain = paired_gain(brier_each(data.p_champion[rows], win) - brier_each(data.p_challenger[rows], win), seed, resamples, k, alpha)
    return MarketComparison(
        n=int(rows.sum()),
        brier_market=brier_market,
        brier_champion=brier_champion,
        brier_challenger=brier_challenger,
        gap_champion=brier_champion - brier_market,
        gap_challenger=brier_challenger - brier_market,
        gap_difference=brier_challenger - brier_champion,
        brier_gain=gain,
    )


def evaluate_paired(
    data: PairedData,
    *,
    now: datetime,
    days_live: float,
    age_days: float,
    days_since_promotion: Optional[float],
    k: int,
    config: EvaluationConfig,
    previous_champion: bool = False,
) -> EvaluationResult:
    """The statistics and the decision for already collected paired data (no database access)."""
    k = max(1, int(k))
    n = data.n
    seed, resamples = config.seed, config.resamples

    scores_champion = scores_challenger = None
    if n:
        scores_champion = Scores(
            float(log_loss_each(data.p_champion, data.win).mean()),
            float(brier_each(data.p_champion, data.win).mean()),
            float(margin_nll_each(data.mu_champion, data.margin, data.sigma_champion).mean()),
        )
        scores_challenger = Scores(
            float(log_loss_each(data.p_challenger, data.win).mean()),
            float(brier_each(data.p_challenger, data.win).mean()),
            float(margin_nll_each(data.mu_challenger, data.margin, data.sigma_challenger).mean()),
        )
    log_loss_gain = paired_gain(
        log_loss_each(data.p_champion, data.win) - log_loss_each(data.p_challenger, data.win), seed, resamples, k, config.alpha
    )
    brier_gain = paired_gain(
        brier_each(data.p_champion, data.win) - brier_each(data.p_challenger, data.win), seed, resamples, k, config.alpha
    )
    nll_gain = paired_gain(
        margin_nll_each(data.mu_champion, data.margin, data.sigma_champion)
        - margin_nll_each(data.mu_challenger, data.margin, data.sigma_challenger),
        seed, resamples, k, config.alpha,
    )
    market = _market_comparison(data, seed, resamples, k, config.alpha)

    # ---- gates (None = not judgeable yet)
    gates: Dict[str, Optional[bool]] = {
        "games": n >= config.min_games,
        "days": days_live >= config.min_days_live,
        "log_loss": None if log_loss_gain.bound_low is None else log_loss_gain.bound_low > 0.0,
        "margin_nll": None if nll_gain.bound_low is None else nll_gain.bound_low > config.margin_nll_floor,
        "market": None,
    }
    if market is not None and market.n >= config.market_min_games:
        gates["market"] = market.gap_difference <= config.market_max_worse
    cooldown_ok = days_since_promotion is None or days_since_promotion >= config.cooldown_days
    gates["cooldown"] = cooldown_ok
    cooldown_until = None
    if not cooldown_ok:
        cooldown_until = _aware_utc(now) + timedelta(days=config.cooldown_days - days_since_promotion)

    statistical_ok = gates["log_loss"] is True and gates["margin_nll"] is True and gates["market"] is not False

    confidence = 1.0 - config.alpha / k
    pct = f"{confidence * 100:.1f}%"
    significantly_worse = (
        n >= config.retire_min_games
        and log_loss_gain.mean < 0.0
        and log_loss_gain.bound_high is not None
        and log_loss_gain.bound_high < 0.0
    )

    if significantly_worse:
        decision = DECISION_RETIRE
        reason = (
            f"significantly worse than the champion: log-loss gain {_signed(log_loss_gain.mean)}, upper bound "
            f"{_signed(log_loss_gain.bound_high)} < 0 at {pct} confidence over {n} paired games"
        )
    elif not gates["games"] or not gates["days"]:
        decision = DECISION_INSUFFICIENT
        parts = []
        if not gates["games"]:
            parts.append(f"{n} of {config.min_games} paired games")
        if not gates["days"]:
            parts.append(f"{days_live:.1f} of {config.min_days_live:g} days live")
        reason = "not enough evidence yet: " + ", ".join(parts)
    elif age_days > config.retire_age_days and n >= config.retire_age_min_games and not statistical_ok:
        decision = DECISION_RETIRE
        reason = (
            f"older than {config.retire_age_days:g} days ({age_days:.0f}) with {n} paired games and the promotion "
            f"gate not met (log-loss gain {_signed(log_loss_gain.mean)}, lower bound {_signed(log_loss_gain.bound_low)})"
        )
    elif statistical_ok and cooldown_ok:
        decision = DECISION_ROLLBACK if previous_champion else DECISION_PROMOTE
        market_text = (
            f"; market Brier gap difference {market.gap_difference:+.4f} within {config.market_max_worse:+.4f}"
            if gates["market"] is True
            else ""
        )
        reason = (
            f"log-loss gain {_signed(log_loss_gain.mean)} with lower bound {_signed(log_loss_gain.bound_low)} > 0 at "
            f"{pct} confidence over {n} paired games; margin NLL gain lower bound {_signed(nll_gain.bound_low)} > "
            f"{config.margin_nll_floor:+.2f}{market_text}"
        )
    else:
        decision = DECISION_KEEP
        failing = []
        if gates["log_loss"] is not True:
            failing.append(f"log-loss gain lower bound {_signed(log_loss_gain.bound_low)} is not above 0")
        if gates["margin_nll"] is not True:
            failing.append(
                f"margin NLL gain lower bound {_signed(nll_gain.bound_low)} is not above {config.margin_nll_floor:+.2f}"
            )
        if gates["market"] is False:
            failing.append(
                f"market Brier gap is {market.gap_difference:+.4f} worse than the champion's (limit {config.market_max_worse:+.4f})"
            )
        if statistical_ok and not cooldown_ok:
            failing.append(f"cooldown until {cooldown_until.date().isoformat()} ({config.cooldown_days:g} days between promotions)")
        reason = "; ".join(failing)

    return EvaluationResult(
        champion_id=data.champion_id,
        challenger_id=data.challenger_id,
        evaluated_at=_aware_utc(now),
        n_games=n,
        n_market_games=data.n_market,
        n_late_excluded=data.n_late_excluded,
        n_unpaired=data.n_unpaired,
        days_live=days_live,
        age_days=age_days,
        days_since_promotion=days_since_promotion,
        cooldown_until=cooldown_until,
        k=k,
        confidence=confidence,
        seed=seed,
        resamples=resamples,
        thresholds={
            key: value for key, value in asdict(config).items() if key not in ("seed", "resamples", "n_challengers")
        },
        previous_champion=previous_champion,
        evidence_since=data.since,
        champion=scores_champion,
        challenger=scores_challenger,
        log_loss_gain=log_loss_gain,
        brier_gain=brier_gain,
        margin_nll_gain=nll_gain,
        market=market,
        gates=gates,
        gate_text=gate_status(n, days_live, config, statistical_ok, gates, cooldown_until, decision),
        decision=decision,
        reason=reason,
    )


def gate_status(
    n: int,
    days_live: float,
    config: EvaluationConfig,
    statistical_ok: bool,
    gates: Dict[str, Optional[bool]],
    cooldown_until: Optional[datetime],
    decision: str,
) -> str:
    """Where the challenger stands against the promotion gate, in words."""
    if decision == DECISION_RETIRE:
        return "retirement criteria met"
    needs = []
    if n < config.min_games:
        needs.append(f"{config.min_games - n} more games")
    if days_live < config.min_days_live:
        needs.append(f"{math.ceil(config.min_days_live - days_live)} more days")
    if needs:
        return "needs " + " and ".join(needs)
    if not statistical_ok:
        if gates.get("log_loss") is not True:
            return "gate not passed: log-loss gain not significant"
        if gates.get("margin_nll") is not True:
            return "gate not passed: margin NLL significantly worse"
        return "gate not passed: worse than the champion against the market"
    if cooldown_until is not None:
        return f"cooldown until {cooldown_until.date().isoformat()}"
    return "gate passed"


# ----------------------------------------------------------------------------------------------- entry point

def default_config() -> EvaluationConfig:
    return EvaluationConfig.from_settings()


def count_active_challengers(session: Session) -> int:
    champion = model_registry.get_champion(session)
    return sum(
        1
        for row in model_registry.list_active(session)
        if row.role == MODEL_ROLE_CHALLENGER and (champion is None or row.id != champion.id)
    )


def evaluate_challenger(
    session: Session,
    challenger: ModelVersion,
    champion: ModelVersion,
    now: datetime,
    config: Optional[EvaluationConfig] = None,
    *,
    data: Optional[PairedData] = None,
) -> EvaluationResult:
    """
    Evaluate ``challenger`` against ``champion`` as of ``now`` (read-only). ``data`` lets a caller that already
    collected the paired games avoid a second query. A challenger that is the champion's parent is the previous
    champion: it is judged by the same rules and its success is a ``rollback``.
    """
    config = config or default_config()
    now = _aware_utc(now)
    data = data if data is not None else collect_for(session, champion, challenger)
    k = config.n_challengers if config.n_challengers is not None else count_active_challengers(session)

    days_live = 0.0
    if data.first_prediction_at is not None:
        days_live = max(0.0, (now - data.first_prediction_at).total_seconds() / _SECONDS_PER_DAY)
    previous_champion = is_previous_champion(champion, challenger)
    if previous_champion and champion.promoted_at is not None:
        # live as a challenger since the demotion, which is also the age that retirement counts
        days_live = max(0.0, (now - _aware_utc(champion.promoted_at)).total_seconds() / _SECONDS_PER_DAY)
    age_days = days_live
    days_since_promotion = None
    if champion.promoted_at is not None:
        days_since_promotion = max(0.0, (now - _aware_utc(champion.promoted_at)).total_seconds() / _SECONDS_PER_DAY)

    return evaluate_paired(
        data,
        now=now,
        days_live=days_live,
        age_days=age_days,
        days_since_promotion=days_since_promotion,
        k=k,
        config=config,
        previous_champion=previous_champion,
    )
