"""
Tests for multiple-comparison control: White's Reality Check, Hansen's SPA, and Diebold-Mariano with HLN.
"""
import numpy as np
import pytest

from app.analytics import multiple_testing as mt


def test_dm_hln_test_on_planted_signal():
    rng = np.random.default_rng(10)
    # Planted signal: candidate is consistently better (positive loss differential)
    d = rng.normal(loc=0.5, scale=1.0, size=200)
    res = mt.dm_hln_test(d, h=1)
    assert res is not None
    stat, p = res
    assert stat > 0.0
    assert p < 0.001
    assert res.statistic == stat and res.p_value == p


def test_dm_hln_test_under_null():
    # Under null (mean 0), p-values across 50 seeds should not over-reject at alpha=0.05
    rng = np.random.default_rng(42)
    p_values = []
    for _ in range(50):
        d = rng.normal(loc=0.0, scale=1.0, size=150)
        res = mt.dm_hln_test(d, h=1)
        assert res is not None
        p_values.append(res.p_value)

    rejections = sum(p < 0.05 for p in p_values)
    assert rejections <= 6  # ~5% expected out of 50


def test_dm_hln_test_tiny_n_and_edge_cases():
    assert mt.dm_hln_test([], h=1) is None
    assert mt.dm_hln_test([0.5], h=1) is None
    assert mt.dm_hln_test([0.5, 0.2], h=1) is None
    # Constant 0 differences
    res = mt.dm_hln_test([0.0, 0.0, 0.0, 0.0], h=1)
    assert res is not None
    assert res.statistic == 0.0 and res.p_value == 1.0


def test_reality_check_and_spa_planted_signal():
    rng = np.random.default_rng(7)
    # 200 games x 10 candidates; candidate 0 has real positive gain
    diffs = rng.normal(loc=0.0, scale=1.0, size=(200, 10))
    diffs[:, 0] += 0.45

    p_rc = mt.reality_check_pvalue(diffs, n_boot=400, seed=42)
    p_spa = mt.spa_pvalue(diffs, n_boot=400, seed=42)

    assert p_rc is not None and p_spa is not None
    assert p_rc < 0.02
    assert p_spa < 0.02


def test_reality_check_and_spa_under_null():
    # Under null across 40 seeds, neither should significantly over-reject at 5%
    rejections_rc = 0
    rejections_spa = 0
    for seed in range(40):
        rng = np.random.default_rng(seed)
        diffs = rng.normal(loc=0.0, scale=1.0, size=(150, 5))
        p_rc = mt.reality_check_pvalue(diffs, n_boot=200, seed=seed)
        p_spa = mt.spa_pvalue(diffs, n_boot=200, seed=seed)
        assert p_rc is not None and p_spa is not None
        if p_rc < 0.05:
            rejections_rc += 1
        if p_spa < 0.05:
            rejections_spa += 1

    assert rejections_rc <= 5
    assert rejections_spa <= 5


def test_spa_ignores_clearly_inferior_candidates():
    # 1 candidate with modest signal, 15 clearly inferior candidates (mean -3.0)
    rng = np.random.default_rng(99)
    N = 250
    diffs = np.empty((N, 16))
    diffs[:, 0] = rng.normal(0.15, 1.0, size=N)  # mild positive
    for k in range(1, 16):
        diffs[:, k] = rng.normal(-3.0, 1.0, size=N)  # clearly inferior

    p_rc = mt.reality_check_pvalue(diffs, n_boot=400, seed=123)
    p_spa = mt.spa_pvalue(diffs, n_boot=400, seed=123)

    assert p_rc is not None and p_spa is not None
    # Hansen's SPA recenters only non-clearly-inferior candidates, so it maintains power
    # while White's RC recenters all 15 bad models at 0, inflating the bootstrap max
    assert p_spa <= p_rc


def test_reproducibility_with_seed():
    rng = np.random.default_rng(21)
    diffs = rng.normal(0.05, 1.0, size=(100, 4))

    rc1 = mt.reality_check_pvalue(diffs, n_boot=250, seed=77)
    rc2 = mt.reality_check_pvalue(diffs, n_boot=250, seed=77)
    rc3 = mt.reality_check_pvalue(diffs, n_boot=250, seed=78)

    assert rc1 == rc2
    assert rc1 != rc3

    spa1 = mt.spa_pvalue(diffs, n_boot=250, seed=77)
    spa2 = mt.spa_pvalue(diffs, n_boot=250, seed=77)
    assert spa1 == spa2


def test_block_length_bootstrap():
    rng = np.random.default_rng(33)
    diffs = rng.normal(0.02, 1.0, size=(120, 3))

    p_rc_block = mt.reality_check_pvalue(diffs, n_boot=200, seed=5, block_length=6)
    p_spa_block = mt.spa_pvalue(diffs, n_boot=200, seed=5, block_length=6)

    assert p_rc_block is not None and 0.0 <= p_rc_block <= 1.0
    assert p_spa_block is not None and 0.0 <= p_spa_block <= 1.0

    # Reproducible with same block_length and seed
    assert mt.reality_check_pvalue(diffs, n_boot=200, seed=5, block_length=6) == p_rc_block


def test_tiny_sample_returns_none():
    assert mt.reality_check_pvalue(np.empty((0, 2))) is None
    assert mt.reality_check_pvalue(np.ones((2, 2))) is None
    assert mt.reality_check_pvalue(np.ones((5, 0))) is None

    assert mt.spa_pvalue(np.empty((0, 2))) is None
    assert mt.spa_pvalue(np.ones((2, 2))) is None
    assert mt.spa_pvalue(np.ones((5, 0))) is None
