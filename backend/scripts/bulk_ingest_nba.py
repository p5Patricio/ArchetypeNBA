import sys
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Set

# Add backend directory to sys.path
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

import numpy as np
import pandas as pd
import sqlalchemy
from sqlmodel import Session, select, func, SQLModel
from sklearn.preprocessing import StandardScaler
from sklearn.metrics.pairwise import cosine_similarity

from app.deps import engine, create_db_and_tables
from app.models import (
    Season, Player, Team, PlayerSeasonStats,
    PlayerGameLog, PlayerShot, PlayerAdvancedStats,
    PlayerSimilarity, TeamEloRating, TeamSeasonStats
)
from app.services.clustering import ClusteringService
from app.repositories.stats import StatsRepository

# nba_api imports
from nba_api.stats.static import teams as static_teams, players as static_players
from nba_api.stats.endpoints import (
    leaguedashplayerstats,
    playergamelogs,
)

# Ingest all seasons from LeBron James's rookie year (2003-04) to present (2025-26)
TARGET_SEASONS = [f"{year}-{str(year+1)[-2:]}" for year in range(2003, 2026)]
BATCH_SIZE = 2000


def safe_int(val, default=0) -> int:
    try:
        if pd.isna(val):
            return default
        return int(float(val))
    except Exception:
        return default


def safe_float(val, default=0.0) -> float:
    try:
        if pd.isna(val):
            return default
        return float(val)
    except Exception:
        return default


def get_or_create_season(session: Session, season_label: str) -> Season:
    stmt = select(Season).where(Season.season_label == season_label)
    season = session.exec(stmt).first()
    if not season:
        season = Season(season_label=season_label, is_active=(season_label in ["2025-26", "2024-25"]))
        session.add(season)
        session.commit()
        session.refresh(season)
    return season


def resolve_team(
    session: Session,
    t_abbr: str,
    team_id_raw: Optional[int],
    teams_by_abbr: Dict[str, int],
    teams_by_id: Dict[int, Team],
) -> int:
    if not t_abbr and not team_id_raw:
        return 0

    if t_abbr and t_abbr in teams_by_abbr:
        return teams_by_abbr[t_abbr]

    t_id = safe_int(team_id_raw)
    if t_id and t_id in teams_by_id:
        if t_abbr:
            teams_by_abbr[t_abbr] = t_id
        return t_id

    # Check database directly by ID
    if t_id:
        existing_id = session.exec(select(Team).where(Team.id == t_id)).first()
        if existing_id:
            if t_abbr:
                teams_by_abbr[t_abbr] = existing_id.id
            teams_by_id[existing_id.id] = existing_id
            return existing_id.id

    # Check database directly by abbreviation
    if t_abbr:
        existing_abbr = session.exec(select(Team).where(Team.abbreviation == t_abbr)).first()
        if existing_abbr:
            teams_by_abbr[t_abbr] = existing_abbr.id
            teams_by_id[existing_abbr.id] = existing_abbr
            return existing_abbr.id

    # Create new team entry
    new_id = t_id or (abs(hash(t_abbr)) % 100000)
    t_obj = Team(
        id=new_id,
        abbreviation=t_abbr or f"T_{new_id}",
        full_name=t_abbr or f"Team {new_id}",
        city=t_abbr or "NBA",
        conference="NBA",
        division="NBA",
    )
    session.add(t_obj)
    session.commit()
    if t_abbr:
        teams_by_abbr[t_abbr] = new_id
    teams_by_id[new_id] = t_obj
    return new_id


def sync_teams_and_players(session: Session):
    print("\n--- 1. Sincronizando Franquicias y Jugadores ---", flush=True)
    
    # 1. Teams
    all_teams = static_teams.get_teams()
    existing_teams = session.exec(select(Team)).all()
    teams_by_abbr = {t.abbreviation: t for t in existing_teams}
    teams_by_id = {t.id: t for t in existing_teams}

    for t in all_teams:
        team_id = t["id"]
        abbr = t["abbreviation"]
        if abbr in teams_by_abbr or team_id in teams_by_id:
            continue
        team = Team(
            id=team_id,
            abbreviation=abbr,
            full_name=t["full_name"],
            city=t["city"],
            conference="East" if abbr in ["BOS", "BKN", "NYK", "PHI", "TOR", "CHI", "CLE", "DET", "IND", "MIL", "ATL", "CHA", "MIA", "ORL", "WAS", "CHH", "NJN"] else "West",
            division=t.get("division", "NBA"),
        )
        session.add(team)
        teams_by_abbr[abbr] = team
        teams_by_id[team_id] = team
    session.commit()
    print(f" -> {len(all_teams)} equipos sincronizados.", flush=True)

    # 2. All Historical Players
    all_players = static_players.get_players()
    print(f" -> Sincronizando directorio historico de {len(all_players)} jugadores NBA...", flush=True)
    
    existing_pids = set(session.exec(select(Player.id)).all())
    new_players = []
    for p in all_players:
        p_id = p["id"]
        if p_id not in existing_pids:
            player = Player(
                id=p_id,
                full_name=p["full_name"],
                headshot_url=f"https://cdn.nba.com/headshots/nba/latest/1040x760/{p_id}.png",
            )
            new_players.append(player)
            existing_pids.add(p_id)
            if len(new_players) >= BATCH_SIZE:
                session.add_all(new_players)
                session.commit()
                new_players = []

    if new_players:
        session.add_all(new_players)
        session.commit()
    print(f" -> Directorio de jugadores sincronizado en PostgreSQL.", flush=True)


def ingest_season_stats_and_advanced(
    session: Session,
    season_label: str,
    teams_by_abbr: Dict[str, int],
    teams_by_id: Dict[int, Team],
    players_cache: Set[int],
):
    season = get_or_create_season(session, season_label)
    
    # 1. Base Stats
    try:
        base_api = leaguedashplayerstats.LeagueDashPlayerStats(
            season=season_label,
            measure_type_detailed_defense="Base",
            timeout=30,
        )
        df_base = base_api.get_data_frames()[0]
        time.sleep(0.8)
    except Exception as e:
        print(f"[{season_label}] Error obteniendo base stats: {e}", flush=True)
        return

    # 2. Advanced Stats
    try:
        adv_api = leaguedashplayerstats.LeagueDashPlayerStats(
            season=season_label,
            measure_type_detailed_defense="Advanced",
            timeout=30,
        )
        df_adv = adv_api.get_data_frames()[0]
        time.sleep(0.8)
    except Exception as e:
        df_adv = pd.DataFrame()

    adv_map = {}
    if not df_adv.empty and "PLAYER_ID" in df_adv.columns:
        for _, r in df_adv.iterrows():
            if pd.notna(r.get("PLAYER_ID")):
                adv_map[safe_int(r["PLAYER_ID"])] = r

    inserted_stats = 0
    updated_stats = 0
    adv_count = 0

    for _, row in df_base.iterrows():
        p_id_raw = row.get("PLAYER_ID")
        if pd.isna(p_id_raw):
            continue
        p_id = safe_int(p_id_raw)
        p_name = str(row.get("PLAYER_NAME", f"Player {p_id}"))
        t_abbr = str(row.get("TEAM_ABBREVIATION", ""))
        team_id = resolve_team(session, t_abbr, row.get("TEAM_ID"), teams_by_abbr, teams_by_id)

        if p_id not in players_cache:
            player = Player(id=p_id, full_name=p_name, headshot_url=f"https://cdn.nba.com/headshots/nba/latest/1040x760/{p_id}.png")
            session.add(player)
            session.commit()
            players_cache.add(p_id)

        stat_vals = {
            "gp": safe_int(row.get("GP")),
            "gs": safe_int(row.get("GS")),
            "min": safe_float(row.get("MIN")),
            "fgm": safe_float(row.get("FGM")),
            "fga": safe_float(row.get("FGA")),
            "fg_pct": safe_float(row.get("FG_PCT")),
            "fg3m": safe_float(row.get("FG3M")),
            "fg3a": safe_float(row.get("FG3A")),
            "fg3_pct": safe_float(row.get("FG3_PCT")),
            "ftm": safe_float(row.get("FTM")),
            "fta": safe_float(row.get("FTA")),
            "ft_pct": safe_float(row.get("FT_PCT")),
            "oreb": safe_float(row.get("OREB")),
            "dreb": safe_float(row.get("DREB")),
            "reb": safe_float(row.get("REB")),
            "ast": safe_float(row.get("AST")),
            "stl": safe_float(row.get("STL")),
            "blk": safe_float(row.get("BLK")),
            "tov": safe_float(row.get("TOV")),
            "pf": safe_float(row.get("PF")),
            "pts": safe_float(row.get("PTS")),
        }

        existing = session.exec(
            select(PlayerSeasonStats).where(
                PlayerSeasonStats.player_id == p_id,
                PlayerSeasonStats.season_id == season.id,
                PlayerSeasonStats.team_id == team_id,
            )
        ).first()

        if existing:
            for k, v in stat_vals.items():
                setattr(existing, k, v)
            session.add(existing)
            updated_stats += 1
        else:
            new_stat = PlayerSeasonStats(player_id=p_id, team_id=team_id, season_id=season.id, **stat_vals)
            session.add(new_stat)
            inserted_stats += 1

        # Advanced stats
        if p_id in adv_map:
            adv_row = adv_map[p_id]
            ts = safe_float(adv_row.get("TS_PCT")) if pd.notna(adv_row.get("TS_PCT")) else None
            usg = safe_float(adv_row.get("USG_PCT")) if pd.notna(adv_row.get("USG_PCT")) else None
            pie = safe_float(adv_row.get("PIE")) if pd.notna(adv_row.get("PIE")) else None
            ast_pct = safe_float(adv_row.get("AST_PCT")) if pd.notna(adv_row.get("AST_PCT")) else None
            reb_pct = safe_float(adv_row.get("REB_PCT")) if pd.notna(adv_row.get("REB_PCT")) else None
            net_rtg = safe_float(adv_row.get("NET_RATING")) if pd.notna(adv_row.get("NET_RATING")) else 0.0
            
            per_est = (pie * 100) if pie else (stat_vals["pts"] + stat_vals["reb"] + stat_vals["ast"]) / max(stat_vals["gp"], 1)
            vorp_est = (net_rtg * (usg or 0.2) * (stat_vals["min"] / 2000.0)) if stat_vals["min"] else 0.0

            existing_adv = session.exec(
                select(PlayerAdvancedStats).where(
                    PlayerAdvancedStats.player_id == p_id,
                    PlayerAdvancedStats.season_id == season.id,
                )
            ).first()

            if existing_adv:
                existing_adv.ts_pct = ts
                existing_adv.usg_pct = usg
                existing_adv.ast_pct = ast_pct
                existing_adv.trb_pct = reb_pct
                existing_adv.per = round(per_est, 1)
                existing_adv.bpm = round(net_rtg, 1)
                existing_adv.vorp = round(vorp_est, 2)
                session.add(existing_adv)
            else:
                new_adv = PlayerAdvancedStats(
                    player_id=p_id,
                    season_id=season.id,
                    ts_pct=ts,
                    usg_pct=usg,
                    ast_pct=ast_pct,
                    trb_pct=reb_pct,
                    per=round(per_est, 1),
                    bpm=round(net_rtg, 1),
                    vorp=round(vorp_est, 2),
                )
                session.add(new_adv)
            adv_count += 1

    session.commit()
    print(f"[{season_label}] Stats: {inserted_stats} ins / {updated_stats} upd | Adv: {adv_count}", flush=True)


def ingest_bulk_game_logs(
    session: Session,
    season_label: str,
    teams_by_abbr: Dict[str, int],
    teams_by_id: Dict[int, Team],
    players_cache: Set[int],
):
    season = get_or_create_season(session, season_label)

    try:
        api_logs = playergamelogs.PlayerGameLogs(season_nullable=season_label, timeout=45)
        df_logs = api_logs.get_data_frames()[0]
        time.sleep(0.8)
    except Exception as e:
        print(f"[{season_label}] Error descargando game logs: {e}", flush=True)
        return

    existing_keys: Set[Tuple[int, str]] = {
        (r[0], r[1]) for r in session.exec(
            select(PlayerGameLog.player_id, PlayerGameLog.game_id).where(PlayerGameLog.season_id == season.id)
        ).all()
    }

    batch = []
    inserted = 0

    for _, row in df_logs.iterrows():
        p_id_raw = row.get("PLAYER_ID")
        game_id_raw = row.get("GAME_ID")
        if pd.isna(p_id_raw) or pd.isna(game_id_raw):
            continue

        p_id = safe_int(p_id_raw)
        game_id = str(game_id_raw).strip()
        if not p_id or not game_id:
            continue

        key = (p_id, game_id)
        if key in existing_keys:
            continue

        t_abbr = str(row.get("TEAM_ABBREVIATION", ""))
        team_id = resolve_team(session, t_abbr, row.get("TEAM_ID"), teams_by_abbr, teams_by_id)

        if p_id not in players_cache:
            player = Player(id=p_id, full_name=str(row.get("PLAYER_NAME", f"Player {p_id}")), headshot_url=f"https://cdn.nba.com/headshots/nba/latest/1040x760/{p_id}.png")
            session.add(player)
            session.commit()
            players_cache.add(p_id)

        game_date_raw = row.get("GAME_DATE")
        game_date = None
        if game_date_raw and pd.notna(game_date_raw):
            try:
                game_date = datetime.strptime(str(game_date_raw), "%Y-%m-%dT%H:%M:%S").date()
            except Exception:
                try:
                    game_date = datetime.strptime(str(game_date_raw), "%Y-%m-%d").date()
                except Exception:
                    pass

        log = PlayerGameLog(
            player_id=p_id,
            team_id=team_id,
            season_id=season.id,
            game_id=game_id,
            game_date=game_date,
            matchup=str(row.get("MATCHUP", "")),
            wl=str(row.get("WL", "")) if pd.notna(row.get("WL")) else None,
            min=safe_int(row.get("MIN")),
            fgm=safe_int(row.get("FGM")),
            fga=safe_int(row.get("FGA")),
            fg_pct=safe_float(row.get("FG_PCT")),
            fg3m=safe_int(row.get("FG3M")),
            fg3a=safe_int(row.get("FG3A")),
            fg3_pct=safe_float(row.get("FG3_PCT")),
            ftm=safe_int(row.get("FTM")),
            fta=safe_int(row.get("FTA")),
            ft_pct=safe_float(row.get("FT_PCT")),
            oreb=safe_int(row.get("OREB")),
            dreb=safe_int(row.get("DREB")),
            reb=safe_int(row.get("REB")),
            ast=safe_int(row.get("AST")),
            stl=safe_int(row.get("STL")),
            blk=safe_int(row.get("BLK")),
            tov=safe_int(row.get("TOV")),
            pf=safe_int(row.get("PF")),
            pts=safe_int(row.get("PTS")),
            plus_minus=safe_int(row.get("PLUS_MINUS")),
        )
        batch.append(log)
        existing_keys.add(key)

        if len(batch) >= BATCH_SIZE:
            session.add_all(batch)
            session.commit()
            inserted += len(batch)
            batch = []

    if batch:
        session.add_all(batch)
        session.commit()
        inserted += len(batch)

    print(f"[{season_label}] Game Logs: {inserted} partidos insertados.", flush=True)


def compute_player_similarities(session: Session, season_id: int):
    stats = session.exec(select(PlayerSeasonStats).where(PlayerSeasonStats.season_id == season_id)).all()
    if len(stats) < 10:
        return

    features = ["pts", "reb", "ast", "stl", "blk", "fg_pct", "fg3_pct", "min"]
    player_data_map: Dict[int, List[float]] = {}
    for s in stats:
        if s.player_id not in player_data_map:
            row = [getattr(s, f, 0) or 0 for f in features]
            player_data_map[s.player_id] = row

    player_ids = list(player_data_map.keys())
    data = [player_data_map[pid] for pid in player_ids]

    scaler = StandardScaler()
    scaled = scaler.fit_transform(data)
    sim_matrix = cosine_similarity(scaled)

    session.exec(sqlalchemy.delete(PlayerSimilarity).where(PlayerSimilarity.season_id == season_id))
    session.commit()

    seen_pairs: Set[Tuple[int, int, int]] = set()
    new_sims = []
    for i in range(len(player_ids)):
        p_id = player_ids[i]
        scores = [(j, sim_matrix[i][j]) for j in range(len(player_ids)) if j != i]
        scores.sort(key=lambda x: x[1], reverse=True)

        for sim_idx, score in scores[:5]:
            sim_p_id = player_ids[sim_idx]
            pair_key = (p_id, season_id, sim_p_id)
            if pair_key in seen_pairs:
                continue
            seen_pairs.add(pair_key)

            sim_obj = PlayerSimilarity(
                player_id=p_id,
                similar_player_id=sim_p_id,
                season_id=season_id,
                similarity_score=float(score),
            )
            new_sims.append(sim_obj)

    if new_sims:
        session.add_all(new_sims)
        session.commit()


def run_full_bulk_ingestion():
    print(f"=== INGESTION HISTORICA NBA (DESDE 2003-04 HASTA 2025-26: {len(TARGET_SEASONS)} TEMPORADAS) ===", flush=True)
    create_db_and_tables()
    
    with Session(engine) as session:
        sync_teams_and_players(session)

        teams_by_id = {t.id: t for t in session.exec(select(Team)).all()}
        teams_by_abbr = {t.abbreviation: t.id for t in session.exec(select(Team)).all()}
        players_cache = set(session.exec(select(Player.id)).all())

        stats_repo = StatsRepository(session)
        clustering_service = ClusteringService(stats_repo)

        for idx, season_label in enumerate(TARGET_SEASONS, start=1):
            print(f"\n>>> [{idx}/{len(TARGET_SEASONS)}] Procesando Temporada: {season_label} <<<", flush=True)
            ingest_season_stats_and_advanced(session, season_label, teams_by_abbr, teams_by_id, players_cache)
            ingest_bulk_game_logs(session, season_label, teams_by_abbr, teams_by_id, players_cache)

            season = get_or_create_season(session, season_label)
            try:
                clustering_service.init_clusters(season.id, k=5)
            except Exception as e:
                pass
            
            compute_player_similarities(session, season.id)

        print("\n========================================================", flush=True)
        print("   INGESTION HISTORICA COMPLETA EN POSTGRESQL!          ", flush=True)
        print("========================================================", flush=True)
        
        p_count = session.exec(select(func.count(Player.id))).one()
        t_count = session.exec(select(func.count(Team.id))).one()
        s_count = session.exec(select(func.count(PlayerSeasonStats.id))).one()
        g_count = session.exec(select(func.count(PlayerGameLog.id))).one()
        a_count = session.exec(select(func.count(PlayerAdvancedStats.id))).one()
        sim_count = session.exec(select(func.count(PlayerSimilarity.id))).one()
        season_count = session.exec(select(func.count(Season.id))).one()

        print(f"Temporadas procesadas:            {season_count}", flush=True)
        print(f"Jugadores totales en DB:          {p_count}", flush=True)
        print(f"Equipos totales en DB:            {t_count}", flush=True)
        print(f"Estadisticas de Temporada en DB:  {s_count}", flush=True)
        print(f"Game Logs (Partidos) en DB:       {g_count}", flush=True)
        print(f"Estadisticas Avanzadas en DB:     {a_count}", flush=True)
        print(f"Pares de Similitud en DB:         {sim_count}", flush=True)
        print("========================================================", flush=True)


if __name__ == "__main__":
    run_full_bulk_ingestion()
