"""
Paper-betting policy as pure functions (no DB, no I/O).

A model probability is never bet at face value: it is blended 50/50 with the sharp book's de-vigged probability,
because the model's disagreement with Pinnacle is mostly noise until a CLV record says otherwise. A side is
eligible only when the raw model edge over the fair probability is at least ``MIN_RAW_EDGE`` and the expected
value at the best available price, computed with the blended probability, is at least ``MIN_EV``.

Pushes are refunds: on a line that can push, ``p_cond`` is the probability of winning given no push
(p_win / (p_win + p_loss)), the same quantity a de-vigged two-way price estimates.

Stakes are in units; the bankroll starts at ``START_BANKROLL`` units. Flat staking risks one unit; fractional
Kelly risks ``KELLY_MULTIPLIER`` of the Kelly fraction. Both are clipped by a per-bet cap and by whatever room
is left under the daily and per-game exposure caps, and a stake under ``MIN_STAKE`` is not placed.
"""
from dataclasses import dataclass
from typing import Optional

START_BANKROLL = 100.0
ALPHA = 0.5  # weight of the model in the blended probability
MIN_RAW_EDGE = 0.02  # model probability minus fair probability, same side
MIN_EV = 0.02  # expected profit per unit staked at the blended probability
FLAT_UNITS = 1.0
KELLY_MULTIPLIER = 0.25
PER_BET_CAP = 0.02  # fraction of bankroll
DAILY_CAP = 0.10
GAME_CAP = 0.04
MIN_STAKE = 0.05

_EPS = 1e-9


@dataclass(frozen=True)
class BetDecision:
    eligible: bool
    reason: str  # "ok", "edge_below_min", "ev_below_min" or "invalid_input"
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
