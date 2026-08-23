import unicodedata
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Query, Depends
from sqlmodel import Session, select
from app.deps import get_db_session
from app.models import Player, PlayerSeasonStats
from app.schemas import (
    VersusPlayerOption,
    VersusMatchupResponse,
)
from app.services.versus import VersusService

router = APIRouter()


def _normalize_str(s: str) -> str:
    if not s:
        return ""
    nfkd = unicodedata.normalize("NFKD", s)
    return (
        "".join(c for c in nfkd if not unicodedata.combining(c))
        .lower()
        .replace("'", "")
        .replace("’", "")
        .replace("-", "")
        .replace(".", "")
        .replace(" ", "")
        .strip()
    )


def _resolve_player_id(session: Session, name: str) -> Optional[int]:
    if not name:
        return None

    clean_target = _normalize_str(name)
    all_players = session.exec(select(Player)).all()
    candidates = []

    for p in all_players:
        clean_p = _normalize_str(p.full_name)
        if clean_p == clean_target:
            candidates.append((p, 2))  # Exact normalized match
        elif clean_target in clean_p or clean_p in clean_target:
            candidates.append((p, 1))  # Partial match

    if not candidates:
        return None

    # Count season stats for each candidate to avoid picking empty duplicate stub records
    stats_map = {}
    for p, _ in candidates:
        stats = session.exec(
            select(PlayerSeasonStats).where(PlayerSeasonStats.player_id == p.id)
        ).all()
        stats_map[p.id] = len(stats)

    # Sort primarily by match confidence (2 > 1), then by number of recorded season stats
    candidates.sort(key=lambda x: (x[1], stats_map.get(x[0].id, 0)), reverse=True)
    return candidates[0][0].id



@router.get("/versus/players", response_model=List[VersusPlayerOption])
def get_versus_players(
    session: Session = Depends(get_db_session),
):
    """
    Returns all players with their available seasons and calculated Peak Season.
    """
    service = VersusService(session)
    return service.get_all_players_with_seasons()


@router.get("/versus/matchup", response_model=VersusMatchupResponse)
def get_versus_matchup(
    player1_id: Optional[int] = Query(default=None, description="Player 1 Database ID"),
    player1_name: Optional[str] = Query(default=None, description="Player 1 Full Name"),
    season1_id: Optional[int] = Query(default=None, description="Player 1 Season ID (defaults to peak)"),
    player2_id: Optional[int] = Query(default=None, description="Player 2 Database ID"),
    player2_name: Optional[str] = Query(default=None, description="Player 2 Full Name"),
    season2_id: Optional[int] = Query(default=None, description="Player 2 Season ID (defaults to peak)"),
    session: Session = Depends(get_db_session),
):
    # Sanitize inputs
    if not isinstance(player1_id, int):
        player1_id = None
    if not isinstance(player2_id, int):
        player2_id = None
    if not isinstance(season1_id, int):
        season1_id = None
    if not isinstance(season2_id, int):
        season2_id = None

    # Resolve player 1 ID if name provided
    if player1_id is None and player1_name:
        player1_id = _resolve_player_id(session, str(player1_name))
        if not player1_id:
            raise HTTPException(status_code=404, detail=f"Player 1 '{player1_name}' not found")

    # Resolve player 2 ID if name provided
    if player2_id is None and player2_name:
        player2_id = _resolve_player_id(session, str(player2_name))
        if not player2_id:
            raise HTTPException(status_code=404, detail=f"Player 2 '{player2_name}' not found")



    if not player1_id or not player2_id:
        raise HTTPException(
            status_code=400,
            detail="Must provide player1_id/player1_name and player2_id/player2_name",
        )

    service = VersusService(session)
    try:
        matchup = service.calculate_matchup(
            player1_id=player1_id,
            season1_id=season1_id,
            player2_id=player2_id,
            season2_id=season2_id,
        )
        return matchup
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error calculating 1v1 matchup: {str(e)}")
