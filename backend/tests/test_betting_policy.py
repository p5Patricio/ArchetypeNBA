import numpy as np
import pytest

from app.analytics import betting_policy as bp


def test_shrink_probability_blends_toward_the_fair_price():
    assert bp.shrink_probability(0.60, 0.50) == pytest.approx(0.55)
    assert bp.shrink_probability(0.60, 0.50, alpha=0.0) == pytest.approx(0.50)
    assert bp.shrink_probability(0.60, 0.50, alpha=1.0) == pytest.approx(0.60)


def test_bet_ev_without_push_is_the_classic_formula():
    assert bp.bet_ev(0.55, 0.0, 1.909) == pytest.approx(0.55 * 1.909 - 1.0)
    assert bp.bet_ev(0.50, 0.0, 2.0) == pytest.approx(0.0)


def test_bet_ev_scales_by_the_non_push_mass():
    # p_cond 0.55 with a 10% push chance at 2.0: 0.9 * (0.55 * 2 - 1)
    assert bp.bet_ev(0.55, 0.10, 2.0) == pytest.approx(0.09)


def test_kelly_fraction_known_values():
    assert bp.kelly_fraction(0.55, 0.0, 2.0) == pytest.approx(0.10)  # b = 1: p - q
    assert bp.kelly_fraction(0.55, 0.10, 2.0) == pytest.approx(0.09)
    assert bp.kelly_fraction(0.60, 0.0, 3.0) == pytest.approx((2 * 0.6 - 0.4) / 2)


def test_kelly_fraction_is_zero_without_an_edge():
    assert bp.kelly_fraction(0.50, 0.0, 1.909) == 0.0
    assert bp.kelly_fraction(0.40, 0.0, 2.0) == 0.0
    assert bp.kelly_fraction(0.70, 0.0, 1.0) == 0.0  # price of 1.0 pays nothing


def test_flat_stake_is_one_unit():
    assert bp.flat_stake() == 1.0


def test_kelly_stake_applies_the_multiplier():
    assert bp.kelly_stake(100.0, 0.04) == pytest.approx(1.0)  # 100 * 0.04 * 0.25


def test_kelly_stake_is_capped_per_bet():
    assert bp.kelly_stake(100.0, 0.50) == pytest.approx(2.0)  # 2% of 100
    assert bp.kelly_stake(250.0, 0.50) == pytest.approx(5.0)


def test_kelly_stake_respects_the_remaining_daily_and_game_room():
    assert bp.kelly_stake(100.0, 0.04, daily_room=0.6) == pytest.approx(0.6)
    assert bp.kelly_stake(100.0, 0.04, game_room=0.4) == pytest.approx(0.4)
    assert bp.kelly_stake(100.0, 0.04, daily_room=5.0, game_room=5.0) == pytest.approx(1.0)


def test_stakes_under_the_minimum_are_not_placed():
    assert bp.kelly_stake(100.0, 0.001) == 0.0  # 0.025u
    assert bp.kelly_stake(100.0, 0.04, daily_room=0.04) == 0.0
    assert bp.cap_stake(1.0, 100.0, game_room=0.0) == 0.0
    assert bp.cap_stake(1.0, 100.0, game_room=0.05) == pytest.approx(0.05)


def test_exposure_rooms_shrink_with_what_is_already_staked():
    assert bp.daily_room(100.0, 3.0) == pytest.approx(7.0)
    assert bp.daily_room(100.0, 12.0) == 0.0
    assert bp.game_room(100.0, 1.0) == pytest.approx(3.0)
    assert bp.game_room(200.0, 0.0) == pytest.approx(8.0)


def test_candidate_with_enough_edge_and_ev_is_eligible():
    d = bp.evaluate_candidate(p_win=0.56, p_push=0.0, p_loss=0.44, p_fair=0.52, decimal_price=1.95)

    assert d.eligible and d.reason == "ok"
    assert d.p_cond == pytest.approx(0.56)
    assert d.raw_edge == pytest.approx(0.04)
    assert d.p_blend == pytest.approx(0.54)
    assert d.ev == pytest.approx(0.54 * 1.95 - 1.0)
    assert d.f_star == pytest.approx(bp.kelly_fraction(0.54, 0.0, 1.95)) and d.f_star > 0


def test_candidate_below_the_raw_edge_is_rejected():
    d = bp.evaluate_candidate(0.53, 0.0, 0.47, p_fair=0.52, decimal_price=2.20)

    assert not d.eligible and d.reason == "edge_below_min"
    assert d.raw_edge == pytest.approx(0.01)


def test_candidate_with_edge_but_a_poor_price_fails_on_ev():
    d = bp.evaluate_candidate(0.55, 0.0, 0.45, p_fair=0.53, decimal_price=1.80)

    assert not d.eligible and d.reason == "ev_below_min"
    assert d.raw_edge == pytest.approx(0.02)
    assert d.ev < 0.02


def test_candidate_edge_is_judged_on_the_conditional_probability_when_a_push_is_possible():
    # p_win 0.45 / p_push 0.10 / p_loss 0.45 -> p_cond 0.5; fair 0.5 gives no edge
    d = bp.evaluate_candidate(0.45, 0.10, 0.45, p_fair=0.50, decimal_price=2.0)

    assert d.p_cond == pytest.approx(0.5)
    assert not d.eligible and d.reason == "edge_below_min"


def test_candidate_ev_uses_the_push_adjustment():
    d = bp.evaluate_candidate(0.495, 0.10, 0.405, p_fair=0.50, decimal_price=2.0)  # p_cond 0.55

    assert d.eligible
    assert d.ev == pytest.approx(0.9 * (0.525 * 2.0 - 1.0))


def test_degenerate_inputs_are_rejected_not_divided_by_zero():
    assert bp.evaluate_candidate(0.0, 1.0, 0.0, 0.5, 2.0).reason == "invalid_input"
    assert bp.evaluate_candidate(0.6, 0.0, 0.4, 0.5, 1.0).reason == "invalid_input"


def test_edge_threshold_is_inclusive_despite_float_noise():
    d = bp.evaluate_candidate(0.57, 0.0, 0.43, p_fair=0.55, decimal_price=2.2)

    assert d.raw_edge >= 0.02 - 1e-12
    assert d.eligible


def test_shrink_factor_monotonic_in_edge():
    edges = [0.005, 0.01, 0.02, 0.05, 0.10, 0.20]
    factors = [bp.shrink_factor(e) for e in edges]
    assert all(f > 0.0 for f in factors)
    assert factors == sorted(factors)
    assert all(0.0 <= f <= 1.0 for f in factors)


def test_shrink_factor_zero_and_negative_edge():
    assert bp.shrink_factor(0.0) == 0.0
    assert bp.shrink_factor(-0.05) == 0.0
    assert bp.shrink_factor(-1.0) == 0.0


def test_shrink_factor_exact_half_at_noise_sd():
    assert bp.shrink_factor(0.05, noise_sd=0.05) == pytest.approx(0.5)
    assert bp.shrink_factor(0.10, noise_sd=0.10) == pytest.approx(0.5)


def test_kelly_shrunk_stake_applies_shrinkage():
    # At edge == noise_sd (0.05): shrink_factor is 0.5.
    # Base multiplier is 0.5, so effective multiplier = 0.5 * 0.5 = 0.25.
    # 100 bankroll * 0.04 f_star * 0.25 = 1.0u.
    assert bp.kelly_shrunk_stake(100.0, 0.04, edge=0.05) == pytest.approx(1.0)


def test_kelly_shrunk_stake_respects_caps_and_min_stake():
    # Per-bet cap: 2% of 100 = 2.0u
    assert bp.kelly_shrunk_stake(100.0, 0.50, edge=0.20) == pytest.approx(2.0)
    # Daily room and game room
    assert bp.kelly_shrunk_stake(100.0, 0.04, edge=0.05, daily_room=0.6) == pytest.approx(0.6)
    assert bp.kelly_shrunk_stake(100.0, 0.04, edge=0.05, game_room=0.4) == pytest.approx(0.4)
    # Zero edge -> multiplier 0 -> stake 0
    assert bp.kelly_shrunk_stake(100.0, 0.04, edge=0.0) == 0.0
    # Under min stake (< 0.05)
    assert bp.kelly_shrunk_stake(100.0, 0.001, edge=0.05) == 0.0


def test_evaluate_market_edge_eligible_when_soft_beats_sharp_prob():
    # Pinnacle fair prob is 0.50 (fair decimal 2.00). Soft book offers 2.10.
    # ev = 0.50 * 2.10 - 1.0 = +0.05 >= 0.02
    d = bp.evaluate_market_edge(p_fair=0.50, decimal_price=2.10)

    assert d.eligible and d.reason == "ok"
    assert d.p_cond == pytest.approx(0.50)
    assert d.p_blend == pytest.approx(0.50)
    assert d.raw_edge == 0.0
    assert d.ev == pytest.approx(0.05)
    assert d.f_star > 0.0


def test_evaluate_market_edge_rejected_when_ev_below_min():
    # Pinnacle fair 0.50, soft book offers 2.02 -> ev = 0.50 * 2.02 - 1.0 = +0.01 < 0.02
    d = bp.evaluate_market_edge(p_fair=0.50, decimal_price=2.02)

    assert not d.eligible and d.reason == "ev_below_min"
    assert d.ev == pytest.approx(0.01)


def test_evaluate_market_edge_invalid_inputs():
    assert bp.evaluate_market_edge(0.0, 2.0).reason == "invalid_input"
    assert bp.evaluate_market_edge(1.0, 2.0).reason == "invalid_input"
    assert bp.evaluate_market_edge(0.5, 1.0).reason == "invalid_input"
    assert bp.evaluate_market_edge(0.5, -1.0).reason == "invalid_input"



# --- calibrated strategy ------------------------------------------------------------------------------------------


def _sigmoid(x):
    return 1.0 / (1.0 + np.exp(-x))


def _logit(p):
    return np.log(p / (1.0 - p))


def test_logit_blend_endpoints_and_midpoint():
    assert bp.logit_blend(0.70, 0.55, 0.0) == pytest.approx(0.55)
    assert bp.logit_blend(0.70, 0.55, 1.0) == pytest.approx(0.70)
    # two probabilities symmetric around 0.5 in logit space blend to 0.5 at w = 0.5
    assert bp.logit_blend(0.60, 0.40, 0.5) == pytest.approx(0.5)
    blended = bp.logit_blend(0.70, 0.55, 0.3)
    assert 0.55 < blended < 0.70
    assert _logit(blended) == pytest.approx(0.3 * _logit(0.70) + 0.7 * _logit(0.55))


def test_logit_blend_clips_extreme_probabilities():
    assert 0.0 < bp.logit_blend(0.0, 0.5, 1.0) < 1e-5
    assert 1.0 - 1e-5 < bp.logit_blend(1.0, 0.5, 1.0) < 1.0


def _synthetic_games(model_has_signal, n=4000, seed=7):
    """
    Truth-generating market world. Noise: the market IS the true probability and the model is that probability
    plus independent logit noise. Signal: the market sees only part of the truth and the model sees the rest.
    """
    rng = np.random.default_rng(seed)
    if not model_has_signal:
        logit_true = rng.normal(0.0, 0.7, n)
        p_true = _sigmoid(logit_true)
        p_fair = p_true
        p_model = _sigmoid(logit_true + rng.normal(0.0, 0.7, n))
    else:
        shared = rng.normal(0.0, 0.5, n)
        private = rng.normal(0.0, 0.5, n)  # information only the model has
        p_true = _sigmoid(shared + private)
        p_fair = _sigmoid(shared)
        p_model = _sigmoid(shared + private + rng.normal(0.0, 0.3, n))
    outcomes = (rng.random(n) < p_true).astype(float)
    return list(p_model), list(p_fair), list(outcomes)


def test_fit_blend_weight_is_about_zero_when_the_model_is_noise_around_the_market():
    p_model, p_fair, outcomes = _synthetic_games(model_has_signal=False)

    w_used, w_hat, n = bp.fit_blend_weight(p_model, p_fair, outcomes)

    assert n == 4000
    assert w_hat <= 0.05
    assert w_used <= w_hat


def test_fit_blend_weight_is_clearly_positive_when_the_model_carries_independent_signal():
    p_model, p_fair, outcomes = _synthetic_games(model_has_signal=True)

    w_used, w_hat, n = bp.fit_blend_weight(p_model, p_fair, outcomes)

    assert w_hat >= 0.30
    assert w_hat <= bp.W_MAX
    assert w_used == pytest.approx(w_hat * n / (n + bp.CALIBRATION_PRIOR_GAMES))
    assert 0.0 < w_used < w_hat


def test_fit_blend_weight_is_zero_below_the_minimum_number_of_games():
    p_model, p_fair, outcomes = _synthetic_games(model_has_signal=True, n=4000)
    k = bp.MIN_CALIBRATION_GAMES - 1

    w_used, w_hat, n = bp.fit_blend_weight(p_model[:k], p_fair[:k], outcomes[:k])

    assert n == k and w_used == 0.0

    w_used, w_hat, n = bp.fit_blend_weight(
        p_model[: bp.MIN_CALIBRATION_GAMES], p_fair[: bp.MIN_CALIBRATION_GAMES], outcomes[: bp.MIN_CALIBRATION_GAMES]
    )
    assert n == bp.MIN_CALIBRATION_GAMES
    assert w_used == pytest.approx(w_hat * n / (n + bp.CALIBRATION_PRIOR_GAMES))


def test_fit_blend_weight_handles_empty_input_and_rejects_ragged_input():
    assert bp.fit_blend_weight([], [], []) == (0.0, 0.0, 0)
    with pytest.raises(ValueError):
        bp.fit_blend_weight([0.5], [0.5, 0.5], [1.0])


def test_evaluate_calibrated_ok_inside_the_band_with_enough_ev():
    # model 0.60 vs market 0.57 (3pp), price 1.80, w 0.3: blend slightly above 0.57
    decision = bp.evaluate_calibrated(0.60, 0.0, 0.40, 0.57, 1.80, 0.3)

    p_blend = bp.logit_blend(0.60, 0.57, 0.3)
    assert decision.eligible and decision.reason == "ok"
    assert decision.p_cond == pytest.approx(0.60)
    assert decision.p_blend == pytest.approx(p_blend)
    assert decision.raw_edge == pytest.approx(0.03)
    assert decision.ev == pytest.approx(p_blend * 1.80 - 1.0)
    assert decision.f_star > 0.0


def test_evaluate_calibrated_reasons():
    assert bp.evaluate_calibrated(0.0, 0.0, 0.0, 0.5, 1.9, 0.3).reason == "invalid_input"
    assert bp.evaluate_calibrated(0.6, 0.0, 0.4, 0.5, 1.0, 0.3).reason == "invalid_input"
    assert bp.evaluate_calibrated(0.6, 0.0, 0.4, 0.0, 1.9, 0.3).reason == "invalid_input"

    no_weight = bp.evaluate_calibrated(0.57, 0.0, 0.43, 0.55, 2.2, 0.0)
    assert not no_weight.eligible and no_weight.reason == "no_model_weight"
    assert bp.evaluate_calibrated(0.57, 0.0, 0.43, 0.55, 2.2, -0.1).reason == "no_model_weight"

    # 8pp apart in either direction is a model error, not an edge
    assert bp.evaluate_calibrated(0.63, 0.0, 0.37, 0.55, 2.2, 0.3).reason == "disagreement_too_large"
    assert bp.evaluate_calibrated(0.47, 0.0, 0.53, 0.55, 2.2, 0.3).reason == "disagreement_too_large"
    # exactly at the cap is still inside the band
    assert bp.evaluate_calibrated(0.61, 0.0, 0.39, 0.55, 2.2, 0.3).reason != "disagreement_too_large"

    # inside the band but the price is too short for the blended probability
    low_ev = bp.evaluate_calibrated(0.57, 0.0, 0.43, 0.55, 1.70, 0.3)
    assert not low_ev.eligible and low_ev.reason == "ev_below_min"
    assert low_ev.ev < bp.MIN_EV


def test_evaluate_calibrated_conditions_on_no_push():
    decision = bp.evaluate_calibrated(0.45, 0.10, 0.45, 0.48, 2.10, 0.4)
    assert decision.p_cond == pytest.approx(0.5)
    assert decision.ev == pytest.approx(bp.bet_ev(decision.p_blend, 0.10, 2.10))
