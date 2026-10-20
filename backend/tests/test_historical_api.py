from datetime import date

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


def _seed_api_data(db_session: Session, base_id: int = 901):
    season = Season(id=base_id, season_label=f"2023-24-api-{base_id}")
    team = Team(
        id=base_id,
        abbreviation=f"A{base_id}",
        full_name="API Testers",
        city="API",
        conference="East",
        division="Atlantic",
    )
    opponent = Team(
        id=base_id + 1,
        abbreviation=f"B{base_id}",
        full_name="API Opponents",
        city="Opponent",
        conference="West",
        division="Pacific",
    )
    player = Player(id=base_id, full_name=f"API Player {base_id}")
    similar = Player(id=base_id + 1, full_name=f"API Similar {base_id}")
    db_session.add_all([season, team, opponent, player, similar])
    db_session.commit()
    db_session.add_all(
        [
            PlayerGameLog(
                player_id=base_id,
                team_id=base_id,
                season_id=base_id,
                game_id=f"API-GAME-{base_id}",
                game_date=date(2023, 10, 24),
                matchup="API vs. OPP",
                wl="W",
                min=33,
                pts=27,
                reb=8,
                ast=10,
            ),
            PlayerShot(
                player_id=base_id,
                season_id=base_id,
                game_id=f"API-GAME-{base_id}",
                game_event_id=12,
                loc_x=55,
                loc_y=66,
                shot_made_flag=True,
            ),
            PlayerAdvancedStats(
                player_id=base_id,
                season_id=base_id,
                per=26.2,
                ts_pct=0.64,
                vorp=7.1,
            ),
            PlayerSimilarity(
                player_id=base_id,
                season_id=base_id,
                similar_player_id=base_id + 1,
                similarity_score=0.93,
            ),
            TeamEloRating(
                model_version_id=ensure_default_champion(db_session).id,
                team_id=base_id,
                season_id=base_id,
                game_id=f"API-GAME-{base_id}",
                game_date=date(2023, 10, 24),
                opponent_team_id=base_id + 1,
                rating_before=1500,
                rating_after=1511,
                result="W",
                win_probability=0.5,
            ),
        ]
    )
    db_session.commit()
    return player, team, season


def test_historical_api_returns_player_game_logs(client, db_session: Session):
    player, _, season = _seed_api_data(db_session, base_id=901)

    response = client.get(f"/api/v1/player/{player.full_name}/game-logs?season_id={season.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["player_name"] == player.full_name
    assert body["games"][0]["game_id"] == "API-GAME-901"
    assert body["games"][0]["pts"] == 27


def test_historical_api_returns_db_backed_shots_when_season_id_is_present(client, db_session: Session):
    player, _, season = _seed_api_data(db_session, base_id=1001)

    response = client.get(f"/api/v1/player/{player.full_name}/shots?season_id={season.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["player_name"] == player.full_name
    assert body["attempts"] == 1
    assert body["makes"] == 1
    assert body["shots"][0]["x"] == 55


def test_historical_api_returns_advanced_similar_and_elo(client, db_session: Session):
    player, team, season = _seed_api_data(db_session, base_id=1101)

    advanced = client.get(f"/api/v1/player/{player.full_name}/advanced?season_id={season.id}")
    similar = client.get(f"/api/v1/player/{player.full_name}/similar?season_id={season.id}")
    elo = client.get(f"/api/v1/teams/{team.abbreviation}/elo?season_id={season.id}")

    assert advanced.status_code == 200
    assert advanced.json()["vorp"] == 7.1
    assert similar.status_code == 200
    assert similar.json()["players"][0]["player_name"] == "API Similar 1101"
    assert elo.status_code == 200
    assert elo.json()["timeline"][0]["rating_after"] == 1511
