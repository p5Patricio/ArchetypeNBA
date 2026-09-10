import unicodedata
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Query, Depends
from sqlmodel import Session, select
from app.deps import get_db_session
from app.models import Player, PlayerMatchupStats
from app.schemas import PlayerMatchupAnalysisResponse
from app.services.matchup_service import MatchupService

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


def _resolve_offensive_player_id(session: Session, name: str) -> Optional[int]:
    if not name:
        return None

    clean_target = _normalize_str(name)
    all_players = session.exec(select(Player)).all()
    candidates = []

    for p in all_players:
        clean_p = _normalize_str(p.full_name)
        if clean_p == clean_target:
            candidates.append((p, 3))
        elif clean_p.startswith(clean_target) or clean_target in clean_p:
            candidates.append((p, 2))
        elif clean_p in clean_target:
            candidates.append((p, 1))

    # Also search official NBA registry if no exact match found
    if not any(c[1] == 3 for c in candidates):
        try:
            from nba_api.stats.static import players as static_players
            nba_all = static_players.get_players()
            for np in nba_all:
                clean_np = _normalize_str(np["full_name"])
                if clean_np == clean_target:
                    local_p = session.get(Player, np["id"])
                    if not local_p:
                        local_p = Player(id=np["id"], full_name=np["full_name"])
                        session.add(local_p)
                        session.commit()
                        session.refresh(local_p)
                    candidates.insert(0, (local_p, 4))
                    break
                elif clean_target in clean_np:
                    local_p = session.get(Player, np["id"])
                    if not local_p:
                        local_p = Player(id=np["id"], full_name=np["full_name"])
                        session.add(local_p)
                        session.commit()
                        session.refresh(local_p)
                    candidates.append((local_p, 2))
        except Exception as e:
            print(f"Error querying static_players: {e}")

    if not candidates:
        return None

    # Count matchup records for each candidate to prioritize existing data
    matchup_map = {}
    for p, _ in candidates:
        count = len(session.exec(
            select(PlayerMatchupStats).where(PlayerMatchupStats.off_player_id == p.id)
        ).all())
        matchup_map[p.id] = count

    candidates.sort(key=lambda x: (x[1], matchup_map.get(x[0].id, 0)), reverse=True)
    return candidates[0][0].id


@router.get("/matchups/player/{player_id}", response_model=PlayerMatchupAnalysisResponse)
def get_player_matchup_analysis(
    player_id: int,
    seasons: Optional[List[str]] = Query(default=None, description="Seasons to include (e.g. 2021-22, 2022-23, 2023-24)"),
    min_possessions: float = Query(default=10.0, description="Minimum possessions against defender"),
    session: Session = Depends(get_db_session),
):
    """
    Analyzes 1v1 defensive matchups for an offensive player.
    Computes per-75 possession statistics, True Shooting % (TS%),
    metric differentials (Δ), and classifies defenders into Kryptonites vs. Mismatch Targets.
    """
    service = MatchupService(session)
    try:
        return service.analyze_player_matchups(
            player_id=player_id,
            seasons=seasons,
            min_possessions=min_possessions,
        )
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error analyzing matchups: {str(e)}")


@router.get("/matchups/search", response_model=PlayerMatchupAnalysisResponse)
def search_player_matchups(
    name: str = Query(description="Offensive player full or partial name (e.g. 'Luka Doncic')"),
    seasons: Optional[List[str]] = Query(default=None, description="Seasons to include"),
    min_possessions: float = Query(default=10.0, description="Minimum possessions against defender"),
    session: Session = Depends(get_db_session),
):
    """
    Searches player by name and returns their 1v1 matchup analysis with differentials and classification.
    """
    player_id = _resolve_offensive_player_id(session, name)
    if not player_id:
        raise HTTPException(status_code=404, detail=f"Player '{name}' not found")

    service = MatchupService(session)
    try:
        return service.analyze_player_matchups(
            player_id=player_id,
            seasons=seasons,
            min_possessions=min_possessions,
        )
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error analyzing matchups: {str(e)}")
