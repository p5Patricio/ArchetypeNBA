"""Tests for app.analytics.availability: pure mathematical functions for player impact, missing impact, and margin adjustment."""
import math
import numpy as np
import pytest

from app.analytics.availability import (
    DEFAULT_REPLACEMENT_RATE,
    DEFAULT_ROTATION_MIN_MPG,
    bootstrap_beta_ci,
    bootstrap_gain_ci,
    compute_adjusted_margin,
    compute_expected_missing_impact,
    compute_gains,
    compute_player_impact,
    compute_production_score,
    compute_team_missing_impact,
    fit_beta,
    normal_win_prob,
)


def test_hand_computed_tiny_example():
    """Verify player impact, expected missing impact, adjusted margin, and normal win prob on exact hand math."""
    # 1. Production score
    # pts=200, fgm=70, fga=150, ftm=40, fta=50, oreb=15, dreb=35, ast=50, stl=10, blk=10, tov=20, pf=20
    # GmSc = 200 + 28 - 105 - 4 + 10.5 + 10.5 + 35 + 10 + 7 - 20 - 8 = 164.0
    score = compute_production_score(
        pts=200, fgm=70, fga=150, ftm=40, fta=50, oreb=15, dreb=35, ast=50, stl=10, blk=10, tov=20, pf=20
    )
    assert abs(score - 164.0) < 1e-9

    # 2. Player impact: 10 games, 300 minutes (mpg = 30.0)
    # r = 164 / 300 = 0.546666...
    # marginal_rate = 0.546666... - 0.20 = 0.346666...
    # impact = 30.0 * 0.346666... = 10.4
    impact = compute_player_impact(
        mpg=30.0,
        production_per_minute=score / 300.0,
        replacement_rate=0.20,
    )
    assert abs(impact - 10.4) < 1e-9

    # 3. Serving expected missing impact: Away player is OUT (prob=0.0)
    exp_missing_away = compute_expected_missing_impact([impact], [0.0])
    assert abs(exp_missing_away - 10.4) < 1e-9

    exp_missing_home = compute_expected_missing_impact([], [])
    assert exp_missing_home == 0.0

    # 4. Adjusted margin with beta = 0.5, mu_elo = 2.0
    # mu_adj = 2.0 + 0.5 * (10.4 - 0.0) = 7.2
    mu_adj = compute_adjusted_margin(
        elo_margin=2.0,
        missing_away=exp_missing_away,
        missing_home=exp_missing_home,
        beta=0.5,
    )
    assert abs(mu_adj - 7.2) < 1e-9

    # 5. Normal win prob: sigma = 14.14
    # z = 7.2 / 14.14 = 0.5091937765
    # Phi(z) = 0.5 * (1 + erf(z / sqrt(2)))
    p_home = normal_win_prob(mu_adj, sigma=14.14)
    expected_p = 0.5 * (1.0 + math.erf((7.2 / 14.14) / math.sqrt(2.0)))
    assert abs(p_home - expected_p) < 1e-9
    assert 0.69 < p_home < 0.70


def test_replacement_level_player_has_zero_impact():
    """A player with production at or below replacement level contributes 0 impact."""
    impact_zero = compute_player_impact(mpg=25.0, production_per_minute=0.20, replacement_rate=0.20)
    assert impact_zero == 0.0

    impact_negative = compute_player_impact(mpg=25.0, production_per_minute=0.10, replacement_rate=0.20)
    assert impact_negative == 0.0


def test_zero_minutes_player_has_zero_impact():
    impact = compute_player_impact(mpg=0.0, production_per_minute=1.0, replacement_rate=0.20)
    assert impact == 0.0


def test_production_score_fallback_when_only_points_available():
    """In synthetic or simplified logs, only points may be non-zero."""
    score = compute_production_score(pts=25.0)
    assert score == 25.0

    # With basic box score columns
    score2 = compute_production_score(pts=20.0, reb=10.0, ast=5.0, stl=2.0, blk=1.0, tov=3.0)
    # GmSc fallback: 20 + 0.4*10 + 0.7*5 + 2 + 0.7*1 - 3 = 20 + 4 + 3.5 + 2 + 0.7 - 3 = 27.2
    assert abs(score2 - 27.2) < 1e-9


def test_sign_convention_documented():
    """Home player missing lowers home margin; away player missing raises home margin."""
    elo_margin = 0.0
    beta = 0.4
    # Home player absent (10 pts impact)
    mu_home_out = compute_adjusted_margin(elo_margin, missing_away=0.0, missing_home=10.0, beta=beta)
    assert mu_home_out == -4.0

    # Away player absent (10 pts impact)
    mu_away_out = compute_adjusted_margin(elo_margin, missing_away=10.0, missing_home=0.0, beta=beta)
    assert mu_away_out == 4.0

    # Both absent equally
    mu_both_out = compute_adjusted_margin(elo_margin, missing_away=10.0, missing_home=10.0, beta=beta)
    assert mu_both_out == 0.0


def test_fit_beta_and_bootstrap():
    """Fitting beta on synthetic x and y ~ beta*x recovers beta and valid CI."""
    rng = np.random.RandomState(42)
    x = rng.uniform(-10.0, 10.0, size=200)
    true_beta = 0.45
    y = true_beta * x + rng.normal(0.0, 2.0, size=200)

    fitted = fit_beta(x, y)
    assert abs(fitted - true_beta) < 0.05

    ci_low, ci_high = bootstrap_beta_ci(x, y, n_boot=500, seed=42)
    assert ci_low < fitted < ci_high
    assert ci_low > 0.35
    assert ci_high < 0.55


def test_fit_beta_zero_variance():
    x = np.zeros(50)
    y = np.ones(50)
    assert fit_beta(x, y) == 0.0


def test_compute_gains_and_bootstrap():
    """Positive gain when adjusted model has better predictions than baseline."""
    rng = np.random.RandomState(123)
    y_actual = rng.choice([0.0, 1.0], size=100)
    # Adjusted is closer to y_actual than baseline with variance
    p_baseline = np.full(100, 0.5)
    noise = rng.uniform(-0.1, 0.1, size=100)
    p_adjusted = np.clip(np.where(y_actual == 1.0, 0.75 + noise, 0.25 + noise), 0.05, 0.95)

    gains = compute_gains(p_baseline, p_adjusted, y_actual)
    assert gains["log_loss_gain"] > 0
    assert gains["brier_gain"] > 0

    ci_low, ci_high = bootstrap_gain_ci(gains["loss_baseline"], gains["loss_adjusted"], n_boot=500, seed=42)
    assert ci_low > 0
    assert ci_high > ci_low
