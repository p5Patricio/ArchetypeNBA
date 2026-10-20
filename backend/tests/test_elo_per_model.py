"""Per-model Elo state: every model version keeps its own rows in team_elo_rating."""
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlmodel import select

from app.models import Game, ModelVersion, Season, Team, TeamEloRating
from app.repositories.historical import HistoricalRepository
from app.services import model_registry
from app.services.elo_service import EloRatingService
from app.services.results_sync import count_final_games_without_ratings
from tests.test_elo_backfill_service import add_game, populate_three_seasons, snapshot, world  # noqa: F401


def _rows(session, model_id):
    return session.exec(
        select(TeamEloRating)
        .where(TeamEloRating.model_version_id == model_id)
        .order_by(TeamEloRating.game_date, TeamEloRating.game_id, TeamEloRating.team_id)
    ).all()


def _two_models(session):
    champion = ModelVersion(name="elo_538", version="1.1", params={"sigma": 14.0}, role="champion")
    challenger = ModelVersion(name="elo_538", version="2.0", params={"sigma": 13.0}, role="challenger")
    session.add_all([champion, challenger])
    session.commit()
    return champion, challenger


def test_the_default_service_belongs_to_the_champion(world):
    session = world["session"]
    champion, challenger = _two_models(session)
    populate_three_seasons(world)

    EloRatingService(session).rebuild_all()

    assert len(_rows(session, champion.id)) == 24
    assert _rows(session, challenger.id) == []


def test_a_challenger_service_writes_its_own_rows_without_touching_the_champions(world):
    session = world["session"]
    champion, challenger = _two_models(session)
    populate_three_seasons(world)
    EloRatingService(session, model_version_id=champion.id).rebuild_all()
    champion_before = snapshot(session)

    summary = EloRatingService(session, model_version_id=challenger.id).rebuild_all()

    assert summary.rows_written == 24 and summary.rows_deleted == 0
    assert len(_rows(session, challenger.id)) == 24
    champion_after = [
        (r.team_id, r.season_id, r.game_id, r.rating_before, r.rating_after, r.result, r.win_probability)
        for r in _rows(session, champion.id)
    ]
    assert champion_after == champion_before  # rows of the champion are byte-for-byte the same


def test_a_rebuild_only_removes_stale_rows_of_its_own_model(world):
    session = world["session"]
    champion, challenger = _two_models(session)
    populate_three_seasons(world)
    stale = dict(team_id=world["teams"]["NJN"], season_id=world["seasons"]["2003-04"], game_id="0020300001")
    session.add_all([TeamEloRating(model_version_id=champion.id, **stale), TeamEloRating(model_version_id=challenger.id, **stale)])
    session.commit()

    summary = EloRatingService(session, model_version_id=champion.id).rebuild_all()

    assert summary.rows_deleted == 1
    assert world["teams"]["NJN"] in {r.team_id for r in _rows(session, challenger.id)}  # the challenger's row survives


def test_each_model_continues_from_its_own_state(world):
    session = world["session"]
    champion, challenger = _two_models(session)
    add_game(world, "0020300001", date(2003, 11, 1), "2003-04", "ATL", "BOS", 110, 100)
    EloRatingService(session, model_version_id=champion.id).rebuild_all()

    add_game(world, "0020300002", date(2003, 11, 3), "2003-04", "BOS", "ATL", 90, 100)
    only_challenger_sees_both = EloRatingService(session, model_version_id=challenger.id).update_new_games()
    champion_update = EloRatingService(session, model_version_id=champion.id).update_new_games()

    assert only_challenger_sees_both.games_used == 2 and not only_challenger_sees_both.rebuilt
    assert champion_update.games_used == 1  # only the game it has not rated yet
    assert len(_rows(session, champion.id)) == len(_rows(session, challenger.id)) == 4


def test_current_ratings_and_sigma_follow_the_model(world):
    session = world["session"]
    champion, challenger = _two_models(session)
    add_game(world, "0020300001", date(2003, 11, 1), "2003-04", "ATL", "BOS", 110, 100)
    EloRatingService(session, model_version_id=champion.id).rebuild_all()

    assert EloRatingService(session, model_version_id=champion.id).current_ratings()
    assert EloRatingService(session, model_version_id=challenger.id).current_ratings() == {}
    assert EloRatingService(session).load_sigma() == 14.0
    assert EloRatingService(session, model_version_id=challenger.id).load_sigma() == 13.0


def test_without_a_champion_the_legacy_model_is_used_and_a_rebuild_registers_it(world):
    session = world["session"]
    populate_three_seasons(world)
    assert model_registry.get_champion(session) is None
    assert EloRatingService(session).rebuild_all(dry_run=True).rows_written == 24
    assert session.exec(select(ModelVersion)).all() == []  # a dry run registers nothing

    EloRatingService(session).rebuild_all()

    (model,) = session.exec(select(ModelVersion)).all()
    assert (model.name, model.version, model.role) == ("elo_538", "1.1", "champion")
    assert len(_rows(session, model.id)) == 24


def test_a_legacy_row_without_a_role_acts_as_the_champion(world):
    session = world["session"]
    legacy = ModelVersion(name="elo_538", version="1.1", params={"sigma": 14.0})  # role defaults to challenger
    session.add(legacy)
    session.commit()

    assert model_registry.get_champion(session).id == legacy.id
    assert [m.id for m in model_registry.list_active(session)] == [legacy.id]  # not listed twice


def test_a_retired_model_is_never_the_champion_or_active(world):
    session = world["session"]
    champion, challenger = _two_models(session)
    challenger.role = "retired"
    session.add(challenger)
    session.commit()

    assert model_registry.get_champion(session).id == champion.id
    assert [m.id for m in model_registry.list_active(session)] == [champion.id]


def test_the_team_elo_timeline_api_reads_the_champion_only(world):
    session = world["session"]
    champion, challenger = _two_models(session)
    populate_three_seasons(world)
    EloRatingService(session, model_version_id=champion.id).rebuild_all()
    EloRatingService(session, model_version_id=challenger.id).rebuild_all()
    atl, season = world["teams"]["ATL"], world["seasons"]["2003-04"]

    timeline = HistoricalRepository(session).list_team_elo(atl, season)

    assert timeline and {row.model_version_id for row in timeline} == {champion.id}


def test_the_rating_catch_up_counts_games_the_champion_has_not_rated(db_session):
    season = Season(season_label="2026-27")
    home = Team(abbreviation="HHH", full_name="Home", city="H", conference="East", division="Atlantic")
    away = Team(abbreviation="AAA", full_name="Away", city="A", conference="West", division="Pacific")
    champion = ModelVersion(name="elo_538", version="1.1", role="champion")
    challenger = ModelVersion(name="elo_538", version="2.0")
    db_session.add_all([season, home, away, champion, challenger])
    db_session.commit()
    db_session.add(Game(
        nba_game_id="0022600001", provider_event_id="ev", season_id=season.id, home_team_id=home.id,
        away_team_id=away.id, commence_time=datetime(2026, 10, 20, 23, 0, tzinfo=timezone.utc) + timedelta(days=0),
        status="final", home_score=100, away_score=90,
    ))
    db_session.add(TeamEloRating(model_version_id=challenger.id, team_id=home.id, season_id=season.id, game_id="0022600001"))
    db_session.commit()
    assert count_final_games_without_ratings(db_session) == 1  # only the challenger rated it

    db_session.add(TeamEloRating(model_version_id=champion.id, team_id=home.id, season_id=season.id, game_id="0022600001"))
    db_session.commit()
    assert count_final_games_without_ratings(db_session) == 0
