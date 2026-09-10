from typing import Optional, List
from fastapi import APIRouter, HTTPException, Query
from app.schemas import ParallelShotZonesResponse, ShotZonePreset
from app.services.parallel_zones import ParallelZonesService

router = APIRouter()
service = ParallelZonesService()


@router.get("/shot-zones/parallel", response_model=ParallelShotZonesResponse)
def get_parallel_shot_zones(
    season: str = Query("2023-24", description="NBA season identifier (e.g. 2023-24, 2024-25)"),
    player_ids: Optional[str] = Query(None, description="Comma-separated player IDs to filter"),
    search: Optional[str] = Query(None, description="Search player name or team"),
):
    """
    Returns authentic NBA 4-zone parallel coordinates data for the top 300 players by minutes.
    Zones:
      1. Pintura (Restricted Area + In-Paint Non-RA)
      2. Media (Mid-Range)
      3. Tiro Libre (Free Throw)
      4. Triple (3-Point)
    Includes individual percentiles, rankings, impact scores, and league averages.
    """
    parsed_ids: Optional[List[int]] = None
    if player_ids:
        try:
            parsed_ids = [int(x.strip()) for x in player_ids.split(",") if x.strip()]
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid player_ids format. Must be comma-separated integers.")

    try:
        return service.get_parallel_shot_zones(season=season, player_ids=parsed_ids, search=search)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving shot zones data: {str(e)}")


@router.get("/shot-zones/presets", response_model=List[ShotZonePreset])
def get_shot_zones_presets():
    """
    Returns preconfigured player comparison presets (e.g., Curry vs Giannis, Edwards vs Brunson vs Mitchell).
    """
    return service.get_presets()
