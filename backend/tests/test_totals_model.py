from dataclasses import replace
from datetime import date, timedelta
import math

import numpy as np
import pytest

from app.analytics.totals_model import (
    DEFAULT_LEAGUE_TOTAL,
    DEFAULT_SIGMA,
    TotalsParams,
    TotalsState,
    build_totals_feature_set,
    p_over,
    p_under,
)
from tests.synthetic_league import make_league


def test_p_over_and_p_under_basic_properties():
    mu = 220.0
    sigma = 15.0

    # Line at mean
    assert p_over(220.0, mu, sigma) == pytest.approx(0.5)
    assert p_under(220.0, mu, sigma) == pytest.approx(0.5)

    # Line above mean -> over less likely, under more likely
    po_high = p_over(235.0, mu, sigma)  # 1 sd above mean
    pu_high = p_under(235.0, mu, sigma)
    assert po_high < 0.5
    assert pu_high > 0.5
    assert po_high + pu_high == pytest.approx(1.0)
    assert po_high == pytest.approx(1.0 - 0.8413447, abs=1e-4)

    # Line below mean
    po_low = p_over(205.0, mu, sigma)  # 1 sd below mean
    pu_low = p_under(205.0, mu, sigma)
    assert po_low > 0.5
    assert pu_low < 0.5
    assert po_low + pu_low == pytest.approx(1.0)

    # Invalid sigma
    with pytest.raises(ValueError, match="sigma must be positive"):
        p_over(220.0, mu, 0.0)
    with pytest.raises(ValueError, match="sigma must be positive"):
        p_over(220.0, mu, -5.0)


def test_totals_state_empty_history():
    state = TotalsState()
    mu, sigma = state.predict(home_team_id=1, away_team_id=2, season_id=10)

    assert mu == DEFAULT_LEAGUE_TOTAL
    assert sigma == DEFAULT_SIGMA

    po, pu = state.predict_probs(220.0, home_team_id=1, away_team_id=2, season_id=10)
    assert po == pytest.approx(0.5)
    assert pu == pytest.approx(0.5)


def test_totals_state_shrinkage():
    # 2 teams: team 1 scored 130 + 130 = 260 total in its game
    # with prior_weight=5.0 and league_mean=220.0, shrunk rolling total should be (260 + 5*220) / (1 + 5) = 1360 / 6 = 226.6667
    params = TotalsParams(window=10, prior_weight=5.0, default_league_total=220.0, default_sigma=17.7)
    state = TotalsState(params)

    class DummyGame:
        game_id = "001"
        game_date = date(2026, 1, 1)
        season_id = 1
        home_team_id = 1
        away_team_id = 2
        home_pts = 130
        away_pts = 130

    g = DummyGame()
    mu_before, sigma_before = state.predict(1, 2, 1)
    assert mu_before == 220.0
    assert sigma_before == 17.7

    state.update(g, mu=mu_before)

    # Now team 1 and 2 both played one game of 260 total points
    t1 = state.team_rolling_total(1, 1)
    # season has 1 game with 260 points, so season_mean is 260.0
    # shrunk total = (260 + 5 * 260) / (1 + 5) = 260.0
    assert t1 == pytest.approx(260.0)

    # Now predict a game between team 1 and unseen team 3
    # team 3 has 0 games, so shrunk total is season_mean (260.0)
    mu_next, _ = state.predict(1, 3, 1)
    assert mu_next == pytest.approx(260.0)


# ------------------------------------------------------------------------------------------ no leakage

@pytest.fixture(scope="module")
def league():
    return make_league(n_seasons=3, n_teams=8, seed=42)


def test_totals_predictions_of_a_game_ignore_future_games(league):
    """Perturbing future games leaves earlier predictions bit-identical."""
    base_fs, _ = build_totals_feature_set(league)
    i = len(league) // 2

    # Perturb all games after i
    changed_scores = list(league)
    for j in range(i, len(league)):
        g = league[j]
        changed_scores[j] = replace(g, home_pts=g.home_pts + 40, away_pts=g.away_pts + 35)

    new_fs, _ = build_totals_feature_set(changed_scores)
    # The prediction for game i was formed BEFORE game i's scores were revealed,
    # so predictions up to index i must be bit-identical.
    assert np.array_equal(new_fs.mu[: i + 1], base_fs.mu[: i + 1])
    assert np.array_equal(new_fs.sigma[: i + 1], base_fs.sigma[: i + 1])


def test_totals_truncated_history_matches(league):
    """Truncating games after i produces identical predictions up to i."""
    base_fs, _ = build_totals_feature_set(league)
    i = len(league) // 3

    truncated = league[: i + 1]
    trunc_fs, _ = build_totals_feature_set(truncated)

    assert np.array_equal(trunc_fs.mu, base_fs.mu[: i + 1])
    assert np.array_equal(trunc_fs.sigma, base_fs.sigma[: i + 1])


def test_totals_step_by_step_matches_batch_pass(league):
    """Stepping game-by-game with TotalsState matches build_totals_feature_set."""
    batch_fs, _ = build_totals_feature_set(league)
    state = TotalsState()

    for i, g in enumerate(league):
        mu, sigma = state.predict(g.home_team_id, g.away_team_id, g.season_id)
        assert mu == pytest.approx(batch_fs.mu[i])
        assert sigma == pytest.approx(batch_fs.sigma[i])
        state.update(g, mu=mu)
