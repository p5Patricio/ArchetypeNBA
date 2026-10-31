#!/usr/bin/env python3
"""
CLI script to fetch and store official NBA injury reports.
Runs up to 3 times on game days only (via nba-injuries.timer or manual invocation).
Controlled by INJURY_PDF_ENABLED and INJURY_MAX_DOWNLOADS_PER_DAY.
"""

import argparse
from datetime import datetime, time, timezone
import logging
import sys
from pathlib import Path
from typing import Optional

# Add backend directory to sys.path
backend_dir = Path(__file__).resolve().parents[1]
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from sqlmodel import Session, select
from app.config import settings
from app.deps import engine
from app.models import Game, InjuryReportSnapshot
from app.services.injury_report_service import InjuryReportService, injury_fetch_due

logger = logging.getLogger("fetch_injuries")


def run_fetch_injuries(
    dry_run: bool = False,
    now: Optional[datetime] = None,
    session: Optional[Session] = None,
) -> int:
    """
    Main routine deciding and executing injury report fetch.
    Returns 0 on success or when exiting cleanly doing nothing.
    """
    # An explicit aware `now` keeps its own zone (tests); otherwise use the machine's local zone, like the tick.
    now_local = now if (now is not None and now.tzinfo is not None) else (now or datetime.now()).astimezone()

    # 1. Config check
    if not settings.INJURY_PDF_ENABLED:
        logger.info("INJURY_PDF_ENABLED is False. Exiting.")
        if dry_run:
            print("[dry-run] INJURY_PDF_ENABLED is False. Exiting 0.")
        return 0

    # 2. Database session
    close_session = False
    if session is None:
        session = Session(engine)
        close_session = True

    try:
        today = now_local.date()
        start_of_day_local = datetime.combine(today, time(0, 0, 0), tzinfo=now_local.tzinfo)
        end_of_day_local = datetime.combine(today, time(23, 59, 59), tzinfo=now_local.tzinfo)

        start_of_day_utc = start_of_day_local.astimezone(timezone.utc)
        end_of_day_utc = end_of_day_local.astimezone(timezone.utc)

        # 3. Find today's scheduled games
        games_today = session.exec(
            select(Game).where(
                Game.commence_time >= start_of_day_utc,
                Game.commence_time <= end_of_day_utc,
                Game.status != "postponed",
            )
        ).all()

        games_commence_times = [g.commence_time for g in games_today]
        if not games_commence_times:
            logger.info("No games scheduled today (%s). Exiting.", today)
            if dry_run:
                print(f"[dry-run] No games scheduled for today ({today}). Exiting 0.")
            return 0

        # 4. Find downloads today
        downloads_today_utc = session.exec(
            select(InjuryReportSnapshot.fetched_at).where(
                InjuryReportSnapshot.fetched_at >= start_of_day_utc,
                InjuryReportSnapshot.fetched_at <= end_of_day_utc,
            )
        ).all()
        downloads_today_local = [d.astimezone(now_local.tzinfo) for d in downloads_today_utc]

        # 5. Check due decision
        due = injury_fetch_due(
            now_local=now_local,
            games_today_commence_times=games_commence_times,
            downloads_today_local_times=downloads_today_local,
            max_per_day=settings.INJURY_MAX_DOWNLOADS_PER_DAY,
        )

        status_msg = (
            f"now={now_local.strftime('%H:%M %Z')}, "
            f"downloads={len(downloads_today_local)}/{settings.INJURY_MAX_DOWNLOADS_PER_DAY}, "
            f"games={len(games_commence_times)}, due={due}"
        )

        if not due:
            logger.info("Injury fetch not due (%s).", status_msg)
            if dry_run:
                print(f"[dry-run] Injury fetch NOT due ({status_msg}). Exiting 0.")
            return 0

        if dry_run:
            print(f"[dry-run] Injury fetch IS DUE ({status_msg}). Would download newest PDF.")
            return 0

        # 6. Perform fetch
        logger.info("Injury fetch is due (%s). Fetching newest report...", status_msg)
        service = InjuryReportService(session=session)
        snap, created, unresolved = service.fetch_and_store_snapshot()
        logger.info(
            "Fetch completed: created=%s, snapshot_id=%s, entries=%s, unresolved_players=%s",
            created,
            getattr(snap, "id", None),
            getattr(snap, "entries_count", 0),
            unresolved,
        )
        return 0

    except Exception as e:
        logger.error("Error in fetch_injuries: %s", e, exc_info=True)
        return 0
    finally:
        if close_session and session is not None:
            session.close()


def main():
    parser = argparse.ArgumentParser(description="Fetch and store official NBA injury reports.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print decision without downloading or writing to database",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    sys.exit(run_fetch_injuries(dry_run=args.dry_run))


if __name__ == "__main__":
    main()
