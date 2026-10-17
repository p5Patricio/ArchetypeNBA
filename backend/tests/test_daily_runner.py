import daily_runner
from app.analytics.props_engine import PlayerBaseline, PropBetLine, PropsEngine
from app.services.gemini_analyzer import PlayerQualitativeModifier


def _player(name: str) -> PlayerBaseline:
    return PlayerBaseline(
        player_id=hash(name) % 10000, name=name, team="LAL", avg_minutes=35.0,
        pts_per_min=0.80, reb_per_min=0.20, ast_per_min=0.20, overdispersion_alpha=0.10,
    )


def test_player_without_live_line_is_skipped():
    engine = PropsEngine(simulation_runs=200)
    props_map = {
        "Has Line": {"PTS": PropBetLine(stat_type="PTS", line=24.5, over_odds=-110, under_odds=-110, bookmaker="alpha")}
    }

    results = daily_runner.evaluate_players(engine, [_player("Has Line"), _player("No Line")], props_map, {})

    assert [r.player_name for r in results] == ["Has Line"]
    assert results[0].sportsbook_line == 24.5
    assert results[0].bookmaker == "alpha"


def test_empty_props_map_yields_no_results():
    engine = PropsEngine(simulation_runs=200)

    assert daily_runner.evaluate_players(engine, [_player("A"), _player("B")], {}, {}) == []


def test_falls_back_to_another_real_stat_but_never_invents_one():
    engine = PropsEngine(simulation_runs=200)
    props_map = {
        "Rebounder": {"REB": PropBetLine(stat_type="REB", line=6.5, over_odds=-120)},
        "Assister": {"AST": PropBetLine(stat_type="AST", line=5.5, over_odds=-120)},  # not PTS/PRA/REB
    }

    results = daily_runner.evaluate_players(engine, [_player("Rebounder"), _player("Assister")], props_map, {})

    assert [(r.player_name, r.stat_type) for r in results] == [("Rebounder", "REB")]


def test_qualitative_modifier_is_applied_to_the_live_line():
    engine = PropsEngine(simulation_runs=200)
    props_map = {"Hurt Star": {"PTS": PropBetLine(stat_type="PTS", line=24.5, over_odds=-110, under_odds=-110)}}
    modifier = PlayerQualitativeModifier(
        player_name="Hurt Star", team="LAL", status="Out", minute_multiplier=0.0, usage_multiplier=0.0,
        risk_level="EXTREME", tactical_summary="Ruled out.",
    )

    results = daily_runner.evaluate_players(engine, [_player("Hurt Star")], props_map, {"hurt star": modifier})

    assert results[0].risk_level == "EXTREME"
    assert "PASS" in results[0].recommendation
