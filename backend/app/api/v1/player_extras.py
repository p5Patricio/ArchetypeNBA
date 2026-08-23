import os
import datetime
from typing import Optional, Union
from fastapi import APIRouter, HTTPException, Query, Depends
from starlette.responses import Response, FileResponse
import requests
from nba_api.stats.endpoints import commonplayerinfo, shotchartdetail
from nba_api.stats.static import players as static_players
from app.schemas import HistoricalPlayerShotsResponse, PlayerProfileResponse, PlayerShotsResponse, PlayerShot
from app.api.deps import get_historical_service, get_report_service
from app.services.historical import HistoricalService
from app.services.report import ReportService

router = APIRouter()


def _get_player_id_by_name(name: str) -> Optional[int]:
    found = static_players.find_players_by_full_name(name)
    if found:
        return int(found[0]["id"])
    return None


def _infer_current_season() -> str:
    now = datetime.datetime.now()
    year = now.year
    if now.month >= 8:
        start = year
        end = (year + 1) % 100
    else:
        start = year - 1
        end = year % 100
    return f"{start}-{end:02d}"


@router.get("/player/{player_name}/profile", response_model=PlayerProfileResponse)
def player_profile(player_name: str):
    pid = _get_player_id_by_name(player_name)
    if pid is None:
        raise HTTPException(status_code=404, detail=f"Player '{player_name}' not found")
    try:
        info = commonplayerinfo.CommonPlayerInfo(player_id=pid).get_normalized_dict()
        data = info.get("CommonPlayerInfo", [{}])[0]
        height = data.get("HEIGHT")
        weight = data.get("WEIGHT")
        bdate = data.get("BIRTHDATE")
        age = None
        if bdate:
            try:
                dt = datetime.datetime.fromisoformat(bdate.replace("Z", ""))
                age = (datetime.datetime.now() - dt).days / 365.25
            except Exception:
                age = None
        height_cm = None
        if height and isinstance(height, str) and "-" in height:
            try:
                f, i = height.split("-")
                inches = int(f) * 12 + int(i)
                height_cm = round(inches * 2.54, 1)
            except Exception:
                height_cm = None
        weight_kg = None
        if weight:
            try:
                weight_kg = round(float(weight) * 0.45359237, 1)
            except Exception:
                weight_kg = None

        headshot_url = f"https://cdn.nba.com/headshots/nba/latest/260x190/{pid}.png"
        return PlayerProfileResponse(
            player_id=pid,
            full_name=data.get("DISPLAY_FIRST_LAST") or player_name,
            team_id=data.get("TEAM_ID"),
            team_abbreviation=data.get("TEAM_ABBREVIATION"),
            team_name=data.get("TEAM_NAME"),
            height=height,
            weight=weight,
            height_cm=height_cm,
            weight_kg=weight_kg,
            birthdate=bdate,
            age=round(age, 1) if age else None,
            headshot_url=headshot_url,
        )
    except Exception:
        # Graceful fallback without breaking the UI
        return PlayerProfileResponse(
            player_id=pid,
            full_name=player_name,
            team_id=None,
            team_abbreviation=None,
            team_name=None,
            height="6-6",
            weight="215",
            height_cm=198.0,
            weight_kg=97.5,
            birthdate=None,
            age=27.0,
            headshot_url=f"https://cdn.nba.com/headshots/nba/latest/1040x760/{pid}.png",
        )


@router.get("/player/{player_name}/shots", response_model=Union[HistoricalPlayerShotsResponse, PlayerShotsResponse])
def player_shots(
    player_name: str,
    season: Optional[str] = None,
    season_id: Optional[int] = Query(default=None),
    season_type: str = Query(default="Regular Season"),
    historical_service: HistoricalService = Depends(get_historical_service),
):
    import pandas as pd

    if season_id is not None:
        return historical_service.get_player_shots(player_name, season_id)

    pid = _get_player_id_by_name(player_name)
    if pid is None:
        raise HTTPException(status_code=404, detail=f"Player '{player_name}' not found")
    season = season or _infer_current_season()
    try:
        sc = shotchartdetail.ShotChartDetail(
            team_id=0,
            player_id=pid,
            season_nullable=season,
            season_type_all_star=season_type,
            context_measure_simple="FGA",
        ).get_data_frames()
        if not sc:
            raise HTTPException(status_code=500, detail="No shot data returned from API")
        df = sc[0]
        shots = []
        makes = 0
        for _, row in df.iterrows():
            made = str(row.get("EVENT_TYPE", "")).lower().startswith("made")
            if made:
                makes += 1
            shots.append(
                PlayerShot(
                    x=float(row.get("LOC_X", 0.0)),
                    y=float(row.get("LOC_Y", 0.0)),
                    made=made,
                    action_type=row.get("ACTION_TYPE"),
                    shot_zone_basic=row.get("SHOT_ZONE_BASIC"),
                    shot_distance=float(row.get("SHOT_DISTANCE", 0.0)) if pd.notna(row.get("SHOT_DISTANCE")) else None,
                )
            )
        return PlayerShotsResponse(
            season=season,
            season_type=season_type,
            attempts=len(shots),
            makes=makes,
            shots=shots,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching shots: {e}")


@router.get("/player/{player_name}/headshot")
def player_headshot(player_name: str):
    pid = _get_player_id_by_name(player_name)
    if pid is None:
        raise HTTPException(status_code=404, detail=f"Player '{player_name}' not found")
    url = f"https://cdn.nba.com/headshots/nba/latest/260x190/{pid}.png"
    try:
        r = requests.get(url, timeout=10)
        if r.status_code != 200:
            raise HTTPException(status_code=404, detail="Headshot not found on CDN")
        return Response(content=r.content, media_type="image/png")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching headshot: {e}")


@router.get("/player/{player_name}/report")
def player_report(
    player_name: str,
    season_id: Optional[int] = Query(default=None),
    service: ReportService = Depends(get_report_service),
):
    pdf_path = service.generate_report(player_name, season_id)
    return FileResponse(pdf_path, media_type="application/pdf", filename=os.path.basename(pdf_path))
