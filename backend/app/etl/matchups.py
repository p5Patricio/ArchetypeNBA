"""
ETL Ingestion script for NBA 1v1 Matchup Tracking Data.
Fetches direct defensive matchup statistics from NBA Stats (LeagueSeasonMatchups)
and stores them in PostgreSQL with per-75 possession and True Shooting (TS%) normalization.

Usage:
    # Ingest 3-year baseline for Luka Doncic
    python -m app.etl.matchups --player-name "Luka Doncic" --seasons 2021-22 2022-23 2023-24

    # Ingest for specific player ID
    python -m app.etl.matchups --player-id 1629029 --seasons 2023-24

    # Ingest entire league for a season
    python -m app.etl.matchups --seasons 2023-24
"""
import argparse
import os
import sys
import time
from typing import Dict, List, Optional

import pandas as pd
from sqlmodel import Session, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from tenacity import retry, stop_after_attempt, wait_exponential
from tqdm import tqdm

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.deps import get_db_context
from app.models import Player, Season, PlayerMatchupStats
from nba_api.stats.endpoints import leagueseasonmatchups
from nba_api.stats.static import players as static_players

REQUEST_DELAY = 1.0  # seconds between NBA API requests


def _get_or_create_season(session: Session, season_label: str) -> Season:
    stmt = select(Season).where(Season.season_label == season_label)
    season = session.exec(stmt).first()
    if season:
        return season
    season = Season(season_label=season_label)
    session.add(season)
    session.commit()
    session.refresh(season)
    return season


def _resolve_player(session: Session, player_id: int, player_name: str, cache: Dict[int, Player]) -> Player:
    if player_id in cache:
        return cache[player_id]

    player = session.get(Player, player_id)
    if not player:
        # Check by name if ID differs
        player = session.exec(select(Player).where(Player.full_name == player_name)).first()
        if not player:
            player = Player(id=player_id, full_name=player_name)
            session.add(player)
            session.commit()
            session.refresh(player)

    cache[player_id] = player
    return player


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def fetch_matchups_data(season: str, player_id: Optional[int] = None) -> Optional[pd.DataFrame]:
    """Fetch matchup tracking data from NBA API for a season and optional player."""
    try:
        kwargs = {"season": season}
        if player_id:
            kwargs["off_player_id_nullable"] = str(player_id)

        endpoint = leagueseasonmatchups.LeagueSeasonMatchups(**kwargs)
        df = endpoint.get_data_frames()[0]
        if df.empty:
            return None
        return df
    except Exception as e:
        if "timeout" in str(e).lower() or "connection" in str(e).lower():
            raise
        print(f"Error fetching matchups for season={season}, player_id={player_id}: {e}")
        return None


def _safe_float(val, default: float = 0.0) -> float:
    if val is None or pd.isna(val):
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _parse_min_string(val) -> float:
    if val is None or pd.isna(val):
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    val_str = str(val).strip()
    if not val_str:
        return 0.0
    if ":" in val_str:
        parts = val_str.split(":")
        try:
            minutes = float(parts[0])
            seconds = float(parts[1]) if len(parts) > 1 else 0.0
            return round(minutes + (seconds / 60.0), 2)
        except (ValueError, TypeError):
            return 0.0
    return _safe_float(val_str, 0.0)


def calculate_metrics(row: pd.Series) -> Dict[str, float]:
    poss = _safe_float(row.get("PARTIAL_POSS", 0.0))
    pts = _safe_float(row.get("PLAYER_PTS", 0.0))
    ast = _safe_float(row.get("MATCHUP_AST", 0.0))
    tov = _safe_float(row.get("MATCHUP_TOV", 0.0))
    fga = _safe_float(row.get("MATCHUP_FGA", 0.0))
    fta = _safe_float(row.get("MATCHUP_FTA", 0.0))

    # True Shooting %: PTS / (2 * (FGA + 0.44 * FTA))
    denom_ts = 2.0 * (fga + 0.44 * fta)
    ts_pct = (pts / denom_ts) * 100.0 if denom_ts > 0 else 0.0

    # Per 75 possessions
    pts_per_75 = (pts / poss) * 75.0 if poss > 0 else 0.0
    ast_per_75 = (ast / poss) * 75.0 if poss > 0 else 0.0
    tov_per_75 = (tov / poss) * 75.0 if poss > 0 else 0.0

    return {
        "ts_pct": round(ts_pct, 2),
        "pts_per_75": round(pts_per_75, 2),
        "ast_per_75": round(ast_per_75, 2),
        "tov_per_75": round(tov_per_75, 2),
    }


def ingest_matchups_dataframe(session: Session, df: pd.DataFrame, season: Season) -> Dict[str, int]:
    summary = {"inserted_or_updated": 0, "errors": 0}
    player_cache: Dict[int, Player] = {}

    # Extract all distinct players involved to batch-resolve
    off_ids = df[["OFF_PLAYER_ID", "OFF_PLAYER_NAME"]].drop_duplicates()
    def_ids = df[["DEF_PLAYER_ID", "DEF_PLAYER_NAME"]].drop_duplicates()

    for _, row in off_ids.iterrows():
        _resolve_player(session, int(row["OFF_PLAYER_ID"]), str(row["OFF_PLAYER_NAME"]), player_cache)
    for _, row in def_ids.iterrows():
        _resolve_player(session, int(row["DEF_PLAYER_ID"]), str(row["DEF_PLAYER_NAME"]), player_cache)

    records = []
    for _, row in df.iterrows():
        try:
            off_pid = int(row["OFF_PLAYER_ID"])
            def_pid = int(row["DEF_PLAYER_ID"])

            off_player = player_cache.get(off_pid)
            def_player = player_cache.get(def_pid)
            if not off_player or not def_player:
                continue

            metrics = calculate_metrics(row)

            record = {
                "season_id": season.id,
                "off_player_id": off_player.id,
                "def_player_id": def_player.id,
                "gp": int(_safe_float(row.get("GP", 0))),
                "matchup_min": _parse_min_string(row.get("MATCHUP_MIN")),
                "partial_poss": _safe_float(row.get("PARTIAL_POSS", 0.0)),
                "player_pts": _safe_float(row.get("PLAYER_PTS", 0.0)),
                "team_pts": _safe_float(row.get("TEAM_PTS", 0.0)),
                "matchup_ast": _safe_float(row.get("MATCHUP_AST", 0.0)),
                "matchup_tov": _safe_float(row.get("MATCHUP_TOV", 0.0)),
                "matchup_blk": _safe_float(row.get("MATCHUP_BLK", 0.0)),
                "matchup_fgm": _safe_float(row.get("MATCHUP_FGM", 0.0)),
                "matchup_fga": _safe_float(row.get("MATCHUP_FGA", 0.0)),
                "matchup_fg_pct": _safe_float(row.get("MATCHUP_FG_PCT", 0.0)),
                "matchup_fg3m": _safe_float(row.get("MATCHUP_FG3M", 0.0)),
                "matchup_fg3a": _safe_float(row.get("MATCHUP_FG3A", 0.0)),
                "matchup_fg3_pct": _safe_float(row.get("MATCHUP_FG3_PCT", 0.0)),
                "help_blk": _safe_float(row.get("HELP_BLK", 0.0)),
                "help_fgm": _safe_float(row.get("HELP_FGM", 0.0)),
                "help_fga": _safe_float(row.get("HELP_FGA", 0.0)),
                "help_fg_perc": _safe_float(row.get("HELP_FG_PERC", 0.0)),
                "matchup_ftm": _safe_float(row.get("MATCHUP_FTM", 0.0)),
                "matchup_fta": _safe_float(row.get("MATCHUP_FTA", 0.0)),
                "sfl": _safe_float(row.get("SFL", 0.0)),
                "matchup_time_sec": _safe_float(row.get("MATCHUP_TIME_SEC", 0.0)),
                **metrics,
            }
            records.append(record)
        except Exception as e:
            summary["errors"] += 1
            print(f"Error parsing row: {e}")
            continue

    # Bulk upsert using PostgreSQL ON CONFLICT DO UPDATE
    if records:
        chunk_size = 500
        for i in range(0, len(records), chunk_size):
            chunk = records[i:i + chunk_size]
            stmt = pg_insert(PlayerMatchupStats).values(chunk)
            update_dict = {
                c.name: c
                for c in stmt.excluded
                if c.name not in ("id", "season_id", "off_player_id", "def_player_id")
            }
            stmt = stmt.on_conflict_do_update(
                constraint="uq_matchup_season_off_def",
                set_=update_dict,
            )
            session.exec(stmt)
            session.commit()
            summary["inserted_or_updated"] += len(chunk)

    return summary


def backfill_matchups(
    seasons: List[str],
    player_id: Optional[int] = None,
) -> Dict[str, any]:
    summary = {
        "seasons": seasons,
        "player_id": player_id,
        "total_rows_inserted_or_updated": 0,
        "errors": 0,
    }

    with get_db_context() as session:
        for season_label in seasons:
            print(f"\n=== Ingesting Matchups for Season {season_label} ===")
            season = _get_or_create_season(session, season_label)

            df = fetch_matchups_data(season=season_label, player_id=player_id)
            time.sleep(REQUEST_DELAY)

            if df is None or df.empty:
                print(f"No matchup data returned for season {season_label}")
                continue

            print(f"Fetched {len(df)} matchup records. Ingesting into PostgreSQL...")
            result = ingest_matchups_dataframe(session, df, season)
            summary["total_rows_inserted_or_updated"] += result["inserted_or_updated"]
            summary["errors"] += result["errors"]
            print(f"Season {season_label} done: {result['inserted_or_updated']} records upserted.")

    return summary


def main():
    parser = argparse.ArgumentParser(description="Backfill NBA 1v1 Matchup tracking data into PostgreSQL")
    parser.add_argument(
        "--seasons",
        nargs="+",
        default=["2023-24"],
        help="NBA seasons to backfill (e.g. 2021-22 2022-23 2023-24 2024-25)",
    )
    parser.add_argument(
        "--player-id",
        type=int,
        default=None,
        help="Optional offensive player ID (e.g. 1629029 for Luka Doncic)",
    )
    parser.add_argument(
        "--player-name",
        type=str,
        default=None,
        help="Optional offensive player name to lookup ID (e.g. 'Luka Doncic')",
    )

    args = parser.parse_args()

    pid = args.player_id
    if not pid and args.player_name:
        found = static_players.find_players_by_full_name(args.player_name)
        if found:
            pid = found[0]["id"]
            print(f"Resolved player '{args.player_name}' to ID {pid}")
        else:
            print(f"Could not find player with name '{args.player_name}'")
            sys.exit(1)

    print(f"Starting Matchup Backfill for seasons={args.seasons}, player_id={pid}")
    results = backfill_matchups(seasons=args.seasons, player_id=pid)
    print("\n=== Backfill Summary ===")
    print(results)


if __name__ == "__main__":
    main()
