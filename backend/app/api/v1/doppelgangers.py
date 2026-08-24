from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session
from app.deps import get_session
from app.schemas import DoppelgangerResponse
from app.services.doppelgangers import DoppelgangerService

router = APIRouter()


@router.get("/doppelgangers", response_model=DoppelgangerResponse)
def get_player_doppelgangers(
    player_id_or_name: str = Query(..., description="Player ID or name to find clones for"),
    season_id: Optional[int] = Query(None, description="Optional target season ID"),
    top_k: int = Query(5, ge=1, le=10, description="Number of historical matches to return"),
    session: Session = Depends(get_session),
):
    """
    Finds top historical clones ('Doppelgängers') across 40 years of NBA history
    using multi-dimensional cosine similarity and positional archetype weighting.
    """
    service = DoppelgangerService(session)
    try:
        return service.find_doppelgangers(player_id_or_name, season_id, top_k)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
