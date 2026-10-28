import math
import pytest

from app.analytics.clv_stats import (
    BetClvRecord,
    ClvStats,
    bets_needed_for,
    compute_clv_stats,
    log_odds_clv,
)


def test_log_odds_clv_basic():
    assert log_odds_clv(2.0, 1.8) == pytest.approx(math.log(2.0 / 1.8))
    assert log_odds_clv(1.9, 2.0) == pytest.approx(math.log(1.9 / 2.0))
    assert log_odds_clv(2.0, 2.0) == 0.0


def test_log_odds_clv_invalid_prices():
    with pytest.raises(ValueError):
        log_odds_clv(0.0, 1.8)
    with pytest.raises(ValueError):
        log_odds_clv(2.0, -1.0)


def test_empty_records_returns_none_gracefully():
    stats = compute_clv_stats([])
    assert stats.n_games == 0
    assert stats.mean_clv is None
    assert stats.std_dev is None
    assert stats.std_err is None
    assert stats.t_stat is None
    assert stats.bets_needed_for(0.01) is None


def test_single_game_returns_none_for_sample_stats():
    record = BetClvRecord(game_id=101, price_taken=2.0, fair_closing_price=1.8)
    stats = compute_clv_stats([record])
    assert stats.n_games == 1
    assert stats.mean_clv == pytest.approx(math.log(2.0 / 1.8))
    assert stats.std_dev is None
    assert stats.std_err is None
    assert stats.t_stat is None
    assert stats.bets_needed_for(0.01) is None


def test_duplicate_bets_on_same_game_are_averaged_first():
    # Game 1 has two bets: price 2.0/close 1.8 (log CLV ~0.10536) and price 2.2/close 1.8 (log CLV ~0.20067)
    # Average for Game 1 = (0.10536 + 0.20067) / 2 = 0.153015
    # Game 2 has one bet: price 1.8/close 2.0 (log CLV ~ -0.10536)
    r1 = BetClvRecord(game_id=1, price_taken=2.0, fair_closing_price=1.8)
    r2 = BetClvRecord(game_id=1, price_taken=2.2, fair_closing_price=1.8)
    r3 = BetClvRecord(game_id=2, price_taken=1.8, fair_closing_price=2.0)

    stats = compute_clv_stats([r1, r2, r3])
    assert stats.n_games == 2

    clv_g1 = (math.log(2.0 / 1.8) + math.log(2.2 / 1.8)) / 2.0
    clv_g2 = math.log(1.8 / 2.0)
    expected_mean = (clv_g1 + clv_g2) / 2.0
    assert stats.mean_clv == pytest.approx(expected_mean)

    expected_var = ((clv_g1 - expected_mean) ** 2 + (clv_g2 - expected_mean) ** 2) / (2 - 1)
    expected_sd = math.sqrt(expected_var)
    expected_se = expected_sd / math.sqrt(2)
    expected_t = expected_mean / expected_se

    assert stats.std_dev == pytest.approx(expected_sd)
    assert stats.std_err == pytest.approx(expected_se)
    assert stats.t_stat == pytest.approx(expected_t)


def test_bets_needed_for_formula():
    sd = 0.0596  # 5.96% observed in research doc
    # For +1%: ((1.645 + 0.8416) * 0.0596 / 0.01) ** 2 ~ 219.64
    needed_1pct = bets_needed_for(sd, 0.01)
    assert needed_1pct == pytest.approx(219.64, rel=1e-2)

    # For +2%: ((1.645 + 0.8416) * 0.0596 / 0.02) ** 2 ~ 54.91
    needed_2pct = bets_needed_for(sd, 0.02)
    assert needed_2pct == pytest.approx(54.91, rel=1e-2)

    # Invalid delta or missing sd
    assert bets_needed_for(None, 0.01) is None
    assert bets_needed_for(sd, 0.0) is None
    assert bets_needed_for(sd, -0.01) is None


def test_zero_variance_does_not_crash():
    r1 = BetClvRecord(game_id=1, price_taken=2.0, fair_closing_price=1.8)
    r2 = BetClvRecord(game_id=2, price_taken=2.0, fair_closing_price=1.8)
    stats = compute_clv_stats([r1, r2])
    assert stats.n_games == 2
    assert stats.std_dev == pytest.approx(0.0)
    assert stats.std_err == pytest.approx(0.0)
    assert stats.t_stat is None  # se == 0: no division by zero
