"""Parameterized Elo: the default hyperparameters reproduce the historical numbers exactly."""
from datetime import date

import pytest
from sqlmodel import select

from app.analytics import elo
from app.models import ModelVersion, Team, TeamEloRating
from app.services.elo_service import EloRatingService, replay_games, update_active_models
from tests.test_elo_backfill_service import add_game, populate_three_seasons, world  # noqa: F401

# (game_id, team, rating_before, rating_after, win_probability, result, k_factor) produced by the pre-parameter
# code on populate_three_seasons; the refactor must reproduce every float exactly.
GOLDEN_ROWS = [
    ('0020300001', 'ATL', 1500.0, 1505.5667966668536, 0.5854986786718095, 'W', 20.0),
    ('0020300001', 'BOS', 1500.0, 1494.4332033331464, 0.4145013213281905, 'L', 20.0),
    ('0020300002', 'BKN', 1500.0, 1488.027007787243, 0.5854986786718095, 'L', 20.0),
    ('0020300002', 'NOP', 1500.0, 1511.972992212757, 0.4145013213281905, 'W', 20.0),
    ('0020300003', 'BOS', 1494.4332033331464, 1502.4264068137102, 0.5944192263704046, 'W', 20.0),
    ('0020300003', 'BKN', 1488.027007787243, 1480.0338043066793, 0.40558077362959544, 'L', 20.0),
    ('0020300004', 'ATL', 1505.5667966668536, 1513.5072873820952, 0.40558077362959544, 'W', 20.0),
    ('0020300004', 'NOP', 1511.972992212757, 1504.0325014975153, 0.5944192263704046, 'L', 20.0),
    ('0020400001', 'ATL', 1511.3804655365714, 1494.2644919550191, 0.6200839128959569, 'L', 20.0),
    ('0020400001', 'BKN', 1486.2753532300094, 1503.3913268115616, 0.3799160871040431, 'W', 20.0),
    ('0020400002', 'BOS', 1503.0698051102827, 1513.7729536119123, 0.5838148583283318, 'W', 20.0),
    ('0020400002', 'NOP', 1504.2743761231366, 1493.571227621507, 0.4161851416716682, 'L', 20.0),
    ('0020400003', 'ATL', 1494.2644919550191, 1491.1865408679928, 0.4018107308103287, 'L', 20.0),
    ('0020400003', 'BKN', 1503.3913268115616, 1506.469277898588, 0.5981892691896713, 'W', 20.0),
    ('0020400004', 'BOS', 1513.7729536119123, 1525.7142215040367, 0.442974878112802, 'W', 20.0),
    ('0020400004', 'NOP', 1493.571227621507, 1481.6299597293826, 0.557025121887198, 'L', 20.0),
    ('0020500001', 'BKN', 1506.101958423941, 1518.0834832984053, 0.6112638162068649, 'W', 20.0),
    ('0020500001', 'NOP', 1487.4724697970369, 1475.4909449225725, 0.3887361837931351, 'L', 20.0),
    ('0020500002', 'ATL', 1494.6399056509945, 1488.33011771006, 0.5489229167563963, 'L', 20.0),
    ('0020500002', 'BOS', 1520.5356661280275, 1526.845454068962, 0.45107708324360374, 'W', 20.0),
    ('0020500003', 'ATL', 1488.33011771006, 1502.781168687645, 0.43254390518933017, 'W', 20.0),
    ('0020500003', 'NOP', 1475.4909449225725, 1461.0398939449874, 0.5674560948106698, 'L', 20.0),
    ('0020500004', 'BOS', 1526.845454068962, 1531.109287945575, 0.5976843331406068, 'W', 20.0),
    ('0020500004', 'BKN', 1518.0834832984053, 1513.8196494217923, 0.40231566685939324, 'L', 20.0),
]


def _dump(session, model_id=None):
    abbr = {t.id: t.abbreviation for t in session.exec(select(Team)).all()}
    stmt = select(TeamEloRating).order_by(TeamEloRating.game_date, TeamEloRating.game_id, TeamEloRating.team_id)
    if model_id is not None:
        stmt = stmt.where(TeamEloRating.model_version_id == model_id)
    return [
        (r.game_id, abbr[r.team_id], r.rating_before, r.rating_after, r.win_probability, r.result, r.k_factor)
        for r in session.exec(stmt).all()
    ]


# --- EloParams ---------------------------------------------------------------------------------------


def test_default_params_are_the_module_constants():
    params = elo.EloParams()
    assert (params.k, params.home_advantage, params.initial_rating) == (elo.K, elo.HOME_ADVANTAGE, elo.INITIAL_RATING)
    assert (params.carryover, params.mean_rating) == (elo.CARRYOVER, elo.MEAN_RATING)
    assert (params.elo_per_point, params.mov_exponent) == (elo.ELO_PER_POINT, 0.8)
    assert params == elo.DEFAULT_PARAMS


def test_params_round_trip_and_tolerate_partial_rows():
    custom = elo.EloParams(k=25.0, home_advantage=80.0, carryover=0.7, mov_exponent=0.9)
    assert elo.EloParams.from_dict(custom.to_dict()) == custom
    assert custom.to_dict()["K"] == 25.0  # historical key name

    registered_row = {"sigma": 14.14, "K": 20.0, "trained_through": "2026-04-12", "home_advantage": None}
    assert elo.EloParams.from_dict(registered_row) == elo.DEFAULT_PARAMS  # missing/null keys, unknown keys ignored
    assert elo.EloParams.from_dict({}) == elo.EloParams.from_dict(None) == elo.DEFAULT_PARAMS


def test_the_pure_functions_accept_explicit_hyperparameters():
    base = elo.update_ratings(1550, 1480, 110, 100)
    assert elo.update_ratings(1550, 1480, 110, 100, elo.K, elo.HOME_ADVANTAGE, elo.MOV_EXPONENT) == base

    doubled_k = elo.update_ratings(1550, 1480, 110, 100, k=2 * elo.K)
    assert doubled_k[0] - 1550 == pytest.approx(2 * (base[0] - 1550))
    assert elo.update_ratings(1550, 1480, 110, 100, home_advantage=100)[2] > base[2]
    assert elo.mov_multiplier(10, 0.0, exponent=1.0) == pytest.approx(13.0 / 7.5)
    assert elo.season_carryover(1600.0, 0.5, 1500.0) == pytest.approx(1550.0)
    assert elo.season_carryover(1600.0) == elo.CARRYOVER * 1600.0 + (1.0 - elo.CARRYOVER) * elo.MEAN_RATING
    assert elo.expected_margin(1560, 1500, 60, elo_per_point=20.0) == pytest.approx(6.0)


# --- equivalence with the pre-parameter behaviour --------------------------------------------------------


def test_default_params_reproduce_the_historical_rating_rows_exactly(world):
    populate_three_seasons(world)
    EloRatingService(world["session"]).rebuild_all()

    assert _dump(world["session"]) == GOLDEN_ROWS


def test_replay_with_explicit_default_params_equals_the_implicit_default(world):
    populate_three_seasons(world)
    games = EloRatingService(world["session"]).load_games()

    implicit, implicit_state = replay_games(games)
    explicit, explicit_state = replay_games(games, params=elo.EloParams())

    assert implicit == explicit and implicit_state == explicit_state


# --- a model with its own hyperparameters ------------------------------------------------------------------


def _champion_and_tuned_challenger(session):
    champion = ModelVersion(name="elo_538", version="1.1", role="champion", params={"sigma": 14.0})
    tuned = ModelVersion(
        name="elo_538", version="2.0", params={"sigma": 13.0, "K": 32.0, "home_advantage": 90.0, "carryover": 0.6,
                                                "mean_rating": 1500.0, "elo_per_point": 25.0, "mov_exponent": 0.7},
    )
    session.add_all([champion, tuned])
    session.commit()
    return champion, tuned


def test_a_challenger_with_other_params_writes_its_own_rows_and_leaves_the_champion_alone(world):
    session = world["session"]
    champion, tuned = _champion_and_tuned_challenger(session)
    populate_three_seasons(world)
    EloRatingService(session, model_version_id=champion.id).rebuild_all()
    champion_rows = _dump(session, champion.id)

    summary = EloRatingService(session, model_version_id=tuned.id).rebuild_all()

    assert summary.rows_written == 24
    assert _dump(session, champion.id) == champion_rows == GOLDEN_ROWS
    tuned_rows = _dump(session, tuned.id)
    assert len(tuned_rows) == 24
    assert {row[6] for row in tuned_rows} == {32.0}  # k_factor column follows the model
    assert [row[3] for row in tuned_rows] != [row[3] for row in GOLDEN_ROWS]
    first = tuned_rows[0]  # ATL beat BOS at home in the first game, from 1500 each
    expected_after, _, expected_p = elo.update_ratings(1500.0, 1500.0, 100, 95, 32.0, 90.0, 0.7)
    assert first[3] == pytest.approx(expected_after) and first[4] == pytest.approx(expected_p)


def test_the_model_params_drive_carryover_prediction_and_walk_forward(world):
    session = world["session"]
    champion, tuned = _champion_and_tuned_challenger(session)
    add_game(world, "0020300001", date(2004, 4, 1), "2003-04", "ATL", "BOS", 110, 100)
    service = EloRatingService(session, model_version_id=tuned.id)
    service.rebuild_all()
    atl, bos = world["teams"]["ATL"], world["teams"]["BOS"]
    raw = service.current_ratings()[atl]

    assert service.params == elo.EloParams.from_dict(tuned.params)
    assert service.current_ratings(for_season_id=world["seasons"]["2004-05"])[atl] == pytest.approx(
        elo.season_carryover(raw, 0.6, 1500.0)
    )
    prediction = service.predict(atl, bos, ratings={atl: 1560.0, bos: 1500.0})
    assert prediction.p_home == pytest.approx(elo.expected_home_win_prob(1560, 1500, 90.0))
    assert prediction.expected_margin == pytest.approx((1560 + 90.0 - 1500) / 25.0)
    assert prediction.sigma == 13.0

    (metrics,) = service.evaluate_walk_forward()
    p = elo.expected_home_win_prob(1500, 1500, 90.0)
    assert metrics.mae_margin == pytest.approx(abs(10 - elo.expected_margin(1500, 1500, 90.0, 25.0)))
    assert metrics.brier == pytest.approx((p - 1.0) ** 2)


def test_a_registered_row_with_only_some_keys_uses_the_defaults_for_the_rest(world):
    session = world["session"]
    legacy = ModelVersion(name="elo_538", version="1.1", role="champion", params={"sigma": 14.14, "K": 20.0})
    session.add(legacy)
    session.commit()

    assert EloRatingService(session).params == elo.DEFAULT_PARAMS


# --- rating every active model --------------------------------------------------------------------------


def test_update_active_models_rates_the_champion_and_each_active_elo_challenger(world):
    session = world["session"]
    champion, tuned = _champion_and_tuned_challenger(session)
    retired = ModelVersion(name="elo_538", version="0.9", role="retired", params={"sigma": 12.0})
    other_family = ModelVersion(name="margin_features", version="1", params={"sigma": 12.0})
    session.add_all([retired, other_family])
    session.commit()
    populate_three_seasons(world)

    updates = update_active_models(session)

    assert [(row.id, summary.rows_written) for row, summary in updates] == [(champion.id, 24), (tuned.id, 24)]
    assert _dump(session, champion.id) == GOLDEN_ROWS
    assert _dump(session, retired.id) == [] and _dump(session, other_family.id) == []

    again = update_active_models(session)
    assert [summary.rows_written for _, summary in again] == [0, 0]


def test_update_active_models_without_any_model_registers_the_default_champion(world):
    session = world["session"]
    populate_three_seasons(world)

    ((row, summary),) = update_active_models(session, dry_run=True)
    assert row is None and summary.rows_written == 24 and session.exec(select(ModelVersion)).all() == []

    ((row, summary),) = update_active_models(session)
    assert row is None and summary.rows_written == 24
    (model,) = session.exec(select(ModelVersion)).all()
    assert (model.name, model.role) == ("elo_538", "champion")
    assert _dump(session, model.id) == GOLDEN_ROWS


def test_a_failing_challenger_never_blocks_the_champion(world, monkeypatch):
    session = world["session"]
    champion, tuned = _champion_and_tuned_challenger(session)
    populate_three_seasons(world)
    original = EloRatingService.update_new_games

    def explode_for_the_challenger(self, dry_run=False):
        if self.model_version_id == tuned.id:
            raise RuntimeError("boom")
        return original(self, dry_run=dry_run)

    monkeypatch.setattr(EloRatingService, "update_new_games", explode_for_the_challenger)

    updates = update_active_models(session)

    assert [(row.id, summary.rows_written) for row, summary in updates] == [(champion.id, 24)]
    assert _dump(session, champion.id) == GOLDEN_ROWS and _dump(session, tuned.id) == []

    monkeypatch.setattr(
        EloRatingService, "update_new_games", lambda self, dry_run=False: (_ for _ in ()).throw(RuntimeError("champion boom"))
    )
    with pytest.raises(RuntimeError, match="champion boom"):
        update_active_models(session)
