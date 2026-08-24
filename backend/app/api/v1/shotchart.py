from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session
from app.deps import get_session
from app.schemas import RealShotChartResponse
from app.services.real_shotchart import RealShotChartService

router = APIRouter()


@router.get("/players/{player_id_or_name}/shot-chart", response_model=RealShotChartResponse)
@router.get("/player/{player_id_or_name}/shot-chart", response_model=RealShotChartResponse)
def get_player_real_shot_chart(
    player_id_or_name: str,
    season_id: Optional[int] = Query(None, description="Optional Season ID"),
    max_shots: int = Query(400, description="Max shots to return in coordinate payload"),
    session: Session = Depends(get_session),
):
    """
    Returns authentic NBA (x, y) coordinate shot chart with:
    - Individual made/missed points with distance and action types.
    - 6 Zone Efficiencies vs League Average (Restricted Area, Paint Non-RA, Mid-Range, Left Corner 3, Right Corner 3, Above Break 3).
    """
    service = RealShotChartService(session)
    try:
        return service.get_player_shot_chart(player_id_or_name, season_id, max_shots)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
