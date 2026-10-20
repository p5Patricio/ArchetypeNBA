"""Leak-free pre-game features (app.analytics.features)."""
from dataclasses import replace
from datetime import date, timedelta

import numpy as np
import pytest

from app.analytics import elo
from app.analytics.features import FEATURE_NAMES, FeatureState, build_feature_set
from app.services.elo_service import HistoricalGame, replay_games
from tests.synthetic_league import make_league


def _game(game_id, day, home, away, home_pts, away_pts, season=1):
    return HistoricalGame(game_id, day, season, home, away, home_pts, away_pts)


def _col(name):
    return FEATURE_NAMES.index(name)


@pytest.fixture
def mini_calendar():
    return [
        _game("g1", date(2024, 10, 20), 1, 2, 100, 90),  # team 1 wins at home by 10
        _game("g2", date(2024, 10, 21), 3, 1, 95, 105),  # team 1 wins away by 10
        _game("g3", date(2024, 10, 24), 1, 3, 110, 100),
    ]


def test_first_game_has_blank_histories(mini_calendar):
    X = build_feature_set(mini_calendar)[0].X[0]
    assert X[_col("elo_edge")] == pytest.approx(elo.HOME_ADVANTAGE)  # equal initial ratings
    for name in ("rest_home", "rest_away"):
        assert X[_col(name)] == 7
    for name in ("b2b_home", "b2b_away", "games7_home", "games7_away", "margin10_home", "margin10_away", "season_progress"):
        assert X[_col(name)] == 0
    assert X[_col("winpct_home")] == X[_col("winpct_away")] == 0.5


def test_rest_back_to_back_and_games_in_the_last_week(mini_calendar):
    X = build_feature_set(mini_calendar)[0].X
    g2, g3 = X[1], X[2]
    assert (g2[_col("rest_home")], g2[_col("rest_away")]) == (7, 1)  # team 3 is new, team 1 played the day before
    assert (g2[_col("b2b_home")], g2[_col("b2b_away")]) == (0, 1)
    assert (g2[_col("games7_home")], g2[_col("games7_away")]) == (0, 1)
    assert (g3[_col("rest_home")], g3[_col("rest_away")]) == (3, 3)
    assert (g3[_col("b2b_home")], g3[_col("b2b_away")]) == (0, 0)
    assert (g3[_col("games7_home")], g3[_col("games7_away")]) == (2, 1)


def test_rest_is_capped_at_seven_days_and_only_the_last_seven_days_count():
    games = [
        _game("a", date(2024, 10, 1), 1, 2, 100, 90),
        _game("b", date(2024, 10, 20), 1, 2, 100, 90),  # 19 days later
    ]
    row = build_feature_set(games)[0].X[1]
    assert row[_col("rest_home")] == row[_col("rest_away")] == 7
    assert row[_col("games7_home")] == row[_col("games7_away")] == 0  # the first game is outside the week

    games.append(_game("c", date(2024, 10, 27), 1, 2, 100, 90))  # exactly 7 days after game b
    assert build_feature_set(games)[0].X[2][_col("games7_home")] == 1
    games[2] = _game("c", date(2024, 10, 28), 1, 2, 100, 90)
    assert build_feature_set(games)[0].X[2][_col("games7_home")] == 0


def test_rolling_margin_and_win_percentage_are_shrunk(mini_calendar):
    g3 = build_feature_set(mini_calendar)[0].X[2]
    # team 1 (home): margins [+10, +10] -> 20 / (2 + 5); 2 wins of 2 -> (2 + 5) / (2 + 10)
    assert g3[_col("margin10_home")] == pytest.approx(20 / 7)
    assert g3[_col("winpct_home")] == pytest.approx(7 / 12)
    # team 3 (away): margin [-10] -> -10 / 6; 0 wins of 1 -> 5 / 11
    assert g3[_col("margin10_away")] == pytest.approx(-10 / 6)
    assert g3[_col("winpct_away")] == pytest.approx(5 / 11)
    assert g3[_col("season_progress")] == pytest.approx((2 + 1) / 2 / 82)


def test_rolling_margin_keeps_only_the_last_ten_games():
    start = date(2024, 10, 1)
    games = [_game(f"g{i:02d}", start + timedelta(days=i), 1, 2, 100 + i, 90) for i in range(12)]  # margins 10..21
    row = build_feature_set(games)[0].X[11]
    assert row[_col("margin10_home")] == pytest.approx(sum(range(11, 21)) / 15)  # games 1..10 -> margins 11..20


def test_a_new_season_resets_the_win_percentage_and_progress_but_not_the_ratings():
    games = [
        _game("a", date(2024, 10, 20), 1, 2, 100, 90, season=1),
        _game("b", date(2025, 10, 20), 1, 2, 100, 90, season=2),
    ]
    row = build_feature_set(games)[0].X[1]
    assert row[_col("winpct_home")] == row[_col("winpct_away")] == 0.5
    assert row[_col("season_progress")] == 0
    assert row[_col("margin10_home")] == pytest.approx(10 / 6)  # recent form crosses the season boundary
    assert row[_col("elo_edge")] != pytest.approx(elo.HOME_ADVANTAGE)  # ratings carried over with regression


def test_elo_edge_matches_the_reference_replay():
    games = make_league(n_seasons=3, n_teams=8, seed=3)
    X = build_feature_set(games)[0].X
    ratings, _ = replay_games(games, params=elo.EloParams())
    expected = [r.home_before + elo.HOME_ADVANTAGE - r.away_before for r in ratings]
    assert X[:, _col("elo_edge")] == pytest.approx(expected)


def test_custom_reference_elo_params_change_only_the_elo_edge():
    games = make_league(n_seasons=2, n_teams=8, seed=3)
    default = build_feature_set(games)[0].X
    other = build_feature_set(games, elo.EloParams(k=30.0, home_advantage=90.0))[0].X
    others = [i for i in range(len(FEATURE_NAMES)) if i != _col("elo_edge")]
    assert np.array_equal(default[:, others], other[:, others])
    assert not np.allclose(default[:, _col("elo_edge")], other[:, _col("elo_edge")])


# ------------------------------------------------------------------------------------------ no leakage

@pytest.fixture(scope="module")
def league():
    return make_league(n_seasons=3, n_teams=8, seed=11)


def test_features_of_a_game_ignore_that_game_and_everything_after(league):
    base = build_feature_set(league)[0].X
    i = len(league) // 2

    changed_scores = list(league)
    for j in range(i, len(league)):
        g = league[j]
        changed_scores[j] = replace(g, home_pts=g.home_pts + 37, away_pts=max(0, g.away_pts - 20))
    assert np.array_equal(build_feature_set(changed_scores)[0].X[: i + 1], base[: i + 1])

    later = league[i].game_date + timedelta(days=400)
    shifted_dates = list(league[: i + 1]) + [replace(g, game_date=later + timedelta(days=k)) for k, g in enumerate(league[i + 1 :])]
    assert np.array_equal(build_feature_set(shifted_dates)[0].X[: i + 1], base[: i + 1])

    truncated = league[: i + 1]  # games after i do not even exist
    assert np.array_equal(build_feature_set(truncated)[0].X, base[: i + 1])


def test_changing_game_i_never_touches_the_features_before_it(league):
    base = build_feature_set(league)[0].X
    i = len(league) // 3
    for variant in (
        replace(league[i], home_pts=league[i].home_pts + 50),
        replace(league[i], game_date=league[i].game_date + timedelta(days=2)),
    ):
        changed = list(league)
        changed[i] = variant
        assert np.array_equal(build_feature_set(changed)[0].X[:i], base[:i])
    missing = league[:i] + league[i + 1 :]
    assert np.array_equal(build_feature_set(missing)[0].X[:i], base[:i])


def test_the_upcoming_game_path_gives_the_same_vector_as_the_training_pass(league):
    full = build_feature_set(league)[0].X
    for i in (0, 1, 7, len(league) // 2, len(league) - 1):
        state = FeatureState()
        for game in league[:i]:
            state.update(game)
        g = league[i]
        assert np.array_equal(state.vector(g.home_team_id, g.away_team_id, g.season_id, g.game_date), full[i])


def test_targets_and_season_ranks(league):
    fs = build_feature_set(league)[0]
    assert len(fs) == len(league) and fs.X.shape == (len(league), len(FEATURE_NAMES))
    assert np.array_equal(fs.margin, [g.home_pts - g.away_pts for g in league])
    assert np.array_equal(fs.home_win, (fs.margin > 0).astype(float))
    assert sorted(set(fs.season_rank.tolist())) == [0, 1, 2]
    assert np.all(np.diff(fs.season_rank) >= 0)


def test_unseen_teams_are_unknown_and_get_blank_histories():
    state = FeatureState()
    assert not state.knows(1) and state.team_last_game_date(1) is None
    state.update(_game("a", date(2024, 10, 20), 1, 2, 100, 90))
    assert state.knows(1) and state.team_last_game_date(2) == date(2024, 10, 20)
    row = state.vector(1, 99, 1, date(2024, 10, 22))
    assert row[_col("rest_away")] == 7 and row[_col("winpct_away")] == 0.5
