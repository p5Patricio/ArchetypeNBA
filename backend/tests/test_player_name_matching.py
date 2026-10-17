import daily_runner
from app.analytics.props_engine import (
    PlayerBaseline,
    PropBetLine,
    PropsEngine,
    index_props_by_player,
    normalize_player_key,
)


def _line(stat="PTS", line=27.5):
    return PropBetLine(stat_type=stat, line=line, over_odds=-110, under_odds=-110, bookmaker="alpha")


def _player(name: str) -> PlayerBaseline:
    return PlayerBaseline(
        player_id=1, name=name, team="DAL", avg_minutes=35.0,
        pts_per_min=0.80, reb_per_min=0.20, ast_per_min=0.20, overdispersion_alpha=0.10,
    )


def test_normalize_player_key_ignores_accents_case_and_punctuation():
    assert normalize_player_key("Luka Dončić") == "luka doncic"
    assert normalize_player_key("Nikola Jokić") == normalize_player_key("nikola jokic")
    assert normalize_player_key("P.J.  Washington Jr.") == "pj washington jr"
    assert normalize_player_key("Shai Gilgeous-Alexander") == "shai gilgeous alexander"
    assert normalize_player_key("De'Aaron Fox") == normalize_player_key("DeAaron Fox")


def test_index_props_by_player_merges_names_that_normalize_alike():
    indexed = index_props_by_player({"Luka Dončić": {"PTS": _line()}, "Luka Doncic": {"REB": _line("REB", 8.5)}})

    assert set(indexed) == {"luka doncic"}
    assert set(indexed["luka doncic"]) == {"PTS", "REB"}


def test_daily_runner_finds_accented_api_names_for_unaccented_baselines():
    engine = PropsEngine(simulation_runs=200)
    props_map = {"Luka Dončić": {"PTS": _line()}}

    results = daily_runner.evaluate_players(engine, [_player("Luka Doncic")], props_map, {})

    assert [r.player_name for r in results] == ["Luka Doncic"]
    assert results[0].sportsbook_line == 27.5
