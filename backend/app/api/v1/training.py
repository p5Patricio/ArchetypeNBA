from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session
from app.deps import get_db_session
from app.schemas import TrainingAnalysisResponse, DrillRecommendation
from app.services.training import TrainingService, DRILLS_CATALOG

router = APIRouter()


@router.get("/training/analyze", response_model=TrainingAnalysisResponse)
def analyze_player_training(
    player_name: str = Query(..., description="Name of the player to analyze"),
    season_id: Optional[int] = Query(default=None, description="Optional season ID"),
    intensity: str = Query(default="standard", description="Intensity level: standard, high, elite"),
    session: Session = Depends(get_db_session),
):
    """
    Performs comprehensive positional analysis comparing player stats with position peers,
    evaluating role fulfillment (0-100 score + grade), identifying weak spots,
    and generating customized training regimes with projected improvements.
    """
    service = TrainingService(session)
    try:
        return service.get_training_analysis(
            player_name=player_name,
            season_id=season_id,
            intensity=intensity,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing training analysis: {str(e)}")


@router.get("/training/drills", response_model=List[DrillRecommendation])
def get_drills_catalog():
    """
    Returns full catalog of professional NBA tactical drills.
    """
    all_drills: List[DrillRecommendation] = []
    seen_ids = set()
    for cat_drills in DRILLS_CATALOG.values():
        for d in cat_drills:
            if d["id"] not in seen_ids:
                seen_ids.add(d["id"])
                all_drills.append(DrillRecommendation(**d))
    return all_drills
