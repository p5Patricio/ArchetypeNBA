import math

import pytest

from app.analytics import elo


def test_equal_ratings_give_home_court_edge():
    assert elo.expected_home_win_prob(1500, 1500) == pytest.approx(1 / (1 + 10 ** (-elo.HOME_ADVANTAGE / 400)))
    assert elo.expected_home_win_prob(1500, 1500) == pytest.approx(0.585, abs=1e-3)
    # the original FiveThirtyEight constant is still reachable explicitly
    assert elo.expected_home_win_prob(1500, 1500, home_advantage=100) == pytest.approx(0.640, abs=1e-3)


def test_home_win_prob_is_even_when_rating_gap_cancels_home_advantage():
    assert elo.expected_home_win_prob(1500 - elo.HOME_ADVANTAGE, 1500) == pytest.approx(0.5)


def test_update_is_zero_sum_and_returns_pre_game_probability():
    new_home, new_away, p_home = elo.update_ratings(1550, 1480, 110, 100)
    assert new_home + new_away == pytest.approx(1550 + 1480)
    assert p_home == pytest.approx(elo.expected_home_win_prob(1550, 1480))


def test_winner_gains_and_loser_drops():
    home_win = elo.update_ratings(1500, 1500, 105, 100)
    away_win = elo.update_ratings(1500, 1500, 100, 105)
    assert home_win[0] > 1500 > home_win[1]
    assert away_win[0] < 1500 < away_win[1]


def test_upset_moves_ratings_more_than_expected_win():
    favourite_wins = elo.update_ratings(1700, 1400, 110, 100)
    underdog_wins = elo.update_ratings(1700, 1400, 100, 110)
    assert abs(underdog_wins[0] - 1700) > abs(favourite_wins[0] - 1700)


def test_mov_multiplier_grows_with_margin():
    values = [elo.mov_multiplier(m, 0.0) for m in (1, 5, 10, 20, 30)]
    assert values == sorted(values)
    assert len(set(values)) == len(values)


def test_mov_multiplier_is_known_value():
    assert elo.mov_multiplier(10, 0.0) == pytest.approx((13 ** 0.8) / 7.5)
    # a large winner edge damps the multiplier (autocorrelation correction)
    assert elo.mov_multiplier(10, 200.0) < elo.mov_multiplier(10, 0.0)


def test_bigger_margin_moves_ratings_more():
    small = elo.update_ratings(1500, 1500, 101, 100)
    blowout = elo.update_ratings(1500, 1500, 130, 100)
    assert blowout[0] - 1500 > small[0] - 1500


def test_season_carryover_pulls_toward_league_mean():
    assert elo.season_carryover(1505) == pytest.approx(1505)
    assert elo.season_carryover(1705) == pytest.approx(1655)
    assert elo.season_carryover(1305) == pytest.approx(1355)


def test_expected_margin_converts_elo_gap_to_points():
    assert elo.expected_margin(1500, 1500) == pytest.approx(elo.HOME_ADVANTAGE / 28)
    assert elo.expected_margin(1500 - elo.HOME_ADVANTAGE, 1500) == pytest.approx(0.0)


@pytest.mark.parametrize("mu", [-7.5, 0.0, 3.2, 11.0])
@pytest.mark.parametrize("line", [-10.5, -4.5, -4.0, 0.0, 2.5, 6.0])
def test_spread_probabilities_sum_to_one(mu, line):
    p_home, p_push, p_away = elo.spread_probabilities(mu, 12.0, line)
    assert p_home + p_push + p_away == pytest.approx(1.0)
    assert min(p_home, p_push, p_away) >= 0.0


def test_integer_lines_have_push_and_half_lines_do_not():
    assert elo.spread_probabilities(3.0, 12.0, -4.0)[1] > 0.0
    assert elo.spread_probabilities(3.0, 12.0, 0.0)[1] > 0.0
    assert elo.spread_probabilities(3.0, 12.0, -4.5)[1] == 0.0
    assert elo.spread_probabilities(3.0, 12.0, 2.5)[1] == 0.0


def test_symmetric_when_margin_is_zero():
    p_home, p_push, p_away = elo.spread_probabilities(0.0, 12.0, 0.0)
    assert p_home == pytest.approx(p_away)
    assert p_push > 0.0
    # mirrored lines swap the sides
    home_minus, _, away_minus = elo.spread_probabilities(0.0, 12.0, -4.5)
    home_plus, _, away_plus = elo.spread_probabilities(0.0, 12.0, 4.5)
    assert home_minus == pytest.approx(away_plus)
    assert away_minus == pytest.approx(home_plus)


def test_half_line_matches_continuity_corrected_normal():
    # home -4.5 needs M >= 5, i.e. normal tail above 4.5
    mu, sigma = 6.0, 12.0
    p_home, _, _ = elo.spread_probabilities(mu, sigma, -4.5)
    expected = 0.5 * math.erfc((4.5 - mu) / sigma / math.sqrt(2))
    assert p_home == pytest.approx(expected)


def test_integer_line_push_mass_is_one_point_wide():
    mu, sigma = 4.0, 12.0
    _, p_push, _ = elo.spread_probabilities(mu, sigma, -4.0)
    # near the mean the discrete mass of a single integer is about the density
    assert p_push == pytest.approx(1 / (sigma * math.sqrt(2 * math.pi)), rel=0.01)


def test_spread_favours_home_as_expected_margin_grows():
    low = elo.spread_probabilities(0.0, 12.0, -4.5)[0]
    high = elo.spread_probabilities(8.0, 12.0, -4.5)[0]
    assert high > low


def test_spread_rejects_non_positive_sigma():
    with pytest.raises(ValueError):
        elo.spread_probabilities(0.0, 0.0, -4.5)
