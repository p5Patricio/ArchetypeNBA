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
    results = []
    for s in seasons:
        count = session.exec(
            select(func.count(PlayerSeasonStats.id)).where(PlayerSeasonStats.season_id == s.id)
        ).one()
        results.append(
            SeasonResponse(
                id=s.id,
                season_label=s.season_label,
                is_active=s.is_active,
                players_count=count or 0,
            )
        )
    return results
