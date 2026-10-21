from typing import List, Optional

from sqlmodel import Session, select

from app.models import (
    PlayerAdvancedStats,
    PlayerGameLog,
    PlayerShot,
    PlayerSimilarity,
    TeamEloRating,
)
from app.services import model_registry


class HistoricalRepository:
    def __init__(self, session: Session):
        self.session = session

    def list_player_game_logs(self, player_id: int, season_id: int) -> List[PlayerGameLog]:
        stmt = (
            select(PlayerGameLog)
            .where(
                PlayerGameLog.player_id == player_id,
                PlayerGameLog.season_id == season_id,
            )
            .order_by(PlayerGameLog.game_date)
        )
        return self.session.exec(stmt).all()

    def list_player_shots(self, player_id: int, season_id: int) -> List[PlayerShot]:
        stmt = (
            select(PlayerShot)
            .where(
                PlayerShot.player_id == player_id,
                PlayerShot.season_id == season_id,
            )
            .order_by(PlayerShot.game_date, PlayerShot.game_event_id)
        )
        return self.session.exec(stmt).all()

    def get_player_advanced_stats(
        self,
        player_id: int,
        season_id: int,
    ) -> Optional[PlayerAdvancedStats]:
        stmt = select(PlayerAdvancedStats).where(
            PlayerAdvancedStats.player_id == player_id,
            PlayerAdvancedStats.season_id == season_id,
        )
        return self.session.exec(stmt).first()

    def list_player_similarities(
        self,
        player_id: int,
        season_id: int,
    ) -> List[PlayerSimilarity]:
        stmt = (
            select(PlayerSimilarity)
            .where(
                PlayerSimilarity.player_id == player_id,
                PlayerSimilarity.season_id == season_id,
            )
            .order_by(PlayerSimilarity.similarity_score.desc())
        )
        return self.session.exec(stmt).all()

    def list_team_elo(self, team_id: int, season_id: int) -> List[TeamEloRating]:
        """The Elo reference model's rating timeline (every model keeps its own rows in team_elo_rating)."""
        stmt = select(TeamEloRating).where(
            TeamEloRating.team_id == team_id,
            TeamEloRating.season_id == season_id,
        )
        reference = model_registry.get_elo_reference(self.session)
        if reference is not None:
            stmt = stmt.where(TeamEloRating.model_version_id == reference.id)
        return self.session.exec(stmt.order_by(TeamEloRating.game_date)).all()

    def save_advanced_stats(self, stats: PlayerAdvancedStats) -> PlayerAdvancedStats:
        existing = self.get_player_advanced_stats(stats.player_id, stats.season_id)
        if existing:
            for key, value in stats.model_dump(exclude={"id"}).items():
                setattr(existing, key, value)
            self.session.add(existing)
            self.session.commit()
            self.session.refresh(existing)
            return existing

        self.session.add(stats)
        self.session.commit()
        self.session.refresh(stats)
        return stats

    def save_team_elo_batch(self, ratings: List[TeamEloRating]) -> int:
        self.session.add_all(ratings)
        self.session.commit()
        return len(ratings)

    def save_player_similarities(self, similarities: List[PlayerSimilarity]) -> int:
        self.session.add_all(similarities)
        self.session.commit()
        return len(similarities)
