"""
FiveThirtyEight-style NBA Elo, as pure functions (no DB, no I/O).

Rating update after a game, with ``diff`` = home rating + home advantage - away rating:

    p_home = 1 / (1 + 10 ** (-diff / 400))
    delta  = K * mov_multiplier(margin, winner_diff) * (S_home - p_home)

``S_home`` is 1 for a home win and 0 for a loss; the update is zero-sum. Between seasons every rating
is pulled a quarter of the way back to the league mean (``season_carryover``). A rating gap converts to
an expected point margin at ELO_PER_POINT Elo points per point, and ``spread_probabilities`` turns that
margin into win / push / loss probabilities for a spread line using a discrete (integer) normal.
"""
import math
from typing import Tuple

K = 20.0
# FiveThirtyEight used 100. Walk-forward residuals on the last five completed seasons show the modern
# home edge is smaller (bias of 1.2-1.9 points at 100, ~0 at 60), so 60 is used. Tuned in-sample on
# 2021-22..2025-26: treat the reported Brier as slightly optimistic.
HOME_ADVANTAGE = 60.0
INITIAL_RATING = 1500.0
MEAN_RATING = 1505.0
CARRYOVER = 0.75
ELO_PER_POINT = 28.0

_ROUND_EPS = 1e-9


def expected_home_win_prob(r_home: float, r_away: float, home_advantage: float = HOME_ADVANTAGE) -> float:
    diff = r_home + home_advantage - r_away
    return 1.0 / (1.0 + 10.0 ** (-diff / 400.0))


def mov_multiplier(margin: float, elo_diff_winner: float) -> float:
    """Margin-of-victory multiplier. ``elo_diff_winner`` = winner rating - loser rating (home edge included)."""
    return ((abs(margin) + 3.0) ** 0.8) / (7.5 + 0.006 * elo_diff_winner)


def update_ratings(
    r_home: float,
    r_away: float,
    home_pts: float,
    away_pts: float,
    k: float = K,
    home_advantage: float = HOME_ADVANTAGE,
) -> Tuple[float, float, float]:
    """Return (new_home, new_away, p_home) where p_home is the pre-game home win probability."""
    diff = r_home + home_advantage - r_away
    p_home = 1.0 / (1.0 + 10.0 ** (-diff / 400.0))
    margin = home_pts - away_pts
    if margin > 0:
        score, winner_diff = 1.0, diff
    elif margin < 0:
        score, winner_diff = 0.0, -diff
    else:  # the NBA has no ties; keep the update well-defined (and zero-sum) anyway
        score, winner_diff = 0.5, 0.0
    delta = k * mov_multiplier(margin, winner_diff) * (score - p_home)
    return r_home + delta, r_away - delta, p_home


def season_carryover(rating: float) -> float:
    return CARRYOVER * rating + (1.0 - CARRYOVER) * MEAN_RATING


def expected_margin(r_home: float, r_away: float, home_advantage: float = HOME_ADVANTAGE) -> float:
    """Expected home margin in points (positive = home favoured)."""
    return (r_home + home_advantage - r_away) / ELO_PER_POINT


def _normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def spread_probabilities(mu: float, sigma: float, home_line: float) -> Tuple[float, float, float]:
    """
    (p_home_win, p_push, p_away_win) for the home side at spread ``home_line``.

    The home margin M is integer-valued, approximated by N(mu, sigma) with a continuity correction.
    Home covers when M + home_line > 0, so a line of -4.5 needs M >= 5 and a line of -5 pushes at M == 5.
    """
    if sigma <= 0:
        raise ValueError("sigma must be positive")
    threshold = -home_line  # home covers when M > threshold
    floor = math.floor(threshold + _ROUND_EPS)
    if abs(threshold - floor) < _ROUND_EPS:  # integer line: M == threshold is a push
        away = _normal_cdf((floor - 0.5 - mu) / sigma)
        upto_push = _normal_cdf((floor + 0.5 - mu) / sigma)
        return 1.0 - upto_push, upto_push - away, away
    boundary = math.floor(threshold) + 0.5  # M >= floor(t)+1
    away = _normal_cdf((boundary - mu) / sigma)
    return 1.0 - away, 0.0, away
