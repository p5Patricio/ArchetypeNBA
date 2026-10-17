from typing import List
from fastapi import APIRouter, Depends
from sqlmodel import Session, select, func
from app.deps import get_db_session
from app.models import Season, PlayerSeasonStats
from app.schemas import SeasonResponse

router = APIRouter()


@router.get("/seasons", response_model=List[SeasonResponse])
def get_seasons(session: Session = Depends(get_db_session)):
    seasons = session.exec(select(Season).order_by(Season.season_label.desc())).all()
    counts = {
        s.id: session.exec(
            select(func.count(PlayerSeasonStats.id)).where(PlayerSeasonStats.season_id == s.id)
        ).one()
        or 0
        for s in seasons
    }
    # Seasons created ahead of time for upcoming games (odds ingestion) have no player stats yet: keep them
    # out of the selector, but never hide the active season.
    seasons = [s for s in seasons if counts[s.id] > 0 or s.is_active]
    has_active = any(s.is_active for s in seasons)
    results = []
    for i, s in enumerate(seasons):
        is_active = s.is_active if has_active else (i == 0)
        results.append(
            SeasonResponse(
                id=s.id,
                season_label=s.season_label,
                is_active=is_active,
                players_count=counts[s.id],
            )
        )
    return results
