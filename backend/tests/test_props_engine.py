import pytest
from app.analytics.props_engine import (
    PropsEngine,
    PlayerBaseline,
    PropBetLine,
    american_to_decimal,
    decimal_to_implied_prob,
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
