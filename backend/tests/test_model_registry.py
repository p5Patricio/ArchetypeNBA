"""The model family registry: roles, loading a family from model_version.params and the Elo family."""
from datetime import date, datetime, timezone

import pytest

from app.analytics import elo
from app.models import ModelVersion
from app.services import model_registry
from app.services.elo_service import EloRatingService
from app.services.model_registry import ModelRegistryError, Prediction, load_model
from tests.test_elo_backfill_service import add_game, world  # noqa: F401

GAME_TIME = datetime(2026, 10, 20, 23, 0, tzinfo=timezone.utc)


def _add(session, version, role="challenger", name="elo_538", params=None):
    row = ModelVersion(name=name, version=version, role=role, params=params if params is not None else {"sigma": 14.0})
    session.add(row)
    session.commit()
    return row


def test_list_active_is_the_champion_then_the_challengers_without_retired_models(db_session):
    first = _add(db_session, "a", "challenger")
    champion = _add(db_session, "b", "champion")
    _add(db_session, "r", "retired")
    last = _add(db_session, "c", "challenger")

    assert model_registry.get_champion(db_session).id == champion.id
    assert [m.id for m in model_registry.list_active(db_session)] == [champion.id, first.id, last.id]


def test_an_empty_registry_has_no_champion_and_nothing_active(db_session):
    assert model_registry.get_champion(db_session) is None
    assert model_registry.list_active(db_session) == []


def test_ensure_default_champion_registers_once(db_session):
    first = model_registry.ensure_default_champion(db_session)
    again = model_registry.ensure_default_champion(db_session)

    assert first.id == again.id
    assert (first.name, first.version, first.role) == ("elo_538", "1.1", "champion")


def test_an_unknown_family_cannot_be_loaded(db_session):
    row = _add(db_session, "1", name="crystal_ball")

    with pytest.raises(ModelRegistryError, match="unknown model family"):
        load_model(db_session, row)


def test_the_elo_family_requires_a_sigma(db_session):
    row = _add(db_session, "1", params={"K": 20.0})

    with pytest.raises(ModelRegistryError, match="no sigma"):
        load_model(db_session, row)


def test_a_new_family_can_be_registered(db_session):
    class Constant:
        def __init__(self, session, model_version):
            self.name, self.version, self.model_version_id = model_version.name, model_version.version, model_version.id

        def predict(self, home_team_id, away_team_id, season_id, game_time):
            return Prediction(0.5, 0.0, 12.0)

    model_registry.register_family("constant_test", Constant)
    try:
        family = load_model(db_session, _add(db_session, "1", name="constant_test"))
        assert family.predict(1, 2, 3, GAME_TIME) == Prediction(0.5, 0.0, 12.0)
    finally:
        model_registry._FAMILIES.pop("constant_test")


def test_the_elo_family_predicts_like_the_rating_service(world):
    session = world["session"]
    row = _add(session, "1.1", "champion", params={"sigma": 13.5})
    add_game(world, "0020300001", date(2004, 4, 1), "2003-04", "ATL", "BOS", 110, 100)
    service = EloRatingService(session, model_version_id=row.id)
    service.rebuild_all()
    atl, bos = world["teams"]["ATL"], world["teams"]["BOS"]
    ratings = service.current_ratings(for_season_id=world["seasons"]["2004-05"])

    family = load_model(session, row)
    prediction = family.predict(atl, bos, world["seasons"]["2004-05"], GAME_TIME)

    assert (family.name, family.version, family.model_version_id) == ("elo_538", "1.1", row.id)
    expected = service.predict(atl, bos, ratings)
    assert prediction == Prediction(expected.p_home, expected.expected_margin, 13.5)
    assert prediction.mu == pytest.approx(elo.expected_margin(ratings[atl], ratings[bos]))


def test_the_elo_family_returns_none_for_a_team_without_ratings(world):
    session = world["session"]
    row = _add(session, "1.1", "champion")
    add_game(world, "0020300001", date(2004, 4, 1), "2003-04", "ATL", "BOS", 110, 100)
    EloRatingService(session, model_version_id=row.id).rebuild_all()

    family = load_model(session, row)

    assert family.predict(world["teams"]["ATL"], world["teams"]["NOP"], world["seasons"]["2003-04"], GAME_TIME) is None


def test_the_elo_family_uses_its_own_hyperparameters(world):
    session = world["session"]
    default = _add(session, "1.1", "champion")
    tuned = _add(session, "2.0", params={"sigma": 14.0, "home_advantage": 100.0, "elo_per_point": 20.0})
    add_game(world, "0020300001", date(2004, 4, 1), "2003-04", "ATL", "BOS", 110, 100)
    for row in (default, tuned):
        EloRatingService(session, model_version_id=row.id).rebuild_all()
    atl, bos, season = world["teams"]["ATL"], world["teams"]["BOS"], world["seasons"]["2003-04"]

    a = load_model(session, default).predict(atl, bos, season, GAME_TIME)
    b = load_model(session, tuned).predict(atl, bos, season, GAME_TIME)

    assert b.p_home > a.p_home and b.mu > a.mu
