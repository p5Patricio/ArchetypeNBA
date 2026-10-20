"""Challengers record shadow predictions next to the champion; only the champion bets."""
from datetime import date
from decimal import Decimal

import pytest
from sqlmodel import select

from app.analytics import elo
from app.models import BetSide, MarketType, ModelPrediction, ModelVersion, SimulatedBet, TeamEloRating
from tests.test_prediction_recorder import NOW, RATINGS, SIGMA, World, american  # noqa: F401

CHALLENGER_PARAMS = {"sigma": 13.0, "home_advantage": 100.0, "elo_per_point": 25.0}


@pytest.fixture
def world(db_session):
    return World(db_session)


def _challenger(world, version="2.0", role="challenger", params=None, ratings=RATINGS):
    session = world.session
    row = ModelVersion(name="elo_538", version=version, role=role, params=params or dict(CHALLENGER_PARAMS))
    session.add(row)
    session.commit()
    for i, (abbr, rating) in enumerate(ratings.items()):
        session.add(
            TeamEloRating(
                model_version_id=row.id, team_id=world.teams[abbr].id, season_id=world.old.id,
                game_id=f"00225{i:05d}", game_date=date(2026, 4, 10), rating_after=rating,
            )
        )
    session.commit()
    return row


def _of(session, model):
    return session.exec(select(ModelPrediction).where(ModelPrediction.model_version_id == model.id)).all()


def _by_target(rows):
    return {(p.market, p.side, None if p.line is None else float(p.line)): p for p in rows}


def _champion(session):
    return session.exec(select(ModelVersion).where(ModelVersion.version == "1.1")).one()


def test_a_challenger_records_the_same_targets_with_its_own_numbers(world, db_session):
    game = world.game()
    world.spread(game, "pinnacle", -3.5, -110, -110)
    challenger = _challenger(world)

    summary = world.recorder().run()

    champion_preds, challenger_preds = _by_target(_of(db_session, _champion(db_session))), _by_target(_of(db_session, challenger))
    assert set(challenger_preds) == set(champion_preds) and len(challenger_preds) == 4
    mu = elo.expected_margin(elo.season_carryover(1600.0), elo.season_carryover(1500.0), 100.0, 25.0)
    p_home = elo.expected_home_win_prob(elo.season_carryover(1600.0), elo.season_carryover(1500.0), 100.0)
    home = challenger_preds[(MarketType.h2h, BetSide.home, None)]
    assert float(home.model_prob) == pytest.approx(p_home, abs=1e-5)
    assert float(home.projection) == pytest.approx(mu, abs=0.01)
    assert float(home.model_prob) != float(champion_preds[(MarketType.h2h, BetSide.home, None)].model_prob)
    p_cover, _, _ = elo.spread_probabilities(mu, 13.0, -3.5)
    assert float(challenger_preds[(MarketType.spreads, BetSide.home, -3.5)].model_prob) == pytest.approx(p_cover, abs=1e-5)
    assert all(p.predicted_at is not None and p.game_id == game.id for p in challenger_preds.values())

    stats = summary.models
    assert [s.role for s in stats.values()] == ["champion", "challenger"]
    assert stats[challenger.id].games_predicted == 1 and stats[challenger.id].predictions_written == 4
    assert summary.predictions_written == 4  # the top-level counters stay the champion's


def test_only_the_champion_bets(world, db_session):
    game = world.game()
    world.h2h(game, "pinnacle", -170, 145)
    # a challenger that loves the away side so much that it would also find an edge
    _challenger(world, params={"sigma": 13.0, "home_advantage": -200.0})

    world.recorder().run()

    champion = _champion(db_session)
    bets = db_session.exec(select(SimulatedBet)).all()
    assert bets
    assert {db_session.get(ModelPrediction, b.prediction_id).model_version_id for b in bets} == {champion.id}


def test_with_a_challenger_the_champions_predictions_and_bets_are_unchanged(world, db_session):
    def run_world():
        game = world.game()
        world.h2h(game, "pinnacle", -170, 145)
        world.h2h(game, "draftkings", -160, 150)
        world.spread(game, "pinnacle", -3.5, -110, -110)
        world.spread(game, "draftkings", -3.5, -105, -115)
        return game

    run_world()
    world.recorder().run()
    champion = _champion(db_session)

    def snapshot():
        preds = sorted(
            (p.game_id, p.market.value, p.side.value, p.line, p.model_prob, p.projection) for p in _of(db_session, champion)
        )
        bets = sorted(
            (b.strategy.value, b.price_taken, b.line_taken, b.stake_units, b.bankroll_before, b.ev_per_unit)
            for b in db_session.exec(select(SimulatedBet)).all()
        )
        return preds, bets

    alone = snapshot()
    for table in (SimulatedBet, ModelPrediction):
        for row in db_session.exec(select(table)).all():
            db_session.delete(row)
    db_session.commit()

    _challenger(world)
    world.recorder().run()

    assert snapshot() == alone


def test_a_second_run_is_idempotent_for_every_model(world, db_session):
    game = world.game()
    world.spread(game, "pinnacle", -3.5, -110, -110)
    challenger = _challenger(world)
    world.recorder().run()
    count = len(db_session.exec(select(ModelPrediction)).all())

    again = world.recorder().run()

    assert len(db_session.exec(select(ModelPrediction)).all()) == count == 8
    assert again.predictions_written == 0 and again.predictions_existing == 4
    assert again.models[challenger.id].predictions_written == 0 and again.models[challenger.id].predictions_existing == 4


def test_a_dry_run_writes_nothing_for_challengers_either(world, db_session):
    world.game()
    challenger = _challenger(world)

    dry = world.recorder().run(dry_run=True)

    assert db_session.exec(select(ModelPrediction)).all() == []
    assert dry.models[challenger.id].predictions_written == 2
    assert world.recorder().run().models[challenger.id].predictions_written == 2


def test_a_challenger_with_missing_ratings_is_skipped_without_affecting_the_champion(world, db_session):
    world.game()
    challenger = _challenger(world, ratings={"BBB": 1500.0, "CCC": 1550.0})  # no rating for AAA

    summary = world.recorder().run()

    assert _of(db_session, challenger) == []
    assert summary.models[challenger.id].skipped_missing_ratings == 1
    assert summary.models[challenger.id].games_predicted == 0
    assert len(_of(db_session, _champion(db_session))) == 2 and summary.skipped["missing_ratings"] == 0


def test_a_challenger_is_recorded_even_when_the_champion_cannot_predict_the_game(world, db_session):
    world.game(home="AAA", away="EEE")  # EEE has no rating for the champion
    challenger = _challenger(world, ratings={**RATINGS, "EEE": 1450.0})

    summary = world.recorder().run()

    assert summary.skipped["missing_ratings"] == 1 and summary.games_processed == 0
    assert _of(db_session, _champion(db_session)) == []
    assert len(_of(db_session, challenger)) == 2


def test_retired_models_are_ignored(world, db_session):
    world.game()
    retired = _challenger(world, version="0.9", role="retired")

    summary = world.recorder().run()

    assert _of(db_session, retired) == [] and retired.id not in summary.models


def test_an_unusable_challenger_is_skipped_and_counted(world, db_session):
    world.game()
    broken_sigma = _challenger(world, version="2.1", params={"K": 20.0})
    unknown = ModelVersion(name="crystal_ball", version="1", params={"sigma": 12.0})
    db_session.add(unknown)
    db_session.commit()

    summary = world.recorder().run()

    assert summary.skipped["challenger_unusable"] == 2
    assert _of(db_session, broken_sigma) == [] and _of(db_session, unknown) == []
    assert len(_of(db_session, _champion(db_session))) == 2


def test_the_champion_without_sigma_still_stops_the_recorder(world, db_session):
    from app.services.prediction_recorder import RecorderError

    champion = _champion(db_session)
    champion.params = {}
    db_session.add(champion)
    db_session.commit()
    world.game()

    with pytest.raises(RecorderError, match="no sigma"):
        world.recorder().run()


def test_a_role_based_champion_wins_over_the_legacy_row(world, db_session):
    world.game()
    legacy = _champion(db_session)
    new_champion = _challenger(world, version="3.0", role="champion", params={"sigma": 13.0})

    summary = world.recorder().run()

    assert list(summary.models) == [new_champion.id, legacy.id]
    assert summary.models[legacy.id].role == "challenger"
    assert len(_of(db_session, new_champion)) == 2 and len(_of(db_session, legacy)) == 2


def test_the_record_cli_summary_lists_each_model(world):
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "scripts" / "record_predictions.py"
    spec = importlib.util.spec_from_file_location("record_predictions_cli", path)
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    world.game()
    only_champion = cli.format_summary(world.recorder().run(dry_run=True))
    _challenger(world)

    text = cli.format_summary(world.recorder().run(dry_run=True))

    assert "models (only the champion bets):" not in only_champion
    assert "models (only the champion bets):" in text and "challenger" in text and "champion" in text
