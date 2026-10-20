"""The margin_features family: training, JSON params, numpy inference and the registry plug-in."""
import ast
import inspect
import json
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest

from app.analytics.features import FEATURE_NAMES, build_feature_set
from app.models import ModelVersion
from app.services import margin_features_model, model_registry
from app.services.margin_features_model import (
    FAMILY_NAME,
    MarginFeaturesFamily,
    MarginFeaturesModel,
    fit_on_feature_set,
    nba_date,
)
from tests.synthetic_league import make_league
from tests.test_elo_backfill_service import add_game, world  # noqa: F401


@pytest.fixture(scope="module")
def trained():
    games = make_league(n_seasons=7, n_teams=10, seed=5)
    feature_set, _ = build_feature_set(games)
    train = feature_set.season_rank < 5  # seasons 0..4 train, 5..6 test
    params = fit_on_feature_set(feature_set, train, seed=42, trained_through=games[train.sum() - 1].game_date, seasons=["s1", "s2"])
    return games, feature_set, train, params


def test_params_are_plain_json_with_everything_inference_needs(trained):
    _, _, train, params = trained
    assert json.loads(json.dumps(params)) == params
    assert params["feature_names"] == list(FEATURE_NAMES)
    assert len(params["mean"]) == len(params["scale"]) == len(params["ridge"]["coef"]) == len(params["logistic"]["coef"]) == len(FEATURE_NAMES)
    assert params["sigma"] > 0 and params["seed"] == 42 and params["n_train"] == int(train.sum())
    assert params["ridge"]["alpha"] > 0 and params["logistic"]["C"] > 0
    assert params["elo_params"]["K"] == 20.0 and params["seasons"] == ["s1", "s2"]


def test_the_model_beats_a_coin_flip_and_predicts_the_margin_sign(trained):
    _, fs, train, params = trained
    test = ~train
    p_home, mu = MarginFeaturesModel(params).predict_matrix(fs.X[test])
    wins = fs.home_win[test]
    assert np.mean((p_home > 0.5) == (wins > 0.5)) > 0.58
    log_loss = -np.mean(wins * np.log(p_home) + (1 - wins) * np.log(1 - p_home))
    assert log_loss < np.log(2) - 0.01
    assert np.corrcoef(mu, fs.margin[test])[0, 1] > 0.2
    assert 8.0 < params["sigma"] < 16.0  # the synthetic noise sd is 11


def test_json_round_trip_gives_identical_predictions(trained):
    _, fs, _, params = trained
    reloaded = json.loads(json.dumps(params))
    a = MarginFeaturesModel(params).predict_matrix(fs.X)
    b = MarginFeaturesModel(reloaded).predict_matrix(fs.X)
    assert np.array_equal(a[0], b[0]) and np.array_equal(a[1], b[1])


def test_training_is_deterministic_for_a_seed(trained):
    _, fs, train, params = trained
    assert fit_on_feature_set(fs, train, seed=42, trained_through=params["trained_through"] and date.fromisoformat(params["trained_through"]), seasons=["s1", "s2"]) == params


def test_a_single_season_falls_back_to_default_penalties():
    fs = build_feature_set(make_league(n_seasons=1, n_teams=8, seed=1))[0]
    params = fit_on_feature_set(fs, np.ones(len(fs), dtype=bool), seed=1)
    assert params["ridge"]["alpha"] == 300.0 and params["logistic"]["C"] == 0.1 and params["sigma"] > 0


def test_malformed_or_mismatched_params_are_rejected(trained):
    _, _, _, params = trained
    with pytest.raises(model_registry.ModelRegistryError):
        MarginFeaturesModel({})
    with pytest.raises(model_registry.ModelRegistryError):
        MarginFeaturesModel({**params, "feature_names": ["elo_edge"]})
    with pytest.raises(model_registry.ModelRegistryError):
        MarginFeaturesModel({**params, "sigma": 0})


def test_inference_does_not_need_scikit_learn(trained, monkeypatch):
    tree = ast.parse(Path(inspect.getsourcefile(margin_features_model)).read_text(encoding="utf-8"))
    top_level = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
    assert not any("sklearn" in ast.dump(n) for n in top_level)  # only the training function imports it

    for name in ("sklearn", "sklearn.linear_model"):
        monkeypatch.setitem(sys.modules, name, None)  # any import now raises ImportError
    _, fs, _, params = trained
    prediction = MarginFeaturesModel(params).predict_vector(fs.X[0])
    assert 0.0 < prediction.p_home < 1.0


def test_nba_date_maps_evening_tipoffs_to_the_local_calendar_date():
    assert nba_date(datetime(2026, 1, 16, 0, 30, tzinfo=timezone.utc)) == date(2026, 1, 15)  # 7:30 pm ET
    assert nba_date(datetime(2026, 1, 16, 3, 0, tzinfo=timezone.utc)) == date(2026, 1, 15)  # 10 pm ET
    assert nba_date(datetime(2026, 1, 15, 17, 0, tzinfo=timezone.utc)) == date(2026, 1, 15)  # noon ET


# ------------------------------------------------------------------------------------- the family

def _register_world(world):
    """Eight games over two seasons between ATL, BOS, BKN, NOP (home/away alternating)."""
    schedule = [
        ("0020300001", "2003-04", "ATL", "BOS", 100, 95),
        ("0020300002", "2003-04", "BKN", "NOP", 90, 99),
        ("0020300003", "2003-04", "BOS", "BKN", 110, 100),
        ("0020300004", "2003-04", "NOP", "ATL", 97, 101),
        ("0020400001", "2004-05", "ATL", "BKN", 88, 102),
        ("0020400002", "2004-05", "BOS", "NOP", 105, 90),
    ]
    start = date(2003, 11, 1)
    for i, (game_id, season, home, away, hp, ap) in enumerate(schedule):
        add_game(world, game_id, start + timedelta(days=i * 90), season, home, away, hp, ap)


def _model_row(session, trained):
    row = ModelVersion(name=FAMILY_NAME, version="lab-test", params=trained[3], role="challenger")
    session.add(row)
    session.commit()
    return row


def test_the_family_is_registered_and_loadable_through_the_registry(world, trained):
    session = world["session"]
    _register_world(world)
    row = _model_row(session, trained)

    family = model_registry.load_model(session, row)

    assert isinstance(family, MarginFeaturesFamily)
    assert (family.name, family.version, family.model_version_id) == (FAMILY_NAME, "lab-test", row.id)
    teams, season = world["teams"], world["seasons"]["2004-05"]
    tipoff = datetime(2005, 2, 1, 1, 0, tzinfo=timezone.utc)  # evening of 2005-01-31
    prediction = family.predict(teams["ATL"], teams["BOS"], season, tipoff)
    assert prediction is not None and 0.0 < prediction.p_home < 1.0 and prediction.sigma == trained[3]["sigma"]


def test_the_family_uses_the_same_vector_as_the_training_pass(world, trained):
    session = world["session"]
    _register_world(world)
    family = model_registry.load_model(session, _model_row(session, trained))
    games = family._history()[0]
    feature_set = build_feature_set(games)[0]
    model = MarginFeaturesModel(trained[3])

    seen = set()
    for i, game in enumerate(games):
        tipoff = datetime.combine(game.game_date, time(23, 0), tzinfo=timezone.utc)
        got = family.predict(game.home_team_id, game.away_team_id, game.season_id, tipoff)
        if {game.home_team_id, game.away_team_id} <= seen:
            expected_p, expected_mu = model.predict_matrix(feature_set.X[i])
            assert got.p_home == pytest.approx(float(expected_p[0])) and got.mu == pytest.approx(float(expected_mu[0]))
        else:
            assert got is None  # a team without earlier games cannot be predicted
        seen |= {game.home_team_id, game.away_team_id}


def test_an_upcoming_game_after_all_the_history_uses_the_full_state(world, trained):
    session = world["session"]
    _register_world(world)
    family = model_registry.load_model(session, _model_row(session, trained))
    games, state = family._history()
    teams, season = world["teams"], world["seasons"]["2004-05"]
    day = games[-1].game_date + timedelta(days=3)

    got = family.predict(teams["ATL"], teams["BOS"], season, datetime.combine(day, time(23, 0), tzinfo=timezone.utc))

    expected = MarginFeaturesModel(trained[3]).predict_vector(state.vector(teams["ATL"], teams["BOS"], season, day))
    assert got == expected
    assert family._past is None  # no restricted history had to be built


def test_a_team_without_history_cannot_be_predicted(world, trained):
    session = world["session"]
    _register_world(world)
    family = model_registry.load_model(session, _model_row(session, trained))
    teams = world["teams"]
    tipoff = datetime(2005, 2, 1, 1, 0, tzinfo=timezone.utc)

    assert family.predict(teams["EST"], teams["ATL"], world["seasons"]["2004-05"], tipoff) is None
    assert family.predict(teams["ATL"], 987654, world["seasons"]["2004-05"], tipoff) is None
