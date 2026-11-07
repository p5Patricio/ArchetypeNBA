"""
Paper-betting policy as pure functions (no DB, no I/O).

A model probability is never bet at face value: it is blended 50/50 with the sharp book's de-vigged probability,
because the model's disagreement with Pinnacle is mostly noise until a CLV record says otherwise. A side is
eligible only when the raw model edge over the fair probability is at least ``MIN_RAW_EDGE`` and the expected
value at the best available price, computed with the blended probability, is at least ``MIN_EV``.

Pushes are refunds: on a line that can push, ``p_cond`` is the probability of winning given no push
(p_win / (p_win + p_loss)), the same quantity a de-vigged two-way price estimates.

The `calibrated` strategy (``evaluate_calibrated``) replaces the fixed 50/50 linear blend with a logit blend whose
model weight is fitted on the champion's own settled record against Pinnacle (``fit_blend_weight``), and only bets
when the model is within ``MAX_DISAGREEMENT`` of the market. The functions above stay the v1 policy.

Stakes are in units; the bankroll starts at ``START_BANKROLL`` units. Flat staking risks one unit; fractional
Kelly risks ``KELLY_MULTIPLIER`` of the Kelly fraction. Both are clipped by a per-bet cap and by whatever room
is left under the daily and per-game exposure caps, and a stake under ``MIN_STAKE`` is not placed.
"""
import math
from dataclasses import dataclass
from typing import Optional, Sequence, Tuple

START_BANKROLL = 100.0
ALPHA = 0.5  # weight of the model in the blended probability
MIN_RAW_EDGE = 0.02  # model probability minus fair probability, same side
MIN_EV = 0.02  # expected profit per unit staked at the blended probability
FLAT_UNITS = 1.0
KELLY_MULTIPLIER = 0.25
KELLY_MULTIPLIER_SHRUNK_BASE = 0.5
MODEL_PROB_NOISE_SD = 0.05  # An ESTIMATE of the standard error of the model's win probability, to be calibrated from the model league, not a fact.
# --- `calibrated` strategy (see docs/QUANT_MODULE.md section 6) ---
W_MAX = 0.5  # upper end of the grid for the fitted weight of the model in the logit blend
W_STEP = 0.01  # grid resolution of the maximum-likelihood fit
MIN_CALIBRATION_GAMES = 100  # below this many calibration games the model gets weight 0 (no bets)
CALIBRATION_PRIOR_GAMES = 200  # shrinkage w_used = w_hat * n / (n + prior): trust grows only with evidence
MAX_DISAGREEMENT = 0.06  # |p_model - p_fair| above this is read as a model error (missing injuries), not an edge
PROB_CLIP = 1e-6  # probabilities are clipped to [PROB_CLIP, 1 - PROB_CLIP] before any logit
PER_BET_CAP = 0.02  # fraction of bankroll
DAILY_CAP = 0.10
GAME_CAP = 0.04
MIN_STAKE = 0.05

_EPS = 1e-9


@dataclass(frozen=True)
class BetDecision:
    eligible: bool
    reason: str  # "ok", "edge_below_min", "ev_below_min", "invalid_input" or, for `calibrated`, "no_model_weight" / "disagreement_too_large"
    p_cond: float  # model win probability given no push
    p_blend: float  # shrunk toward the fair probability
    raw_edge: float  # p_cond - p_fair
    ev: float  # per unit staked, with p_blend
    f_star: float  # full Kelly fraction with p_blend (0 when there is no edge)


def shrink_probability(p_model_cond: float, p_fair: float, alpha: float = ALPHA) -> float:
    return alpha * p_model_cond + (1.0 - alpha) * p_fair


def bet_ev(p_cond: float, p_push: float, decimal_price: float) -> float:
    """Expected profit per unit staked; a push returns the stake, so only the non-push mass counts."""
    return (1.0 - p_push) * (p_cond * decimal_price - 1.0)


def kelly_fraction(p_cond: float, p_push: float, decimal_price: float) -> float:
    """Full Kelly fraction of bankroll, floored at 0. f* = (b * p_win - p_lose) / b with b = price - 1."""
    b = decimal_price - 1.0
    if b <= 0:
        return 0.0
    p_win = p_cond * (1.0 - p_push)
    p_lose = (1.0 - p_cond) * (1.0 - p_push)
    return max(0.0, (b * p_win - p_lose) / b)


def flat_stake() -> float:
    return FLAT_UNITS


def daily_room(bankroll: float, staked_today: float, cap: float = DAILY_CAP) -> float:
    return max(0.0, cap * bankroll - staked_today)


def game_room(bankroll: float, staked_on_game: float, cap: float = GAME_CAP) -> float:
    return max(0.0, cap * bankroll - staked_on_game)


def cap_stake(
    stake: float,
    bankroll: float,
    per_bet_cap: float = PER_BET_CAP,
    daily_room: Optional[float] = None,
    game_room: Optional[float] = None,
) -> float:
    """Clips a stake by the per-bet cap and the remaining exposure rooms; 0 when under ``MIN_STAKE``."""
    capped = min(stake, per_bet_cap * bankroll)
    if daily_room is not None:
        capped = min(capped, daily_room)
    if game_room is not None:
        capped = min(capped, game_room)
    capped = round(max(0.0, capped), 3)
    return capped if capped >= MIN_STAKE - _EPS else 0.0


def kelly_stake(
    bankroll: float,
    f_star: float,
    multiplier: float = KELLY_MULTIPLIER,
    per_bet_cap: float = PER_BET_CAP,
    daily_room: Optional[float] = None,
    game_room: Optional[float] = None,
) -> float:
    """Fractional-Kelly stake in units after the per-bet, daily and per-game caps."""
    return cap_stake(bankroll * f_star * multiplier, bankroll, per_bet_cap, daily_room, game_room)


def shrink_factor(edge: float, noise_sd: float = MODEL_PROB_NOISE_SD) -> float:
    """
    Baker & McHale (2013) shrinkage factor for model parameter uncertainty:
    k = edge^2 / (edge^2 + noise_sd^2) clipped to [0, 1].
    Returns 0.0 if edge <= 0 or noise_sd <= 0.
    """
    if edge <= 0.0 or noise_sd <= 0.0:
        return 0.0
    k = (edge ** 2) / (edge ** 2 + noise_sd ** 2)
    return min(max(k, 0.0), 1.0)


def kelly_shrunk_stake(
    bankroll: float,
    f_star: float,
    edge: float = 0.0,
    noise_sd: float = MODEL_PROB_NOISE_SD,
    base_multiplier: float = KELLY_MULTIPLIER_SHRUNK_BASE,
    multiplier: Optional[float] = None,
    per_bet_cap: float = PER_BET_CAP,
    daily_room: Optional[float] = None,
    game_room: Optional[float] = None,
) -> float:
    """
    Kelly stake shrunk for model parameter uncertainty (Baker & McHale 2013).
    multiplier = base_multiplier * shrink_factor(edge, noise_sd) if multiplier is None.
    """
    if multiplier is None:
        multiplier = base_multiplier * shrink_factor(edge, noise_sd)
    return cap_stake(bankroll * f_star * multiplier, bankroll, per_bet_cap, daily_room, game_room)


def evaluate_market_edge(
    p_fair: float,
    decimal_price: float,
    min_ev: float = MIN_EV,
) -> BetDecision:
    """
    Evaluates taking decimal_price at Pinnacle's fair probability p_fair.
    No model probability is read or involved.
    """
    if p_fair <= 0.0 or p_fair >= 1.0 or decimal_price <= 1.0:
        return BetDecision(False, "invalid_input", 0.0, 0.0, 0.0, 0.0, 0.0)

    ev = bet_ev(p_fair, 0.0, decimal_price)
    f_star = kelly_fraction(p_fair, 0.0, decimal_price)

    if ev < min_ev - _EPS:
        return BetDecision(False, "ev_below_min", p_fair, p_fair, 0.0, ev, f_star)
    return BetDecision(True, "ok", p_fair, p_fair, 0.0, ev, f_star)


def evaluate_candidate(
    p_win: float,
    p_push: float,
    p_loss: float,
    p_fair: float,
    decimal_price: float,
    min_raw_edge: float = MIN_RAW_EDGE,
    min_ev: float = MIN_EV,
) -> BetDecision:
    """Decides whether one side at one price is a bet. ``p_fair`` is the sharp book's de-vigged probability."""
    live_mass = p_win + p_loss
    if live_mass <= 0 or decimal_price <= 1.0:
        return BetDecision(False, "invalid_input", 0.0, 0.0, 0.0, 0.0, 0.0)

    p_cond = p_win / live_mass
    raw_edge = p_cond - p_fair
    p_blend = shrink_probability(p_cond, p_fair)
    ev = bet_ev(p_blend, p_push, decimal_price)
    f_star = kelly_fraction(p_blend, p_push, decimal_price)

    if raw_edge < min_raw_edge - _EPS:
        return BetDecision(False, "edge_below_min", p_cond, p_blend, raw_edge, ev, f_star)
    if ev < min_ev - _EPS:
        return BetDecision(False, "ev_below_min", p_cond, p_blend, raw_edge, ev, f_star)
    return BetDecision(True, "ok", p_cond, p_blend, raw_edge, ev, f_star)



def _logit(p: float) -> float:
    p = min(max(p, PROB_CLIP), 1.0 - PROB_CLIP)
    return math.log(p / (1.0 - p))


def _sigmoid(x: float) -> float:
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    e = math.exp(x)
    return e / (1.0 + e)


def logit_blend(p_model: float, p_fair: float, w: float) -> float:
    """sigmoid(w * logit(p_model) + (1 - w) * logit(p_fair)); w is the weight of the model, 0 returns the market."""
    return _sigmoid(w * _logit(p_model) + (1.0 - w) * _logit(p_fair))


def blend_weight_grid() -> list:
    """The candidate weights 0.00 .. W_MAX in W_STEP steps."""
    steps = int(round(W_MAX / W_STEP))
    return [round(i * W_STEP, 10) for i in range(steps + 1)]


def fit_blend_weight(
    p_models: Sequence[float], p_fairs: Sequence[float], outcomes: Sequence[float]
) -> Tuple[float, float, int]:
    """
    Fits how much the model deserves in the logit blend with the market: ``(w_used, w_hat, n)``.

    ``w_hat`` maximizes the likelihood of the observed outcomes (1 = the side won) over the grid 0..W_MAX; ties go to
    the smaller weight. ``w_used`` is 0 until ``MIN_CALIBRATION_GAMES`` games exist, then ``w_hat`` shrunk by
    ``n / (n + CALIBRATION_PRIOR_GAMES)``.
    """
    n = len(outcomes)
    if len(p_models) != n or len(p_fairs) != n:
        raise ValueError("p_models, p_fairs and outcomes must have the same length")
    if n == 0:
        return 0.0, 0.0, 0
    logit_models = [_logit(p) for p in p_models]
    logit_fairs = [_logit(p) for p in p_fairs]
    best_w, best_ll = 0.0, -math.inf
    for w in blend_weight_grid():
        ll = 0.0
        for lm, lf, y in zip(logit_models, logit_fairs, outcomes):
            z = w * lm + (1.0 - w) * lf
            # log-likelihood of a Bernoulli outcome with logit z, numerically stable: y*z - log(1 + e^z)
            softplus = z + math.log1p(math.exp(-z)) if z > 0 else math.log1p(math.exp(z))
            ll += y * z - softplus
        if ll > best_ll + 1e-12:
            best_w, best_ll = w, ll
    w_used = 0.0 if n < MIN_CALIBRATION_GAMES else best_w * n / (n + CALIBRATION_PRIOR_GAMES)
    return w_used, best_w, n


def evaluate_calibrated(
    p_win: float,
    p_push: float,
    p_loss: float,
    p_fair: float,
    decimal_price: float,
    w: float,
    max_disagreement: float = MAX_DISAGREEMENT,
    min_ev: float = MIN_EV,
) -> BetDecision:
    """
    Decides whether one side at one price is a `calibrated` bet. The model is trusted only as far as ``w`` says
    (0 means never) and only when it is close enough to the sharp market that a disagreement is plausibly signal
    and not a missing-information error; the EV is computed with the logit blend at that weight.
    """
    live_mass = p_win + p_loss
    if live_mass <= 0 or decimal_price <= 1.0 or not 0.0 < p_fair < 1.0:
        return BetDecision(False, "invalid_input", 0.0, 0.0, 0.0, 0.0, 0.0)

    p_cond = p_win / live_mass
    raw_edge = p_cond - p_fair
    p_blend = logit_blend(p_cond, p_fair, w) if w > 0 else p_fair
    ev = bet_ev(p_blend, p_push, decimal_price)
    f_star = kelly_fraction(p_blend, p_push, decimal_price)

    if w <= 0:
        return BetDecision(False, "no_model_weight", p_cond, p_blend, raw_edge, ev, f_star)
    if abs(raw_edge) > max_disagreement + _EPS:
        return BetDecision(False, "disagreement_too_large", p_cond, p_blend, raw_edge, ev, f_star)
    if ev < min_ev - _EPS:
        return BetDecision(False, "ev_below_min", p_cond, p_blend, raw_edge, ev, f_star)
    return BetDecision(True, "ok", p_cond, p_blend, raw_edge, ev, f_star)
