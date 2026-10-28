#!/usr/bin/env python3
"""
Lineup logger: records starters and inactives from nba_api live boxscores before tip-off.
Appends one JSON line per game and run to logs/lineups.jsonl.
Purpose: measure empirically how early starters and inactives appear (research item 6).
"""

import argparse
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import sys
import time
from typing import Callable, Dict, List, Optional

logger = logging.getLogger("lineup_logger")


def parse_game_tipoff(game_dict: Dict) -> Optional[datetime]:
    """Parses UTC tip-off datetime from live scoreboard game dictionary."""
    time_utc_str = game_dict.get("gameTimeUTC")
    if not time_utc_str:
        return None
    try:
        # Handles ISO format, e.g. "2026-10-28T00:30:00Z" or "2026-10-28T00:30:00+00:00"
        clean_str = time_utc_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(clean_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception as e:
        logger.warning(f"Could not parse gameTimeUTC '{time_utc_str}': {e}")
        return None


def extract_team_lineup_info(team_data: Dict) -> Dict:
    """Extracts starter counts, inactive counts, and inactive players from team boxscore data."""
    tricode = team_data.get("teamTricode", "")
    players = team_data.get("players", [])

    starters_count = 0
    not_playing_count = 0
    not_playing_players = []

    for p in players:
        starter_val = str(p.get("starter", "")).strip()
        if starter_val == "1":
            starters_count += 1

        status = str(p.get("status", "")).strip().upper()
        reason = p.get("notPlayingReason") or p.get("notPlayingDescription") or ""

        # Player is considered not playing if inactive or if a reason/description is present
        if status not in ("ACTIVE", "") or reason:
            not_playing_count += 1
            not_playing_players.append(
                {
                    "name": p.get("name", ""),
                    "status": p.get("status", ""),
                    "reason": reason,
                }
            )

    return {
        "tricode": tricode,
        "starters_count": starters_count,
        "not_playing_count": not_playing_count,
        "not_playing_players": not_playing_players,
    }


def build_lineup_record(
    game: Dict,
    boxscore_data: Dict,
    tipoff_utc: datetime,
    now_utc: datetime,
) -> Dict:
    """Builds a single structured record for one game."""
    minutes_to_tip = (tipoff_utc - now_utc).total_seconds() / 60.0

    home_data = boxscore_data.get("homeTeam", {})
    away_data = boxscore_data.get("awayTeam", {})

    return {
        "timestamp": now_utc.isoformat(),
        "game_id": game.get("gameId"),
        "minutes_to_tipoff": round(minutes_to_tip, 1),
        "away_team": extract_team_lineup_info(away_data),
        "home_team": extract_team_lineup_info(home_data),
    }


def default_scoreboard_fetcher(timeout: float = 30.0) -> List[Dict]:
    """Fetches today's live scoreboard from nba_api."""
    from nba_api.live.nba.endpoints import scoreboard

    sb = scoreboard.ScoreBoard(timeout=timeout)
    if sb.games:
        return sb.games.get_dict()
    return []


def default_boxscore_fetcher(game_id: str, timeout: float = 30.0) -> Dict:
    """Fetches live boxscore for a game from nba_api."""
    from nba_api.live.nba.endpoints import boxscore

    bs = boxscore.BoxScore(game_id=game_id, timeout=timeout)
    if bs.game:
        return bs.game.get_dict()
    return {}


def log_lineups(
    window_minutes: int = 60,
    dry_run: bool = False,
    log_file: Optional[Path] = None,
    now: Optional[datetime] = None,
    scoreboard_fetcher: Optional[Callable[[], List[Dict]]] = None,
    boxscore_fetcher: Optional[Callable[[str], Dict]] = None,
) -> int:
    """
    Main lineup logging pipeline.
    Errors are logged rather than raised, ensuring exit code 0.
    Returns the number of games logged.
    """
    now_utc = now or datetime.now(timezone.utc)
    if log_file is None:
        repo_root = Path(__file__).resolve().parents[2]
        log_file = repo_root / "logs" / "lineups.jsonl"

    fetch_sb = scoreboard_fetcher or default_scoreboard_fetcher
    fetch_bs = boxscore_fetcher or default_boxscore_fetcher

    # Fetch scoreboard with 1 retry
    games = None
    for attempt in range(2):
        try:
            games = fetch_sb()
            break
        except Exception as e:
            logger.warning(f"Failed to fetch live scoreboard (attempt {attempt + 1}/2): {e}")
            if attempt == 0:
                time.sleep(1.0)

    if games is None:
        logger.error("Could not retrieve live scoreboard after retry. Exiting cleanly.")
        return 0

    logged_count = 0

    for game in games:
        game_id = game.get("gameId")
        if not game_id:
            continue

        tipoff_utc = parse_game_tipoff(game)
        if not tipoff_utc:
            continue

        minutes_to_tip = (tipoff_utc - now_utc).total_seconds() / 60.0
        # Check window: tipping off within the next window_minutes
        if not (0 <= minutes_to_tip <= window_minutes):
            continue

        # Fetch boxscore with 1 retry
        boxscore_data = None
        for attempt in range(2):
            try:
                boxscore_data = fetch_bs(game_id)
                break
            except Exception as e:
                logger.warning(f"Failed to fetch live boxscore for game {game_id} (attempt {attempt + 1}/2): {e}")
                if attempt == 0:
                    time.sleep(1.0)

        if not boxscore_data:
            logger.warning(f"Skipping game {game_id}: no boxscore data available.")
            continue

        record = build_lineup_record(game, boxscore_data, tipoff_utc, now_utc)
        json_line = json.dumps(record, ensure_ascii=False)

        if dry_run:
            print(f"[dry-run] {json_line}")
        else:
            try:
                log_file.parent.mkdir(parents=True, exist_ok=True)
                with open(log_file, "a", encoding="utf-8") as f:
                    f.write(json_line + "\n")
            except Exception as e:
                logger.error(f"Failed writing to {log_file}: {e}")

        logged_count += 1

    logger.info(f"Lineup logger: logged {logged_count} game(s) within window {window_minutes}m.")
    return logged_count


def main():
    parser = argparse.ArgumentParser(description="Log pre-game NBA lineups and inactives.")
    parser.add_argument(
        "--window-minutes",
        type=int,
        default=60,
        help="Window in minutes before tip-off to poll games (default: 60)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print records to stdout without writing to logs/lineups.jsonl",
    )
    parser.add_argument(
        "--log-file",
        type=Path,
        default=None,
        help="Custom path to output JSONL file (default: logs/lineups.jsonl)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    try:
        log_lineups(
            window_minutes=args.window_minutes,
            dry_run=args.dry_run,
            log_file=args.log_file,
        )
    except Exception as e:
        logger.error(f"Unexpected error in lineup logger: {e}", exc_info=True)

    sys.exit(0)


if __name__ == "__main__":
    main()
