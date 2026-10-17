import pytest
from app.analytics.props_engine import (
    PropsEngine,
    PlayerBaseline,
    PropBetLine,
    american_to_decimal,
    decimal_to_implied_prob,
    devig_two_way,
)


def test_american_to_decimal():
    assert american_to_decimal(-110) == 1.909
    assert american_to_decimal(+100) == 2.0
    assert american_to_decimal(+150) == 2.5


def test_decimal_to_implied_prob():
    assert decimal_to_implied_prob(2.0) == 0.5
    assert decimal_to_implied_prob(1.909) == 0.5238


def test_props_engine_standard_evaluation():
    engine = PropsEngine(simulation_runs=1000)
    player = PlayerBaseline(
        player_id=1,
        name="Star Player",
        team="LAL",
        avg_minutes=35.0,
        pts_per_min=0.80,
        reb_per_min=0.20,
        ast_per_min=0.20,
        overdispersion_alpha=0.10,
    )
    # Expected mean = 35.0 * 0.80 = 28.0 PTS
    prop_line = PropBetLine(stat_type="PTS", line=24.5, over_odds=-110)

    result = engine.evaluate_prop(player=player, prop=prop_line)

    assert result.player_name == "Star Player"
    assert result.projected_mean == 28.0
    assert 0.0 < result.prob_over < 1.0
    assert 0.0 < result.prob_under < 1.0
    assert round(result.prob_over + result.prob_under, 2) == 1.0
    # Because projected mean (28.0) is higher than line (24.5), Over should have positive edge
    assert result.prob_over > result.book_implied_prob
    assert result.edge_pct > 0.0
    assert result.recommendation in ("STRONG OVER", "LEAN OVER")


def test_props_engine_player_out():
    engine = PropsEngine(simulation_runs=500)
    player = PlayerBaseline(
        player_id=2,
        name="Injured Star",
        team="DAL",
        avg_minutes=36.0,
        pts_per_min=0.90,
        reb_per_min=0.20,
        ast_per_min=0.20,
    )
    prop_line = PropBetLine(stat_type="PTS", line=30.5)

    # Teammate or player confirmed OUT -> minute_multiplier = 0.0
    result = engine.evaluate_prop(
        player=player,
        prop=prop_line,
        minute_multiplier=0.0,
        usage_multiplier=0.0,
        tactical_summary="Ruled OUT with ankle injury",
    )

    assert result.projected_mean == 0.0
    assert result.prob_over == 0.0
    assert result.prob_under == 1.0
    assert "PASS" in result.recommendation


def _star() -> PlayerBaseline:
    # Expected mean = 35.0 * 0.80 = 28.0 PTS
    return PlayerBaseline(
        player_id=3, name="Star Player", team="LAL", avg_minutes=35.0,
        pts_per_min=0.80, reb_per_min=0.20, ast_per_min=0.20, overdispersion_alpha=0.10,
    )


def test_devig_two_way_even_market():
    fair_over, fair_under = devig_two_way(american_to_decimal(-110), american_to_decimal(-110))
    assert fair_over == pytest.approx(0.5)
    assert fair_under == pytest.approx(0.5)


def test_devig_two_way_sums_to_one_and_keeps_favorite():
    fair_over, fair_under = devig_two_way(american_to_decimal(-150), american_to_decimal(+120))
    assert fair_over + fair_under == pytest.approx(1.0)
    assert fair_over > fair_under
    # no-vig prob is below the vigged implied prob of the favorite
    assert fair_over < 1.0 / american_to_decimal(-150)


def test_two_sided_prop_recommends_under_when_under_has_positive_ev():
    engine = PropsEngine(simulation_runs=500)
    # mean 28 vs line 33.5: the model strongly favors the under
    prop = PropBetLine(stat_type="PTS", line=33.5, over_odds=-110, under_odds=-110, bookmaker="alpha")

    result = engine.evaluate_prop(player=_star(), prop=prop)

    assert result.side == "under"
    assert result.devigged is True
    assert result.fair_prob == pytest.approx(0.5)
    assert result.recommendation in ("STRONG UNDER", "LEAN UNDER")
    assert result.expected_value_pct > 0
    assert result.edge_pct > 0
    assert result.kelly_stake_pct > 0
    assert result.under_odds == -110
    assert result.bookmaker == "alpha"
    # EV uses the under's own price and the model's under probability
    expected_ev = round(result.prob_under * american_to_decimal(-110) - 1.0, 4) * 100.0
    assert result.expected_value_pct == pytest.approx(expected_ev, abs=0.1)


def test_two_sided_prop_recommends_over_against_fair_probability():
    engine = PropsEngine(simulation_runs=500)
    prop = PropBetLine(stat_type="PTS", line=24.5, over_odds=-110, under_odds=-110)

    result = engine.evaluate_prop(player=_star(), prop=prop)

    assert result.side == "over"
    assert result.devigged is True
    assert result.book_implied_prob == pytest.approx(0.5)  # no-vig, not the vigged 0.5238
    assert result.recommendation in ("STRONG OVER", "LEAN OVER")


def test_two_sided_prop_with_no_edge_is_pass():
    engine = PropsEngine(simulation_runs=500)
    # mean 28: line 27.5 is near the median, so neither side clears the thresholds
    prop = PropBetLine(stat_type="PTS", line=27.5, over_odds=-110, under_odds=-110)

    result = engine.evaluate_prop(player=_star(), prop=prop)

    assert result.recommendation == "PASS"


def test_one_sided_prop_is_not_devigged_and_never_recommends_under():
    engine = PropsEngine(simulation_runs=500)
    # Line far above the projection: the old logic would say LEAN UNDER from a made-up -110 under.
    prop = PropBetLine(stat_type="PTS", line=33.5, over_odds=-110)

    assert prop.under_odds is None
    result = engine.evaluate_prop(player=_star(), prop=prop)

    assert result.devigged is False
    assert result.fair_prob is None
    assert result.side == "over"
    assert result.under_odds is None
    assert "UNDER" not in result.recommendation
    # vigged implied probability of the over is used
    assert result.book_implied_prob == pytest.approx(decimal_to_implied_prob(american_to_decimal(-110)))
