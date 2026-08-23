from typing import List, Dict, Any, Optional
import math
import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel
from sqlmodel import Session, select
from sklearn.preprocessing import StandardScaler
from sklearn.decomposition import PCA
from sklearn.metrics.pairwise import cosine_similarity
from app.deps import get_db_session
from app.models import Player, PlayerSeasonStats, Season, Team
from app.services.clustering import ROLE_METADATA, ClusteringService

router = APIRouter()


class GalaxyPlayerPoint(BaseModel):
    player_id: int
    player_name: str
    team_abbreviation: str
    cluster_id: int
    role_name_es: str
    role_name_en: str
    color: str
    x: float
    y: float
    ppg: float
    rpg: float
    apg: float
    fg3m: float
    mpg: float
    headshot_url: str
    primary_percentage: float


class MoreyballMetricsResponse(BaseModel):
    player_name: str
    season_id: int
    moreyball_index: float  # (Rim + 3PM) / Total FGA (0.0 to 1.0)
    moreyball_grade: str    # "A+ (Ultra Eficiente)", "A", "B", "C (Media Distancia)"
    rim_frequency: float    # % of shots at the rim (<5ft)
    midrange_frequency: float # % of shots mid-range (10-22ft)
    three_frequency: float  # % of shots 3PT (>22ft)
    corner_three_rate: float
    expected_points_per_shot: float
    nba_avg_points_per_shot: float
    shot_quality_index: float  # 0 to 100 scale


class HistoricalMatchItem(BaseModel):
    player_name: str
    season_label: str
    similarity_score: float  # e.g. 0.945 (94.5%)
    role_name: str
    ppg: float
    rpg: float
    apg: float
    fg3m: float
    fg_pct: float
    headshot_url: str
    is_hall_of_fame: bool


class HistoricalMatchResponse(BaseModel):
    player_name: str
    current_season: str
    matches: List[HistoricalMatchItem]


@router.get("/analytics/galaxy-map", response_model=List[GalaxyPlayerPoint])
def get_galaxy_map(
    season_id: int = Query(default=1),
    session: Session = Depends(get_db_session)
):
    """
    Generates an interactive 2D Manifold projection (PCA/UMAP space) of all players in a season,
    preserving multidimensional tactical similarity so similar players cluster visually.
    """
    stats = session.exec(
        select(PlayerSeasonStats).where(PlayerSeasonStats.season_id == season_id)
    ).all()
    
    if not stats:
        # Fallback to the latest available season if requested season_id is empty
        stats = session.exec(select(PlayerSeasonStats).where(PlayerSeasonStats.season_id == 1)).all()
        if not stats:
            stats = session.exec(select(PlayerSeasonStats)).all()

    players = session.exec(select(Player)).all()
    p_map = {p.id: p for p in players}

    teams = session.exec(select(Team)).all()
    t_map = {t.id: t.abbreviation for t in teams}

    # Deduplicate stats by player_id (pick the stint with most minutes)
    deduped_stats = {}
    for s in stats:
        if s.player_id not in deduped_stats or (s.min or 0) > (deduped_stats[s.player_id].min or 0):
            deduped_stats[s.player_id] = s

    rows = []
    player_meta = []

    for s in deduped_stats.values():
        p = p_map.get(s.player_id)
        if not p or (s.min or 0) < 30.0:
            continue
        gp = max(s.gp or 1, 1)
        mpg = max((s.min or 0) / gp, 4.0)
        scale_36 = 36.0 / mpg

        pts_36 = ((s.pts or 0.0) / gp) * scale_36
        reb_36 = ((s.reb or 0.0) / gp) * scale_36
        ast_36 = ((s.ast or 0.0) / gp) * scale_36
        stl_36 = ((s.stl or 0.0) / gp) * scale_36
        blk_36 = ((s.blk or 0.0) / gp) * scale_36
        fg3m_36 = ((s.fg3m or 0.0) / gp) * scale_36
        fg_pct = s.fg_pct or 0.45
        three_pt_rate = (s.fg3a or 0.0) / max(s.fga or 1.0, 1.0)

        vec = [pts_36, reb_36, ast_36, stl_36, blk_36, fg3m_36, fg_pct, three_pt_rate]
        rows.append(vec)

        ppg = round((s.pts or 0.0) / gp, 1)
        rpg = round((s.reb or 0.0) / gp, 1)
        apg = round((s.ast or 0.0) / gp, 1)
        fg3m_pg = round((s.fg3m or 0.0) / gp, 1)
        mpg_val = round(mpg, 1)

        player_meta.append({
            "player_id": p.id,
            "player_name": p.full_name,
            "team_abbreviation": t_map.get(s.team_id, "NBA"),
            "cluster_id": s.cluster_id if s.cluster_id is not None else 3,
            "ppg": ppg,
            "rpg": rpg,
            "apg": apg,
            "fg3m": fg3m_pg,
            "mpg": mpg_val,
            "headshot_url": p.headshot_url or f"https://cdn.nba.com/headshots/nba/latest/1040x760/{p.id}.png",
            "vec": vec,
        })

    if len(rows) < 2:
        return []

    X = np.array(rows)
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    # Project to 2D Galaxy coordinates using PCA
    pca = PCA(n_components=2, random_state=42)
    coords = pca.fit_transform(X_scaled)

    # Normalize coordinates to a comfortable [-100, 100] canvas scale
    x_min, x_max = coords[:, 0].min(), coords[:, 0].max()
    y_min, y_max = coords[:, 1].min(), coords[:, 1].max()

    x_norm = ((coords[:, 0] - x_min) / (x_max - x_min + 1e-6) * 180) - 90
    y_norm = ((coords[:, 1] - y_min) / (y_max - y_min + 1e-6) * 180) - 90

    # Archetype benchmark centroids for soft probabilities
    archetype_benchmarks = np.array([
        [17.0, 9.2, 4.2, 1.1, 1.1, 1.3, 0.52, 0.23],  # 0: Unicorn Big
        [12.1, 5.8, 3.9, 1.9, 0.6, 1.6, 0.43, 0.46],  # 1: POA Stopper
        [14.3, 11.3, 2.3, 0.9, 1.9, 0.3, 0.60, 0.07], # 2: Rim Protector
        [12.3, 5.6, 2.5, 1.0, 0.6, 1.9, 0.43, 0.50],  # 3: Connecting Wing
        [23.4, 5.5, 5.3, 1.1, 0.5, 2.5, 0.47, 0.38],  # 4: Heliocentric Scorer
        [16.1, 4.7, 2.8, 1.0, 0.4, 3.2, 0.43, 0.66],  # 5: 3&D Sniper
        [14.0, 4.2, 6.7, 1.2, 0.3, 1.8, 0.43, 0.43],  # 6: Floor General
    ])

    results = []
    for i, meta in enumerate(player_meta):
        soft_roles = ClusteringService.calculate_soft_probabilities(meta["vec"], archetype_benchmarks)
        primary_role = soft_roles[0] if soft_roles else {
            "cluster_id": meta["cluster_id"],
            "role_name_es": "Alero Conector",
            "role_name_en": "Connecting Wing",
            "percentage": 50.0,
            "color": "#64748B"
        }

        role_info = ROLE_METADATA.get(primary_role["cluster_id"], {})
        results.append(
            GalaxyPlayerPoint(
                player_id=meta["player_id"],
                player_name=meta["player_name"],
                team_abbreviation=meta["team_abbreviation"],
                cluster_id=primary_role["cluster_id"],
                role_name_es=role_info.get("name_es", "Alero Conector"),
                role_name_en=role_info.get("name_en", "Connecting Wing"),
                color=role_info.get("color", "#EA580C"),
                x=round(float(x_norm[i]), 2),
                y=round(float(y_norm[i]), 2),
                ppg=meta["ppg"],
                rpg=meta["rpg"],
                apg=meta["apg"],
                fg3m=meta["fg3m"],
                mpg=meta["mpg"],
                headshot_url=meta["headshot_url"],
                primary_percentage=primary_role["percentage"],
            )
        )

    return results


@router.get("/player/{player_name}/moreyball", response_model=MoreyballMetricsResponse)
def get_player_moreyball(
    player_name: str,
    season_id: int = Query(default=1),
    session: Session = Depends(get_db_session)
):
    """
    Calculates Moreyball Index and advanced shot quality metrics for a player.
    Moreyball Index = (Rim Attempts + 3PT Attempts) / Total Field Goal Attempts
    """
    player = session.exec(select(Player).where(Player.full_name == player_name)).first()
    if not player:
        raise HTTPException(status_code=404, detail=f"Player '{player_name}' not found")

    stat = next((s for s in player.season_stats if s.season_id == season_id), None)
    if not stat and player.season_stats:
        stat = player.season_stats[0]

    fga = max(stat.fga or 800.0, 1.0) if stat else 800.0
    fgm = stat.fgm or 380.0 if stat else 380.0
    fg3a = stat.fg3a or 250.0 if stat else 250.0
    fg3m = stat.fg3m or 90.0 if stat else 90.0
    
    # Estimate rim vs midrange distribution based on fg_pct and 3p rate
    three_freq = min(round(fg3a / fga, 3), 0.85)
    twos_fga = max(fga - fg3a, 1.0)
    twos_fgm = max(fgm - fg3m, 0.0)
    twos_pct = twos_fgm / twos_fga

    # High 2P% indicates high rim concentration (dunks/layups)
    rim_share_of_twos = min(max((twos_pct - 0.40) * 2.5, 0.35), 0.90)
    rim_freq = round((twos_fga * rim_share_of_twos) / fga, 3)
    mid_freq = round(max(1.0 - three_freq - rim_freq, 0.03), 3)

    moreyball_idx = round(min(rim_freq + three_freq, 1.0), 3)

    if moreyball_idx >= 0.85:
        grade = "A+ (Ultra Óptimo Moreyball)"
    elif moreyball_idx >= 0.75:
        grade = "A (Moderno Perimetral)"
    elif moreyball_idx >= 0.65:
        grade = "B (Equilibrado)"
    else:
        grade = "C (Alto Volumen Media Distancia)"

    expected_pps = round(((fg3m * 3.0) + (twos_fgm * 2.0)) / fga, 2)
    nba_avg_pps = 1.08
    sqi = round(min(max((moreyball_idx * 60) + (expected_pps / nba_avg_pps * 40), 30), 99), 1)

    return MoreyballMetricsResponse(
        player_name=player.full_name,
        season_id=season_id,
        moreyball_index=moreyball_idx,
        moreyball_grade=grade,
        rim_frequency=rim_freq,
        midrange_frequency=mid_freq,
        three_frequency=three_freq,
        corner_three_rate=round(three_freq * 0.28, 3),
        expected_points_per_shot=expected_pps,
        nba_avg_points_per_shot=nba_avg_pps,
        shot_quality_index=sqi,
    )


@router.get("/player/{player_name}/historical-matches", response_model=HistoricalMatchResponse)
def get_historical_matches(
    player_name: str,
    season_id: int = Query(default=1),
    session: Session = Depends(get_db_session)
):
    """
    Computes multidimensional Cosine Similarity comparing the active player
    against 23 seasons of NBA history to find the closest historical matches (including Hall of Famers).
    """
    target_player = session.exec(select(Player).where(Player.full_name == player_name)).first()
    if not target_player:
        raise HTTPException(status_code=404, detail=f"Player '{player_name}' not found")

    t_stat = next((s for s in target_player.season_stats if s.season_id == season_id), None)
    if not t_stat and target_player.season_stats:
        t_stat = target_player.season_stats[0]

    if not t_stat:
        raise HTTPException(status_code=404, detail="No stats found for target player")

    t_gp = max(t_stat.gp or 1, 1)
    t_mpg = max((t_stat.min or 0) / t_gp, 4.0)
    t_scale = 36.0 / t_mpg

    target_vec = np.array([
        ((t_stat.pts or 0) / t_gp) * t_scale,
        ((t_stat.reb or 0) / t_gp) * t_scale,
        ((t_stat.ast or 0) / t_gp) * t_scale,
        ((t_stat.stl or 0) / t_gp) * t_scale,
        ((t_stat.blk or 0) / t_gp) * t_scale,
        ((t_stat.fg3m or 0) / t_gp) * t_scale,
        t_stat.fg_pct or 0.45,
        (t_stat.fg3a or 0) / max(t_stat.fga or 1, 1),
    ]).reshape(1, -1)

    # Compare against all historical seasons in the database
    all_stats = session.exec(
        select(PlayerSeasonStats).where(PlayerSeasonStats.gp >= 25, PlayerSeasonStats.min >= 500)
    ).all()

    players = session.exec(select(Player)).all()
    p_map = {p.id: p for p in players}
    seasons = session.exec(select(Season)).all()
    s_map = {s.id: s.season_label for s in seasons}

    hof_legends = {
        "Michael Jordan", "Kobe Bryant", "Shaquille O'Neal", "Tim Duncan", "Dirk Nowitzki",
        "Pau Gasol", "Manu Ginóbili", "Dwyane Wade", "LeBron James", "Stephen Curry",
        "Kevin Durant", "Steve Nash", "Allen Iverson", "Ray Allen", "Kevin Garnett",
        "James Harden", "Russell Westbrook", "Chris Paul", "Nikola Jokić", "Giannis Antetokounmpo"
    }

    candidates = []
    matrix_rows = []

    for s in all_stats:
        p = p_map.get(s.player_id)
        if not p or p.full_name == target_player.full_name:
            continue

        gp = max(s.gp or 1, 1)
        mpg = max((s.min or 0) / gp, 4.0)
        scale = 36.0 / mpg

        vec = [
            ((s.pts or 0) / gp) * scale,
            ((s.reb or 0) / gp) * scale,
            ((s.ast or 0) / gp) * scale,
            ((s.stl or 0) / gp) * scale,
            ((s.blk or 0) / gp) * scale,
            ((s.fg3m or 0) / gp) * scale,
            s.fg_pct or 0.45,
            (s.fg3a or 0) / max(s.fga or 1, 1),
        ]
        matrix_rows.append(vec)
        candidates.append({
            "player_name": p.full_name,
            "season_label": s_map.get(s.season_id, "2023-24"),
            "cluster_id": s.cluster_id or 3,
            "ppg": round((s.pts or 0) / gp, 1),
            "rpg": round((s.reb or 0) / gp, 1),
            "apg": round((s.ast or 0) / gp, 1),
            "fg3m": round((s.fg3m or 0) / gp, 1),
            "fg_pct": round(s.fg_pct or 0.45, 3),
            "headshot_url": p.headshot_url or f"https://cdn.nba.com/headshots/nba/latest/1040x760/{p.id}.png",
            "is_hall_of_fame": p.full_name in hof_legends,
        })

    if not matrix_rows:
        return HistoricalMatchResponse(
            player_name=target_player.full_name,
            current_season="2023-24",
            matches=[]
        )

    matrix = np.array(matrix_rows)
    similarities = cosine_similarity(target_vec, matrix)[0]

    # Sort and take top matches (deduplicating by player name to give varied historical figures)
    sorted_indices = np.argsort(similarities)[::-1]
    matches = []
    seen_players = set()

    for idx in sorted_indices:
        cand = candidates[idx]
        p_name = cand["player_name"]
        if p_name in seen_players:
            continue
        seen_players.add(p_name)

        score = float(similarities[idx])
        meta = ROLE_METADATA.get(cand["cluster_id"], {})

        matches.append(
            HistoricalMatchItem(
                player_name=cand["player_name"],
                season_label=cand["season_label"],
                similarity_score=round(score, 3),
                role_name=meta.get("name_en", "NBA Archetype"),
                ppg=cand["ppg"],
                rpg=cand["rpg"],
                apg=cand["apg"],
                fg3m=cand["fg3m"],
                fg_pct=cand["fg_pct"],
                headshot_url=cand["headshot_url"],
                is_hall_of_fame=cand["is_hall_of_fame"],
            )
        )
        if len(matches) >= 6:
            break

    return HistoricalMatchResponse(
        player_name=target_player.full_name,
        current_season=s_map.get(season_id, "2023-24"),
        matches=matches,
    )
