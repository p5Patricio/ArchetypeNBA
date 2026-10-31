from datetime import datetime
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import Session, func, select

from app.deps import get_db_session
from app.models import InjuryEntry, InjuryReportSnapshot

router = APIRouter(prefix="/injuries")


class InjuryEntryResponse(BaseModel):
    id: int
    game_date: str
    game_time_et: Optional[str] = None
    matchup: Optional[str] = None
    team_name: Optional[str] = None
    player_name_raw: str
    player_id: Optional[int] = None
    status: str
    reason: Optional[str] = None
    availability_prob: Optional[float] = None


class LatestInjuryReportResponse(BaseModel):
    snapshot_id: int
    source: str
    report_url: str
    report_timestamp: datetime
    fetched_at: datetime
    sha256: str
    total_entries_count: int
    returned_entries_count: int
    teams: Dict[str, List[InjuryEntryResponse]]


@router.get("/latest", response_model=LatestInjuryReportResponse)
def get_latest_injuries(
    include_available: bool = Query(
        False, description="Whether to include players with Available status"
    ),
    session: Session = Depends(get_db_session),
):
    """
    Returns the latest official NBA injury report snapshot summary with entries grouped by team.
    By default, only non-Available players are included.
    """
    snapshot = session.exec(
        select(InjuryReportSnapshot).order_by(
            InjuryReportSnapshot.report_timestamp.desc(),
            InjuryReportSnapshot.id.desc(),
        )
    ).first()

    if snapshot is None:
        raise HTTPException(
            status_code=404, detail="No injury report snapshot found"
        )

    stmt = select(InjuryEntry).where(InjuryEntry.snapshot_id == snapshot.id)
    if not include_available:
        stmt = stmt.where(func.lower(InjuryEntry.status) != "available")

    entries = session.exec(stmt).all()

    teams_map: Dict[str, List[InjuryEntryResponse]] = {}
    for e in entries:
        team_key = e.team_name or "Unknown"
        item = InjuryEntryResponse(
            id=e.id,  # type: ignore
            game_date=e.game_date,
            game_time_et=e.game_time_et,
            matchup=e.matchup,
            team_name=e.team_name,
            player_name_raw=e.player_name_raw,
            player_id=e.player_id,
            status=e.status,
            reason=e.reason,
            availability_prob=float(e.availability_prob)
            if e.availability_prob is not None
            else None,
        )
        teams_map.setdefault(team_key, []).append(item)

    return LatestInjuryReportResponse(
        snapshot_id=snapshot.id,  # type: ignore
        source=snapshot.source,
        report_url=snapshot.report_url,
        report_timestamp=snapshot.report_timestamp,
        fetched_at=snapshot.fetched_at,
        sha256=snapshot.sha256,
        total_entries_count=snapshot.entries_count,
        returned_entries_count=len(entries),
        teams=teams_map,
    )
