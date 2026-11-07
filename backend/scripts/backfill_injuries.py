#!/usr/bin/env python3
"""
Historical backfill CLI for official NBA injury report PDFs (2018-12-17 onward).

Downloads at most --per-day reports per NBA game date (default 2: latest <= 5:00 PM ET
and latest <= 60 min before first tip-off when known, else 7:30 PM ET), trying both the
15-minute (HH_MMAM|PM.pdf) and 2018-2022 hourly (HHAM|PM.pdf) naming variants with
newest-first fallback within the hour. Enforces polite rate limits (default 4 s delay,
2 s minimum, --max-requests 300 cap), resumability, and leak-free report_timestamp storage.
"""

import argparse
from datetime import date, datetime
import logging
import sys
import time as time_module
from pathlib import Path
from typing import Callable, Optional, Sequence

# Add backend directory to sys.path
backend_dir = Path(__file__).resolve().parents[1]
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

import httpx
from sqlmodel import Session

from app.deps import engine
from app.services.injury_report_service import (
    ARCHIVE_START_DATE,
     BackfillSummary,
    DEFAULT_BACKFILL_DELAY_SECONDS,
    DEFAULT_MAX_REQUESTS,
    EASTERN_TZ,
    MIN_BACKFILL_DELAY_SECONDS,
    backfill_injury_reports,
)

logger = logging.getLogger("backfill_injuries")


def _parse_iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Invalid ISO date '{value}' (expected YYYY-MM-DD)") from exc


def format_summary(summary: BackfillSummary) -> str:
    """Formats a human-readable summary block for terminal and log output."""
    mode = "DRY-RUN" if summary.dry_run else "LIVE"
    lines = [
        f"=== Injury Report Backfill Summary ({mode}) ===",
        f"  Date window            : {summary.start_date.isoformat()} .. {summary.end_date.isoformat()}",
        f"  Game dates found       : {summary.game_dates_found}",
        f"  Slots skipped (stored) : {summary.skipped_existing}",
        f"  Slots planned          : {summary.slots_planned}",
        f"  Delay enforced         : {summary.effective_delay_seconds:.1f}s (min {MIN_BACKFILL_DELAY_SECONDS:.1f}s)",
        f"  Max requests cap       : {summary.max_requests}",
        f"  Requested              : {summary.requested}",
        f"  Stored                 : {summary.stored}",
        f"  Duplicates (sha256)    : {summary.duplicates}",
        f"  Missing (403/404)      : {summary.missing} (missing slots: {summary.missing_slots})",
        f"  Parse failures         : {summary.parse_failures}",
        f"  HTTP errors            : {summary.http_errors}",
        f"  Unmatched player names : {summary.unmatched_player_names}",
    ]
    if summary.cap_reached:
        lines.append("  Status                 : stopped at --max-requests cap (re-run to resume)")
    elif summary.interrupted:
        lines.append("  Status                 : interrupted by Ctrl-C (re-run to resume)")
    else:
        lines.append("  Status                 : completed")
    return "\n".join(lines)


def run_backfill_injuries(
    *,
    start_date: date = ARCHIVE_START_DATE,
    end_date: Optional[date] = None,
    per_day: int = 2,
    delay_seconds: float = DEFAULT_BACKFILL_DELAY_SECONDS,
    max_requests: int = DEFAULT_MAX_REQUESTS,
    dry_run: bool = False,
    session: Optional[Session] = None,
    http_client: Optional[httpx.Client] = None,
    pdf_text_extractor: Optional[Callable[[bytes], str]] = None,
    sleep_fn: Callable[[float], None] = time_module.sleep,
    now: Optional[datetime] = None,
) -> BackfillSummary:
    """
    Executes or previews the injury report backfill and prints the planned URLs (in dry-run)
    and summary.
    """
    close_session = False
    if session is None:
        session = Session(engine)
        close_session = True

    try:
        summary = backfill_injury_reports(
            session=session,
            start_date=start_date,
            end_date=end_date,
            per_day=per_day,
            delay_seconds=delay_seconds,
            max_requests=max_requests,
            dry_run=dry_run,
            http_client=http_client,
            pdf_text_extractor=pdf_text_extractor,
            sleep_fn=sleep_fn,
            now=now,
        )

        if dry_run:
            print(
                f"[dry-run] Window {summary.start_date.isoformat()}..{summary.end_date.isoformat()}: "
                f"{summary.game_dates_found} game date(s), "
                f"{summary.skipped_existing} existing slot(s) skipped, "
                f"{summary.slots_planned} slot(s) planned."
            )
            for idx, slot in enumerate(summary.planned_slots[: max(0, max_requests)], start=1):
                tip_label = "tip-60m" if slot.tipoff_known else "default"
                print(
                    f"[dry-run] {idx:03d}. {slot.game_date.isoformat()} "
                    f"<= {slot.cutoff_time_et.strftime('%H:%M')} ET ({tip_label}): "
                    f"{slot.primary_url} (+{len(slot.candidate_urls) - 1} fallback variants)"
                )

        summary_text = format_summary(summary)
        print(summary_text)
        logger.info("\n%s", summary_text)
        return summary
    finally:
        if close_session and session is not None:
            session.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Backfill official NBA injury report PDFs across historical game dates."
    )
    parser.add_argument(
        "--start",
        type=_parse_iso_date,
        default=ARCHIVE_START_DATE,
        help=f"Start date YYYY-MM-DD (default: {ARCHIVE_START_DATE.isoformat()}, when archive begins)",
    )
    parser.add_argument(
        "--end",
        type=_parse_iso_date,
        default=None,
        help="End date YYYY-MM-DD inclusive (default: today in Eastern Time)",
    )
    parser.add_argument(
        "--per-day",
        type=int,
        default=2,
        help="Max reports to download per game date (default: 2)",
    )
    parser.add_argument(
        "--delay",
        "--delay-seconds",
        dest="delay",
        type=float,
        default=DEFAULT_BACKFILL_DELAY_SECONDS,
        help=f"Delay in seconds between HTTP requests (default: {DEFAULT_BACKFILL_DELAY_SECONDS:.0f}s, min {MIN_BACKFILL_DELAY_SECONDS:.0f}s)",
    )
    parser.add_argument(
        "--max-requests",
        type=int,
        default=DEFAULT_MAX_REQUESTS,
        help=f"Hard cap on HTTP requests per run (default: {DEFAULT_MAX_REQUESTS})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List planned URLs with zero network requests and zero database writes",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    end_date = args.end or datetime.now(EASTERN_TZ).date()
    if end_date < args.start:
        parser.error(f"--end ({end_date.isoformat()}) must not be earlier than --start ({args.start.isoformat()})")

    run_backfill_injuries(
        start_date=args.start,
        end_date=end_date,
        per_day=args.per_day,
        delay_seconds=args.delay,
        max_requests=args.max_requests,
        dry_run=args.dry_run,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
