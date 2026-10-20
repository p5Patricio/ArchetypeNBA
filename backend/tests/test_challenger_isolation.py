"""A challenger can never break the champion: its failures are contained, logged and counted."""
from decimal import Decimal

import numpy as np
import pytest
from sqlmodel import select

from app.models import BetSide, MarketType, ModelPrediction, ModelVersion, SimulatedBet
from app.services import margin_features_model, model_registry
from app.services.margin_features_model import FEATURE_NAMES
from app.services.model_registry import ModelRegistryError, Prediction, load_model
from tests.test_prediction_recorder import NOW, World, american  # noqa: F401
from tests.test_shadow_predictions import _challenger, _champion, _of


@pytest.fixture
def world(db_session):
    return World(db_session)


class _Family:
    """A configurable fake family: ``behaviour(session, game_index)`` runs inside ``predict``."""

    behaviour = None

    def __init__(self, session, model_version):
        self.name, self.version, self.model_version_id = model_version.name, model_version.version, model_version.id
        self._session = session
        self._calls = 0

    def predict(self, home_team_id, away_team_id, season_id, game_time):
        index, self._calls = self._calls, self._calls + 1
        if type(self).behaviour is not None:
            type(self).behaviour(self._session, index)
        return Prediction(0.6, 3.0, 12.0)


def _register(monkeypatch, name, behaviour=None, factory=None):
    family = type(f"Family_{name}", (_Family,), {"behaviour": staticmethod(behaviour) if behaviour else None})
    monkeypatch.setitem(model_registry._FAMILIES, name, factory or family)


def _fake_challenger(session, name, params=None):
    row = ModelVersion(name=name, version="1", role="challenger", params=params or {})
    session.add(row)
    session.commit()
    return row


def _setup_game_with_edge(world):
    game = world.game()
    world.h2h(game, "pinnacle", -170, 145)
    return game


def _assert_champion_intact(session, game):
    champion = _champion(session)
    assert len(_of(session, champion)) == 2
    bets = session.exec(select(SimulatedBet)).all()
    assert bets
    assert {session.get(ModelPrediction, b.prediction_id).model_version_id for b in bets} == {champion.id}
    return len(bets)


def _bad_prediction(session):
    """An insert the database rejects (probability outside (0, 1))."""
    champion = session.exec(select(ModelVersion).where(ModelVersion.version == "1.1")).one()
    game_id = session.exec(select(ModelPrediction.game_id)).first()
    session.add(
        ModelPrediction(
            model_version_id=champion.id, game_id=game_id or 1, market=MarketType.h2h, side=BetSide.home,
            model_prob=Decimal("5.0"), predicted_at=NOW,
        )
    )
    session.flush()


# --- the registry ---------------------------------------------------------------------------------


def test_a_family_module_that_cannot_be_imported_raises_the_registry_error(db_session, monkeypatch):
    monkeypatch.delitem(model_registry._FAMILIES, "margin_features", raising=False)
    monkeypatch.setitem(model_registry._FAMILY_MODULES, "margin_features", "app.services.no_such_module")
    row = ModelVersion(name="margin_features", version="9", role="challenger", params={})

    with pytest.raises(ModelRegistryError, match="cannot import"):
        load_model(db_session, row)


def test_a_family_that_fails_to_construct_raises_the_registry_error(db_session, monkeypatch):
    def exploding(session, model_version):
        raise RuntimeError("boom")

    monkeypatch.setitem(model_registry._FAMILIES, "exploding", exploding)

    with pytest.raises(ModelRegistryError, match="cannot build"):
        load_model(db_session, ModelVersion(name="exploding", version="1", params={}))


# --- the recorder ---------------------------------------------------------------------------------


def test_a_challenger_whose_family_import_fails_does_not_touch_the_champion(world, db_session, monkeypatch):
    game = _setup_game_with_edge(world)
    monkeypatch.delitem(model_registry._FAMILIES, "margin_features", raising=False)
    monkeypatch.setitem(model_registry._FAMILY_MODULES, "margin_features", "app.services.no_such_module")
    broken = _fake_challenger(db_session, "margin_features")

    summary = world.recorder().run()

    assert summary.skipped["challenger_unusable"] == 1 and broken.id not in summary.models
    _assert_champion_intact(db_session, game)


def test_a_family_that_blows_up_while_loading_is_counted_as_an_error(world, db_session, monkeypatch):
    game = _setup_game_with_edge(world)
    # load_model wraps constructor failures, so make the loader itself fail in a way it does not wrap
    def exploding_loader(session, row):
        raise RuntimeError("database is locked")

    monkeypatch.setattr(model_registry, "load_model", lambda session, row: (
        exploding_loader(session, row) if row.name == "boom" else load_model(session, row)
    ))
    _fake_challenger(db_session, "boom")

    summary = world.recorder().run()

    assert summary.skipped["challenger_error"] == 1
    _assert_champion_intact(db_session, game)


def test_a_challenger_with_wrongly_shaped_params_does_not_touch_the_champion(world, db_session, monkeypatch):
    game = _setup_game_with_edge(world)
    n = len(FEATURE_NAMES)
    params = {
        "feature_names": list(FEATURE_NAMES), "mean": [0.0] * n, "scale": [1.0] * n,
        "ridge": {"coef": [1.0, 2.0], "intercept": 0.0},  # wrong length: fails inside predict
        "logistic": {"coef": [0.0] * n, "intercept": 0.0}, "sigma": 12.0,
    }
    row = ModelVersion(name="margin_features", version="1", role="challenger", params=params)
    db_session.add(row)
    db_session.commit()

    class _State:
        def team_last_game_date(self, team_id):
            return None

        def knows(self, team_id):
            return True

        def vector(self, home, away, season_id, day):
            return np.zeros(n)

    monkeypatch.setattr(margin_features_model.MarginFeaturesFamily, "_history", lambda self: ([], _State()))

    summary = world.recorder().run()

    assert summary.skipped["challenger_error"] == 1 and summary.models[row.id].errors == 1
    assert _of(db_session, row) == []
    _assert_champion_intact(db_session, game)


def test_a_challenger_whose_predict_raises_does_not_touch_the_champion(world, db_session, monkeypatch):
    game = _setup_game_with_edge(world)

    def explode(session, index):
        raise ValueError("matmul shape mismatch")

    _register(monkeypatch, "raiser", explode)
    row = _fake_challenger(db_session, "raiser")

    summary = world.recorder().run()

    assert summary.skipped["challenger_error"] == 1
    assert summary.models[row.id].errors == 1 and summary.models[row.id].predictions_written == 0
    assert _of(db_session, row) == []
    _assert_champion_intact(db_session, game)


def test_a_database_error_inside_a_challenger_leaves_the_session_usable(world, db_session, monkeypatch):
    game = _setup_game_with_edge(world)
    _register(monkeypatch, "db_breaker", lambda session, index: _bad_prediction(session))
    breaker = _fake_challenger(db_session, "db_breaker")
    healthy = _challenger(world)  # a later challenger, created after the failing one

    summary = world.recorder().run()

    assert summary.skipped["challenger_error"] == 1 and summary.models[breaker.id].errors == 1
    assert _of(db_session, breaker) == []
    assert len(_of(db_session, healthy)) == 2 and summary.models[healthy.id].errors == 0
    bets = _assert_champion_intact(db_session, game)
    # the session is not left in a failed transaction: it can still write and commit
    db_session.add(ModelVersion(name="after", version="1", role="retired", params={}))
    db_session.commit()
    assert len(db_session.exec(select(SimulatedBet)).all()) == bets


def test_a_challenger_that_fails_on_a_later_game_leaves_no_partial_writes(world, db_session, monkeypatch):
    game_one = _setup_game_with_edge(world)
    world.game(home="CCC", away="DDD", hours=6.0)

    def fail_on_second(session, index):
        if index == 1:
            raise RuntimeError("second game")

    _register(monkeypatch, "half", fail_on_second)
    half = _fake_challenger(db_session, "half")

    summary = world.recorder().run()

    assert summary.skipped["challenger_error"] == 1
    assert _of(db_session, half) == []  # the first game's rows were rolled back with the rest
    assert len(_of(db_session, _champion(db_session))) == 4
    assert game_one.id is not None


def test_a_healthy_challenger_next_to_a_failing_one_still_records_and_reruns_are_idempotent(
    world, db_session, monkeypatch
):
    game = _setup_game_with_edge(world)
    _register(monkeypatch, "raiser", lambda session, index: (_ for _ in ()).throw(RuntimeError("no")))
    failing = _fake_challenger(db_session, "raiser")
    healthy = _challenger(world)

    first = world.recorder().run()
    count = len(db_session.exec(select(ModelPrediction)).all())
    bets = len(db_session.exec(select(SimulatedBet)).all())
    second = world.recorder().run()

    assert count == 4 and len(_of(db_session, healthy)) == 2 and _of(db_session, failing) == []
    assert first.skipped["challenger_error"] == second.skipped["challenger_error"] == 1
    assert len(db_session.exec(select(ModelPrediction)).all()) == count
    assert len(db_session.exec(select(SimulatedBet)).all()) == bets
    assert second.predictions_written == 0 and second.models[healthy.id].predictions_written == 0
    assert second.models[healthy.id].predictions_existing == 2
    _assert_champion_intact(db_session, game)


def test_a_failing_challenger_on_a_dry_run_writes_nothing_and_is_counted(world, db_session, monkeypatch):
    _setup_game_with_edge(world)

    def explode(session, index):
        raise ValueError("no")

    _register(monkeypatch, "raiser", explode)
    _fake_challenger(db_session, "raiser")

    summary = world.recorder().run(dry_run=True)

    assert summary.skipped["challenger_error"] == 1
    assert db_session.exec(select(ModelPrediction)).all() == []


def test_a_champion_failure_still_propagates(world, db_session, monkeypatch):
    _setup_game_with_edge(world)

    def explode(*args, **kwargs):
        raise RuntimeError("champion broke")

    monkeypatch.setattr("app.services.prediction_recorder.PredictionRecorder._record_game", explode)

    with pytest.raises(RuntimeError, match="champion broke"):
        world.recorder().run()
    assert db_session.exec(select(ModelPrediction)).all() == []
