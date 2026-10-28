"""
Multiple-comparison control and paired forecast evaluation (pure functions, numpy only, seeded).

Implements:
1. White's Reality Check (White 2000, Econometrica):
   Tests whether any of K candidate models outperforms a benchmark model under data snooping.
   The observed statistic is:
       T_RC = max_{k=1..K} d_bar_k
   where d_bar_k is the sample mean loss differential for candidate k (positive = candidate better).
   Under the least favorable configuration of the null hypothesis H_0: max_k E[d_k] <= 0 with E[d_k] = 0,
   paired bootstrap resamples d^{*b} are recentered by the full sample mean:
       Z_k^{*b} = d_bar_k^{*b} - d_bar_k
       T_RC^{*b} = max_{k=1..K} Z_k^{*b}
   The p-value is the fraction of resamples where T_RC^{*b} >= T_RC.

2. Hansen's Superior Predictive Ability (SPA) test (Hansen 2005, JBES):
   Improves on White's Reality Check by studentizing each candidate by its standard error
   and recentering only over non-clearly-inferior candidates to preserve statistical power.
   The studentized statistic is:
       t_k = d_bar_k / se(d_bar_k)
       T_SPA = max_{k=1..K} t_k
   Hansen's consistent recentering estimator uses the threshold A_N = sqrt(2 * ln(ln(N))):
       mu_k = d_bar_k  if t_k >= -A_N  else 0.0
   The studentized bootstrap statistic is:
       t_k^{*b} = (d_bar_k^{*b} - mu_k) / se(d_bar_k)
       T_SPA^{*b} = max_{k=1..K} t_k^{*b}
   The p-value is the fraction of resamples where T_SPA^{*b} >= T_SPA.

3. Diebold-Mariano test with Harvey-Leybourne-Newbold correction (HLN 1997, IJF):
   Paired test of equal predictive accuracy for h-step-ahead forecasts.
   For mean differential d_bar and Diebold-Mariano long-run variance V_hat:
       DM = d_bar / sqrt(V_hat / n)
   HLN modifies DM by a small-sample correction factor:
       k_HLN = sqrt((n + 1 - 2*h + n^(-1)*h*(h - 1)) / n)
       DM_HLN = DM * k_HLN
   and compares DM_HLN to a Student-t distribution with (n - 1) degrees of freedom.
"""
import math
from dataclasses import dataclass
from typing import NamedTuple, Optional, Sequence, Tuple

import numpy as np

BOOTSTRAP_CHUNK = 250
MIN_N = 3


class DMTestResult(NamedTuple):
    """Result of a Diebold-Mariano test with HLN small-sample correction."""

    statistic: float
    p_value: float


# --------------------------------------------------------------------------------- Student-t helpers


def _betainc(a: float, b: float, x: float, max_iter: int = 200, eps: float = 1e-15) -> float:
    """
    Regularized incomplete beta function I_x(a, b) via Lentz's continued fraction method.
    Pure Python/math implementation to avoid external dependencies.
    """
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0

    lbeta = math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)
    front = math.exp(a * math.log(x) + b * math.log(1.0 - x) - lbeta) / a

    c = 1.0
    d = 1.0 - (a + b) * x / (a + 1.0)
    if abs(d) < 1e-30:
        d = 1e-30
    d = 1.0 / d
    f = d

    for m in range(1, max_iter):
        # Even step 2*m
        num = m * (b - m) * x / ((a + 2 * m - 1) * (a + 2 * m))
        d = 1.0 + num * d
        if abs(d) < 1e-30:
            d = 1e-30
        c = 1.0 + num / c
        if abs(c) < 1e-30:
            c = 1e-30
        d = 1.0 / d
        f *= c * d

        # Odd step 2*m + 1
        num = -(a + m) * (a + b + m) * x / ((a + 2 * m) * (a + 2 * m + 1))
        d = 1.0 + num * d
        if abs(d) < 1e-30:
            d = 1e-30
        c = 1.0 + num / c
        if abs(c) < 1e-30:
            c = 1e-30
        d = 1.0 / d
        delta = c * d
        f *= delta
        if abs(delta - 1.0) < eps:
            break

    return front * f


def _student_t_sf(x: float, df: float) -> float:
    """Survival function P(T >= x) for a Student-t random variable with df degrees of freedom."""
    if x == 0.0:
        return 0.5
    if x < 0.0:
        return 1.0 - _student_t_sf(-x, df)
    w = df / (df + x * x)
    return 0.5 * _betainc(df / 2.0, 0.5, w)


# --------------------------------------------------------------------------------------- DM-HLN test


def dm_hln_test(d: Sequence[float] | np.ndarray, h: int = 1) -> Optional[DMTestResult]:
    """
    Diebold-Mariano test with Harvey, Leybourne, and Newbold (1997) small-sample correction.

    Parameters
    ----------
    d : array_like of shape (n,)
        Per-period forecast loss differentials (baseline loss minus candidate loss;
        positive = candidate better).
    h : int, default 1
        Forecast horizon in periods. For h=1, errors are assumed serially uncorrelated.

    Returns
    -------
    DMTestResult(statistic, p_value) or None
        statistic: HLN-corrected DM statistic.
        p_value: two-sided p-value referenced to Student-t(n - 1).
        Returns None if n < 3 or n <= h.
    """
    arr = np.asarray(d, dtype=float).ravel()
    n = len(arr)
    if n < MIN_N or n <= h or h < 1:
        return None

    d_bar = float(np.mean(arr))
    z = arr - d_bar
    gamma0 = float(np.mean(z**2))

    if gamma0 < 1e-15:
        return DMTestResult(statistic=0.0, p_value=1.0) if d_bar == 0.0 else None

    var = gamma0
    for k in range(1, h):
        gamma_k = float(np.mean(z[k:] * z[:-k]))
        var += 2.0 * gamma_k

    if var <= 0.0:
        var = gamma0

    dm = d_bar / math.sqrt(var / n)
    hln_factor = math.sqrt(max(0.0, (n + 1 - 2 * h + (h * (h - 1)) / n) / n))
    stat = dm * hln_factor
    p = 2.0 * _student_t_sf(abs(stat), float(n - 1))
    return DMTestResult(statistic=float(stat), p_value=float(min(max(p, 0.0), 1.0)))


# ----------------------------------------------------------------------------------- paired bootstrap


def _paired_bootstrap_means(
    matrix: np.ndarray,
    n_boot: int,
    seed: int,
    block_length: Optional[int] = None,
    chunk_size: int = BOOTSTRAP_CHUNK,
) -> np.ndarray:
    """
    Paired bootstrap means across K candidates.
    If block_length is given (> 1), uses circular block bootstrap to account for serial dependence.
    Otherwise uses paired i.i.d. resampling.
    """
    N, K = matrix.shape
    rng = np.random.default_rng(seed)
    means = []
    L = None if block_length is None else max(1, min(int(block_length), N))

    for start in range(0, n_boot, chunk_size):
        size = min(chunk_size, n_boot - start)
        if L is None or L <= 1:
            idx = rng.integers(0, N, size=(size, N))
        else:
            n_blocks = int(math.ceil(N / L))
            starts = rng.integers(0, N, size=(size, n_blocks))
            offsets = np.arange(L)
            block_idx = (starts[:, :, None] + offsets[None, None, :]) % N
            idx = block_idx.reshape(size, -1)[:, :N]
        means.append(matrix[idx].mean(axis=1))

    return np.concatenate(means, axis=0)


# ----------------------------------------------------------------------------- Reality Check & SPA


def reality_check_pvalue(
    loss_diffs_matrix: np.ndarray | Sequence[Sequence[float]],
    n_boot: int = 2000,
    seed: int = 42,
    block_length: Optional[int] = None,
) -> Optional[float]:
    """
    White's Reality Check (White 2000) p-value for testing H_0: max_k E[d_k] <= 0.

    Parameters
    ----------
    loss_diffs_matrix : array_like of shape (N, K)
        Per-game loss differentials: baseline loss minus candidate k loss (positive = candidate better).
    n_boot : int, default 2000
        Number of paired bootstrap replications.
    seed : int, default 42
        RNG seed for reproducibility.
    block_length : int, optional
        Block length for circular block bootstrap. If None, i.i.d. paired bootstrap is used.

    Returns
    -------
    float or None
        P-value in [0, 1], or None if N < 3 or K < 1.
    """
    mat = np.asarray(loss_diffs_matrix, dtype=float)
    if mat.ndim == 1:
        mat = mat[:, None]
    if mat.ndim != 2:
        return None
    N, K = mat.shape
    if N < MIN_N or K < 1:
        return None

    d_bar = mat.mean(axis=0)
    t_rc = float(np.max(d_bar))

    boot_means = _paired_bootstrap_means(mat, n_boot=n_boot, seed=seed, block_length=block_length)
    boot_centered = boot_means - d_bar
    t_boot = np.max(boot_centered, axis=1)

    p_val = float(np.mean(t_boot >= t_rc))
    return float(np.clip(p_val, 0.0, 1.0))


def spa_pvalue(
    loss_diffs_matrix: np.ndarray | Sequence[Sequence[float]],
    n_boot: int = 2000,
    seed: int = 42,
    block_length: Optional[int] = None,
) -> Optional[float]:
    """
    Hansen's Superior Predictive Ability (SPA) test (Hansen 2005) p-value.
    Uses studentized test statistic and consistent recentering over non-clearly-inferior models.

    Parameters
    ----------
    loss_diffs_matrix : array_like of shape (N, K)
        Per-game loss differentials: baseline loss minus candidate k loss (positive = candidate better).
    n_boot : int, default 2000
        Number of paired bootstrap replications.
    seed : int, default 42
        RNG seed for reproducibility.
    block_length : int, optional
        Block length for circular block bootstrap. If None, i.i.d. paired bootstrap is used.

    Returns
    -------
    float or None
        P-value in [0, 1], or None if N < 3 or K < 1.
    """
    mat = np.asarray(loss_diffs_matrix, dtype=float)
    if mat.ndim == 1:
        mat = mat[:, None]
    if mat.ndim != 2:
        return None
    N, K = mat.shape
    if N < MIN_N or K < 1:
        return None

    d_bar = mat.mean(axis=0)
    var = np.mean((mat - d_bar) ** 2, axis=0)
    se = np.maximum(np.sqrt(var) / math.sqrt(N), 1e-12)
    t = d_bar / se
    t_spa = float(np.max(t))

    # Hansen's threshold A_N for identifying non-clearly-inferior candidates
    # For N >= 3, log(log(N)) > 0
    an = math.sqrt(2.0 * math.log(max(math.log(N), 1e-9)))
    mu = np.where(t >= -an, d_bar, 0.0)

    boot_means = _paired_bootstrap_means(mat, n_boot=n_boot, seed=seed, block_length=block_length)
    boot_t = (boot_means - mu) / se
    t_boot = np.max(boot_t, axis=1)

    p_val = float(np.mean(t_boot >= t_spa))
    return float(np.clip(p_val, 0.0, 1.0))
