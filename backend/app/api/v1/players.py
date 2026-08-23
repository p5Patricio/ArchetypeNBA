from typing import Optional, List
from fastapi import APIRouter, Depends, Query
from app.api.deps import get_player_service
from app.schemas import PlayerAnalysisResponse, PlayerRadarsResponse, PlayerSeasonSummary
from app.services.player import PlayerService

router = APIRouter()


@router.get("/players", response_model=List[str])
def get_players(
    team: Optional[str] = Query(default=None),
    season_id: Optional[int] = Query(default=None),
    service: PlayerService = Depends(get_player_service),
):
    # Return list of player names from repo
    if season_id:
        stats = service.stats_repo.find_by_season(season_id=season_id, team_abbreviation=team)
        names = list({s.player.full_name for s in stats if s.player})
        return sorted(names)
    players = service.player_repo.list()
    names = [p.full_name for p in players]
    if team:
        stats = service.stats_repo.find_by_season(season_id=1, team_abbreviation=team)
        names = list({s.player.full_name for s in stats if s.player})
    return sorted(names)


@router.get("/players/season/{season_id}", response_model=List[PlayerSeasonSummary])
def get_season_players(
    season_id: int,
    team: Optional[str] = Query(default=None),
    service: PlayerService = Depends(get_player_service),
):
    return service.get_season_players(season_id, team=team)


@router.get("/player/{player_name}/analysis", response_model=PlayerAnalysisResponse)
def analyze_player(
    player_name: str,
    season_id: Optional[int] = Query(default=None),
    service: PlayerService = Depends(get_player_service),
):
    return service.get_analysis(player_name, season_id)


@router.get("/player/{player_name}/radars", response_model=PlayerRadarsResponse)
def player_radars(
    player_name: str,
    service: PlayerService = Depends(get_player_service),
):
    return service.get_radars(player_name)
