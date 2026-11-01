"""
Availability and player impact analytics (pure maths, numpy only, no I/O).

Implements the player impact proxy, missing impact summation, Elo margin adjustment,
and walk-forward calibration functions.

Design:
1. Player Impact Proxy:
   Measures a player's expected margin contribution in points per game relative to a replacement-level player:
     impact = mpg * max(0.0, production_rate - replacement_rate)
   where production_rate = production_score / total_minutes.
   When full box score is available, production_score is Hollinger's Game Score:
     GmSc = pts + 0.4*fgm - 0.7*fga - 0.4*(fta - ftm) + 0.7*oreb + 0.3*dreb + 0.7*ast + stl + 0.7*blk - tov - 0.4*pf
   When only basic counts are available (e.g. synthetic league where fgm/fga are 0), fallback:
     GmSc = pts + 0.4*reb + 0.7*ast + stl + 0.7*blk - tov.
   If only pts is present, GmSc = pts.

2. Team Missing Impact:
   - Training proxy (actual absences):
     missing_impact = sum(impact_i for i in absent_rotation_players)
   - Serving (expected missing impact from injury report):
     expected_missing_impact = sum(impact_i * (1.0 - availability_prob_i) for i in team_players)

3. Margin Adjustment:
   - mu_adj = mu_elo + beta * (expected_missing_away - expected_missing_home)
     Sign convention:
       If away has missing impact (missing_away > missing_home), away is weakened, so home expected margin increases.
       If home has missing impact (missing_home > missing_away), home is weakened, so home expected margin decreases.
   - Win probability:
     p_home = Phi(mu_adj / sigma) under the continuous normal margin distribution M ~ N(mu_adj, sigma).

4. Calibration & Caveats:
   - Fit beta by OLS through origin: actual_margin - mu_elo ~ beta * (missing_away - missing_home).
   - Walk-forward evaluation reports log loss and Brier gains over Elo alone.
   - UPPER BOUND CAVEAT: Historical evaluation uses actual absences from player game logs (binary: played or didn't).
     Serving time uses expected absences from pre-game injury status probabilities, which are noisier (train/serve skew).
     The historical evaluation represents an upper bound on what live serving can achieve.
"""
import math
from typing import Any, Dict, Optional, Sequence, Tuple

import numpy as np

DEFAULT_ROTATION_MIN_MPG: float = 15.0
DEFAULT_ROTATION_MIN_GP: int = 5
DEFAULT_REPLACEMENT_RATE: float = 0.20  # ~7.2 GameScore per 36 minutes
_PROB_EPS: float = 1e-6


def compute_production_score(
    pts: float = 0.0,
    fgm: float = 0.0,
    fga: float = 0.0,
    ftm: float = 0.0,
    fta: float = 0.0,
    oreb: float = 0.0,
    dreb: float = 0.0,
    reb: float = 0.0,
    ast: float = 0.0,
    stl: float = 0.0,
    blk: float = 0.0,
    tov: float = 0.0,
    pf: float = 0.0,
) -> float:
    """
    Computes Hollinger's Game Score from box score stats, with graceful fallbacks
    for reduced box scores (e.g. synthetic test leagues).
    """
    if fga > 0.0 or fgm > 0.0:
        # Full box score available
        effective_oreb = oreb if (oreb > 0.0 or dreb > 0.0) else (0.5 * reb)
        effective_dreb = dreb if (oreb > 0.0 or dreb > 0.0) else (0.5 * reb)
        score = (
            pts
            + 0.4 * fgm
            - 0.7 * fga
            - 0.4 * (fta - ftm)
            + 0.7 * effective_oreb
            + 0.3 * effective_dreb
            + 0.7 * ast
            + stl
            + 0.7 * blk
            - tov
            - 0.4 * pf
        )
    elif reb > 0.0 or ast > 0.0 or stl > 0.0 or blk > 0.0 or tov > 0.0:
        # Basic counting stats available without shot attempts
        score = pts + 0.4 * reb + 0.7 * ast + stl + 0.7 * blk - tov
    else:
        # Only points available (e.g. minimal synthetic fixtures)
        score = float(pts)

    return float(score)


def compute_player_impact(
    mpg: float,
    production_per_minute: float,
    replacement_rate: float = DEFAULT_REPLACEMENT_RATE,
) -> float:
    """
    Computes a player's impact proxy in points of team margin per game relative to replacement level.
    """
    if mpg <= 0.0 or production_per_minute <= replacement_rate:
        return 0.0
    marginal_rate = production_per_minute - replacement_rate
    return float(mpg * marginal_rate)


def compute_team_missing_impact(missing_player_impacts: Sequence[float]) -> float:
    """Sum of impact of absent rotation players in points per game (training proxy)."""
    if not missing_player_impacts:
        return 0.0
    return float(np.sum(missing_player_impacts))


def compute_expected_missing_impact(
    impacts: Sequence[float],
    availability_probs: Sequence[float],
) -> float:
    """
    Expected missing impact from injury report at serving time:
      sum(impact_i * (1.0 - prob_i))
    """
    if not impacts or not availability_probs:
        return 0.0
    impacts_arr = np.asarray(impacts, dtype=float)
    probs_arr = np.clip(np.asarray(availability_probs, dtype=float), 0.0, 1.0)
    return float(np.sum(impacts_arr * (1.0 - probs_arr)))


def compute_adjusted_margin(
    elo_margin: float,
    missing_away: float,
    missing_home: float,
    beta: float,
) -> float:
    """
    mu_adj = mu_elo + beta * (missing_away - missing_home).

    Sign convention:
      - If away team has missing impact (missing_away > missing_home), away is weakened,
        so home team's expected margin increases (+).
      - If home team has missing impact (missing_home > missing_away), home is weakened,
        so home team's expected margin decreases (-).
    """
    return float(elo_margin + beta * (missing_away - missing_home))


def normal_win_prob(mu: float, sigma: float) -> float:
    """
    Win probability P(M > 0) under normal margin distribution M ~ N(mu, sigma):
      Phi(mu / sigma) = 0.5 * (1 + erf(mu / (sigma * sqrt(2))))
    """
    if sigma <= 0.0:
        raise ValueError("sigma must be positive")
    z = mu / (sigma * math.sqrt(2.0))
    return float(0.5 * (1.0 + math.erf(z)))


def fit_beta(x: np.ndarray, y: np.ndarray) -> float:
    """
    Fits coefficient beta of y ~ beta * x through origin via OLS.
      beta = sum(x * y) / sum(x^2)
    """
    x_arr = np.asarray(x, dtype=float)
    y_arr = np.asarray(y, dtype=float)
    denom = float(np.sum(x_arr**2))
    if denom <= 0.0:
        return 0.0
    numer = float(np.sum(x_arr * y_arr))
    return float(numer / denom)


def bootstrap_beta_ci(
    x: np.ndarray,
    y: np.ndarray,
    n_boot: int = 2000,
    seed: int = 42,
    alpha: float = 0.05,
) -> Tuple[float, float]:
    """Computes a paired bootstrap percentile confidence interval for beta."""
    x_arr = np.asarray(x, dtype=float)
    y_arr = np.asarray(y, dtype=float)
    n = len(x_arr)
    if n < 5:
        b = fit_beta(x_arr, y_arr)
        return (b, b)
    rng = np.random.RandomState(seed)
    betas = np.empty(n_boot, dtype=float)
    indices = np.arange(n)
    for i in range(n_boot):
        sample_idx = rng.choice(indices, size=n, replace=True)
        betas[i] = fit_beta(x_arr[sample_idx], y_arr[sample_idx])
    low = float(np.percentile(betas, 100.0 * (alpha / 2.0)))
    high = float(np.percentile(betas, 100.0 * (1.0 - alpha / 2.0)))
    return (low, high)


def compute_gains(
    p_baseline: np.ndarray,
    p_adjusted: np.ndarray,
    y_actual: np.ndarray,
) -> Dict[str, Any]:
    """
    Computes per-game and aggregate log loss and Brier gains:
      gain = baseline - adjusted (positive means adjusted is better).
    """
    y = np.asarray(y_actual, dtype=float)
    p_base = np.clip(np.asarray(p_baseline, dtype=float), _PROB_EPS, 1.0 - _PROB_EPS)
    p_adj = np.clip(np.asarray(p_adjusted, dtype=float), _PROB_EPS, 1.0 - _PROB_EPS)

    loss_base = -(y * np.log(p_base) + (1.0 - y) * np.log(1.0 - p_base))
    loss_adj = -(y * np.log(p_adj) + (1.0 - y) * np.log(1.0 - p_adj))
    ll_gain = float(np.mean(loss_base - loss_adj))

    brier_base = (p_base - y) ** 2
    brier_adj = (p_adj - y) ** 2
    brier_gain = float(np.mean(brier_base - brier_adj))

    return {
        "log_loss_gain": ll_gain,
        "brier_gain": brier_gain,
        "loss_baseline": loss_base,
        "loss_adjusted": loss_adj,
        "brier_baseline": brier_base,
        "brier_adjusted": brier_adj,
        "mean_loss_baseline": float(np.mean(loss_base)),
        "mean_loss_adjusted": float(np.mean(loss_adj)),
        "mean_brier_baseline": float(np.mean(brier_base)),
        "mean_brier_adjusted": float(np.mean(brier_adj)),
    }


def bootstrap_gain_ci(
    loss_base: np.ndarray,
    loss_adj: np.ndarray,
    n_boot: int = 2000,
    seed: int = 42,
    alpha: float = 0.05,
) -> Tuple[float, float]:
    """Computes paired percentile bootstrap confidence interval for metric gain (base - adj)."""
    diff = np.asarray(loss_base, dtype=float) - np.asarray(loss_adj, dtype=float)
    n = len(diff)
    if n < 5:
        m = float(np.mean(diff)) if n > 0 else 0.0
        return (m, m)
    rng = np.random.RandomState(seed)
    boot_means = np.empty(n_boot, dtype=float)
    for i in range(n_boot):
        sample = rng.choice(diff, size=n, replace=True)
        boot_means[i] = np.mean(sample)
    low = float(np.percentile(boot_means, 100.0 * (alpha / 2.0)))
    high = float(np.percentile(boot_means, 100.0 * (1.0 - alpha / 2.0)))
    return (low, high)
