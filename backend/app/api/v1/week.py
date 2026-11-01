"""
Read-only Weekly View API router:
  - GET /api/v1/week?days=7 (1 to 14)

Returns scheduled games tipping off within the local day window (America/Mexico_City),
with model predictions, Pinnacle market references, line shopping, candidate paper bet flags,
and team injury reports.
"""
from typing import List

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from app.deps import get_db_session
from app.services.week_view import WeekGameResponse, build_week_view

router = APIRouter(prefix="/week", tags=["week"])


@router.get("", response_model=List[WeekGameResponse])
@router.get("/", response_model=List[WeekGameResponse], include_in_schema=False)
def get_week_view(
    days: int = Query(7, ge=1, le=14, description="Number of days to look ahead (1 to 14)"),
    session: Session = Depends(get_db_session),
) -> List[WeekGameResponse]:
    """
    Returns weekly schedule with model predictions, market odds, candidate qualification,
    and latest injury reports. Pure read-only view.
    """
    return build_week_view(session=session, days=days)
