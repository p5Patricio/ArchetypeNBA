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
from app.repositories.historical import HistoricalRepository


def _seed_historical_data(db_session: Session, base_id: int = 301):
    season = Season(id=base_id, season_label=f"2023-24-historical-{base_id}")
    team = Team(
        id=base_id,
        abbreviation=f"H{base_id}",
        full_name="Historical Testers",
        city="History",
        conference="East",
        division="Atlantic",
    )
    opponent = Team(
        id=base_id + 1,
        abbreviation=f"O{base_id}",
        full_name="Opponent Testers",
        city="Opponent",
        conference="West",
        division="Pacific",
    )
    player = Player(id=base_id, full_name=f"Historical Player {base_id}")
    similar = Player(id=base_id + 1, full_name=f"Similar Player {base_id}")
    db_session.add_all([season, team, opponent, player, similar])
    db_session.commit()

    db_session.add_all(
        [
            PlayerGameLog(
                player_id=base_id,
                team_id=base_id,
                season_id=base_id,
                game_id=f"HIST-GAME-{base_id}",
                game_date=date(2023, 10, 24),
                matchup="HST vs. OPP",
                wl="W",
                pts=31,
            ),
            PlayerShot(
                player_id=base_id,
                season_id=base_id,
                game_id=f"HIST-GAME-{base_id}",
                game_event_id=7,
                loc_x=10,
                loc_y=20,
                shot_made_flag=True,
            ),
            PlayerAdvancedStats(
                player_id=base_id,
                season_id=base_id,
                per=24.8,
                ts_pct=0.625,
                vorp=6.4,
            ),
            PlayerSimilarity(
                player_id=base_id,
                season_id=base_id,
                similar_player_id=base_id + 1,
                similarity_score=0.91,
            ),
            TeamEloRating(
                model_version_id=ensure_default_champion(db_session).id,
                team_id=base_id,
                season_id=base_id,
                game_id=f"HIST-GAME-{base_id}",
                game_date=date(2023, 10, 24),
                opponent_team_id=base_id + 1,
                rating_before=1500,
                rating_after=1510,
                result="W",
                win_probability=0.5,
            ),
        ]
    )
    db_session.commit()


def test_historical_repository_reads_phase_2_player_data(db_session: Session):
    _seed_historical_data(db_session, base_id=301)
    repo = HistoricalRepository(db_session)

    logs = repo.list_player_game_logs(player_id=301, season_id=301)
    shots = repo.list_player_shots(player_id=301, season_id=301)
    advanced = repo.get_player_advanced_stats(player_id=301, season_id=301)
    similar = repo.list_player_similarities(player_id=301, season_id=301)

    assert [log.game_id for log in logs] == ["HIST-GAME-301"]
    assert shots[0].game_event_id == 7
    assert advanced is not None
    assert advanced.vorp == 6.4
    assert similar[0].similar_player_id == 302
    assert similar[0].similarity_score == 0.91


def test_historical_repository_reads_team_elo_timeline(db_session: Session):
    _seed_historical_data(db_session, base_id=401)
    repo = HistoricalRepository(db_session)

    timeline = repo.list_team_elo(team_id=401, season_id=401)

    assert len(timeline) == 1
    assert timeline[0].game_id == "HIST-GAME-401"
    assert timeline[0].rating_before == 1500
    assert timeline[0].rating_after == 1510
