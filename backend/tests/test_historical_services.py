from datetime import date

import pytest
from fastapi import HTTPException
from sqlmodel import Session

from app.models import (
    Player,
    PlayerAdvancedStats,
    PlayerGameLog,
    PlayerShot,
    PlayerSimilarity,
    Season,
    Team,
    TeamEloRating,
)
from app.services.model_registry import ensure_default_champion
from app.repositories.historical import HistoricalRepository
from app.repositories.player import PlayerRepository
from app.repositories.team import TeamRepository
from app.services.historical import HistoricalService


def _seed_service_data(db_session: Session, base_id: int = 501):
    season = Season(id=base_id, season_label=f"2023-24-service-{base_id}")
    team = Team(
        id=base_id,
        abbreviation=f"S{base_id}",
        full_name="Service Testers",
        city="Service",
        conference="East",
        division="Atlantic",
    )
    opponent = Team(
        id=base_id + 1,
        abbreviation=f"P{base_id}",
        full_name="Service Opponents",
        city="Opponent",
        conference="West",
        division="Pacific",
    )
    player = Player(id=base_id, full_name=f"Service Player {base_id}")
    similar = Player(id=base_id + 1, full_name=f"Service Similar {base_id}")
    db_session.add_all([season, team, opponent, player, similar])
    db_session.commit()
    db_session.add_all(
        [
            PlayerGameLog(
                player_id=base_id,
                team_id=base_id,
                season_id=base_id,
                game_id=f"SVC-GAME-{base_id}",
                game_date=date(2023, 10, 24),
                matchup="SVC vs. OPP",
                wl="W",
                min=34,
                pts=28,
                ast=9,
                reb=7,
            ),
            PlayerShot(
                player_id=base_id,
                season_id=base_id,
                game_id=f"SVC-GAME-{base_id}",
                game_event_id=9,
                loc_x=33,
                loc_y=44,
                shot_made_flag=True,
                action_type="Layup Shot",
            ),
            PlayerAdvancedStats(
                player_id=base_id,
                season_id=base_id,
                per=25.1,
                ts_pct=0.63,
                usg_pct=31.2,
                vorp=6.7,
            ),
            PlayerSimilarity(
                player_id=base_id,
                season_id=base_id,
                similar_player_id=base_id + 1,
                similarity_score=0.88,
            ),
            TeamEloRating(
                model_version_id=ensure_default_champion(db_session).id,
                team_id=base_id,
                season_id=base_id,
                game_id=f"SVC-GAME-{base_id}",
                game_date=date(2023, 10, 24),
                opponent_team_id=base_id + 1,
                rating_before=1500,
                rating_after=1512,
                result="W",
                win_probability=0.5,
            ),
        ]
    )
    db_session.commit()
    return player, team, season


def _service(db_session: Session) -> HistoricalService:
    return HistoricalService(
        player_repo=PlayerRepository(db_session),
        team_repo=TeamRepository(db_session),
        historical_repo=HistoricalRepository(db_session),
    )


class DictCache:
    def __init__(self):
        self.values = {}

    def get_json(self, key):
        return self.values.get(key)

    def set_json(self, key, value, ttl_seconds=None):
        self.values[key] = value


def test_historical_service_returns_player_game_logs(db_session: Session):
    player, _, season = _seed_service_data(db_session, base_id=501)

    response = _service(db_session).get_player_game_logs(player.full_name, season.id)

    assert response.player_name == player.full_name
    assert response.season_id == season.id
    assert response.games[0].game_id == "SVC-GAME-501"
    assert response.games[0].pts == 28


def test_historical_service_reuses_cached_game_logs(db_session: Session):
    player, _, season = _seed_service_data(db_session, base_id=511)
    cache = DictCache()
    service = HistoricalService(
        player_repo=PlayerRepository(db_session),
        team_repo=TeamRepository(db_session),
        historical_repo=HistoricalRepository(db_session),
        cache=cache,
    )

    first = service.get_player_game_logs(player.full_name, season.id)
    db_session.add(
        PlayerGameLog(
            player_id=511,
            team_id=511,
            season_id=511,
            game_id="SVC-GAME-511-B",
            pts=99,
        )
    )
    db_session.commit()
    second = service.get_player_game_logs(player.full_name, season.id)

    assert [game.game_id for game in first.games] == ["SVC-GAME-511"]
    assert [game.game_id for game in second.games] == ["SVC-GAME-511"]


def test_historical_service_returns_player_shots(db_session: Session):
    player, _, season = _seed_service_data(db_session, base_id=601)

    response = _service(db_session).get_player_shots(player.full_name, season.id)

    assert response.player_name == player.full_name
    assert response.attempts == 1
    assert response.makes == 1
    assert response.shots[0].x == 33
    assert response.shots[0].action_type == "Layup Shot"


def test_historical_service_returns_advanced_stats_and_similar_players(db_session: Session):
    player, _, season = _seed_service_data(db_session, base_id=701)

    advanced = _service(db_session).get_player_advanced_stats(player.full_name, season.id)
    similar = _service(db_session).get_player_similarities(player.full_name, season.id)

    assert advanced.per == 25.1
    assert advanced.ts_pct == 0.63
    assert advanced.vorp == 6.7
    assert similar.players[0].player_name == "Service Similar 701"
    assert similar.players[0].similarity_score == 0.88


def test_historical_service_returns_team_elo(db_session: Session):
    _, team, season = _seed_service_data(db_session, base_id=801)

    response = _service(db_session).get_team_elo(team.abbreviation, season.id)

    assert response.team_abbreviation == team.abbreviation
    assert response.timeline[0].rating_before == 1500
    assert response.timeline[0].rating_after == 1512


def test_historical_service_raises_404_for_unknown_player(db_session: Session):
    with pytest.raises(HTTPException) as exc:
        _service(db_session).get_player_game_logs("Missing Player", 999)

    assert exc.value.status_code == 404
