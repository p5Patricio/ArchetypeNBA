from typing import List
from fastapi import APIRouter, HTTPException, Depends
from sqlmodel import Session
from app.deps import get_db_session
from app.schemas import (
    LineupTeamRequest,
    LineupTeamEvaluationResponse,
    Lineup5v5SimulationRequest,
    Lineup5v5SimulationResponse,
    ClassicPresetLineup,
)
from app.services.lineup import LineupService

router = APIRouter()


@router.post("/lineup/evaluate", response_model=LineupTeamEvaluationResponse)
def evaluate_lineup(
    request: LineupTeamRequest,
    session: Session = Depends(get_db_session),
):
    """
    Evaluates a 5-player fantasy team lineup, calculating Spacing, Playmaking,
    Defense, Net Rating, and Archetype Synergy.
    """
    try:
        service = LineupService(session)
        return service.evaluate_lineup(request.team_name, request.slots)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error evaluating lineup: {str(e)}")


@router.post("/lineup/simulate", response_model=Lineup5v5SimulationResponse)
def simulate_5v5_lineup(
    request: Lineup5v5SimulationRequest,
    session: Session = Depends(get_db_session),
):
    """
    Simulates a full 48-minute 5 vs 5 game between Team 1 and Team 2,
    returning final score, quarter scores, Box Score, and game MVP.
    """
    try:
        service = LineupService(session)
        return service.simulate_5v5_game(request.team1, request.team2)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error simulating 5v5 game: {str(e)}")


@router.get("/lineup/presets", response_model=List[ClassicPresetLineup])
def get_lineup_presets(
    session: Session = Depends(get_db_session),
):
    """
    Returns legendary classic preset lineups (e.g. 1996 Bulls, 2017 Warriors, 2001 Lakers).
    """
    try:
        service = LineupService(session)
        return service.get_classic_presets()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching lineup presets: {str(e)}")
