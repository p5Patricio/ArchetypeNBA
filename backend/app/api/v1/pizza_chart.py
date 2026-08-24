from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session
from app.deps import get_session
from app.schemas import PizzaChartResponse
from app.services.pizza_chart import PizzaChartService

router = APIRouter()


@router.get("/players/{player_id_or_name}/pizza-chart", response_model=PizzaChartResponse)
@router.get("/player/{player_id_or_name}/pizza-chart", response_model=PizzaChartResponse)
def get_player_pizza_chart(
    player_id_or_name: str,
    season_id: Optional[int] = Query(None, description="Optional Season ID to evaluate"),
    session: Session = Depends(get_session),
):
    """
    Returns 16-metric Percentile Pizza Chart data for a player grouped into 4 tactical quadrants:
    1. Scoring & Efficiency (Red)
    2. Creation & Playmaking (Blue)
    3. Defense & Disruption (Green)
    4. Rebounding & Physicality (Purple)
    """
    service = PizzaChartService(session)
    try:
        return service.get_player_pizza_chart(player_id_or_name, season_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
