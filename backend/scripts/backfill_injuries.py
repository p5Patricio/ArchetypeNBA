#!/usr/bin/env python3
"""
Historical backfill CLI for official NBA injury report PDFs (2018-12-17 onward).

Downloads at most --per-day reports per NBA game date (default 2: the report labelled
5:00 PM ET, and the latest report published at or before the first tip-off - 60 min, the
tip-off read from the stored 5 PM report when the database has no tip time). Exact file
names come from the official season index pages when they list the date (one request per
season); otherwise the file name of the date's naming era is guessed (hourly ``_05PM.pdf``
through 2025-12-21, quarter-hour ``_05_00PM.pdf`` from 2025-12-22) with at most 3 guesses.
Enforces polite rate limits (default 4 s delay, 2 s minimum, --max-requests 300 cap),
resumability, and stores the publication time printed in the PDF title.

Every attempted slot is recorded in the ``injury_backfill_slot`` ledger (stored / missing /
parse_failed / http_error). Later runs skip slots whose outcome is missing or parse_failed;
``--retry-failed`` re-plans parse failures (fresh download, re-parse, e.g. after a parser fix),
``--retry-missing`` re-plans missing slots, ``--reparse-failed-only`` plans nothing but the parse
failures. HTTP errors are retried automatically. The summary ends with the cumulative coverage
per season from the ledger.
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
        f"  Slots skipped (ledger) : {summary.skipped_missing} missing, {summary.skipped_parse_failed} parse-failed"
        " (--retry-missing / --retry-failed re-plan them)",
        f"  Slots planned          : {summary.slots_planned}"
        f" (retrying: {summary.retried_failed} parse-failed, {summary.retried_missing} missing,"
        f" {summary.retried_http_error} http-error)",
        f"  Delay enforced         : {summary.effective_delay_seconds:.1f}s (min {MIN_BACKFILL_DELAY_SECONDS:.1f}s)",
        f"  Max requests cap       : {summary.max_requests}",
        f"  Requested              : {summary.requested}",
        f"  Stored                 : {summary.stored}",
        f"  Duplicates (sha256)    : {summary.duplicates}",
        f"  Missing (403/404)      : {summary.missing} (missing slots: {summary.missing_slots})",
        f"  Parse failures         : {summary.parse_failures}",
        f"  HTTP errors            : {summary.http_errors}",
        f"  Entries stored         : {summary.entries_stored}",
        f"  Unmatched player names : {summary.unmatched_player_names}",
        f"  Slots reused (stored)  : {summary.reused_slots}",
        f"  Index pages requested  : {summary.index_pages_requested}"
        + (f" (unavailable: {', '.join(summary.index_seasons_unavailable)})" if summary.index_seasons_unavailable else ""),
    ]
    if summary.dry_run:
        lo, hi = summary.estimated_requests_min, summary.estimated_requests
        delay = summary.effective_delay_seconds
        cap = max(1, summary.max_requests)
        lines.append(
            f"  Estimated requests     : ~{lo}..{hi} (low: hourly-era pre-tip slots reuse the 5 PM file; "
            f"high: one per planned slot; index pages included; 403/404 fallbacks add more)"
        )
        lines.append(
            f"  Estimated duration     : ~{lo * delay / 60.0:.0f}..{hi * delay / 60.0:.0f} min at {delay:.1f}s spacing, "
            f"{-(-lo // cap)}..{-(-hi // cap)} run(s) of --max-requests {summary.max_requests}"
        )
    if summary.coverage:
        lines.append("  Coverage by season (cumulative, ledger + stored snapshots):")
        lines.append(f"    {'season':<8} {'stored':>7} {'missing':>8} {'failed':>7} {'remaining':>10} {'total':>7}")
        totals = [0, 0, 0, 0, 0]
        for label in sorted(summary.coverage):
            c = summary.coverage[label]
            values = [c.stored, c.missing, c.failed, c.remaining, c.total]
            totals = [a + b for a, b in zip(totals, values)]
            lines.append(f"    {label:<8} {values[0]:>7} {values[1]:>8} {values[2]:>7} {values[3]:>10} {values[4]:>7}")
        lines.append(f"    {'all':<8} {totals[0]:>7} {totals[1]:>8} {totals[2]:>7} {totals[3]:>10} {totals[4]:>7}")
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
    use_index_pages: bool = True,
    retry_failed: bool = False,
    retry_missing: bool = False,
    reparse_failed_only: bool = False,
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
            use_index_pages=use_index_pages,
            retry_failed=retry_failed,
            retry_missing=retry_missing,
            reparse_failed_only=reparse_failed_only,
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
                if slot.kind == "pre_tip":
                    tip_label = "pre-tip, tip known" if slot.tipoff_known else "pre-tip, re-planned from the 5 PM report"
                else:
                    tip_label = slot.kind
                print(
                    f"[dry-run] {idx:03d}. {slot.game_date.isoformat()} "
                    f"<= {slot.cutoff_time_et.strftime('%H:%M')} ET ({tip_label}): "
                    f"{slot.primary_url} (+{max(0, len(slot.candidate_urls) - 1)} fallback guesses)"
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
        "--no-index-pages",
        action="store_true",
        help="Do not read the official season index pages; guess file names for every date",
    )
    parser.add_argument(
        "--retry-failed",
        action="store_true",
        help="Re-plan slots whose last outcome was parse_failed (fresh download and re-parse, e.g. after a parser fix)",
    )
    parser.add_argument(
        "--retry-missing",
        action="store_true",
        help="Re-plan slots whose candidate files all returned 403/404 last time",
    )
    parser.add_argument(
        "--reparse-failed-only",
        action="store_true",
        help="Plan ONLY slots whose last outcome was parse_failed (implies --retry-failed)",
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
        use_index_pages=not args.no_index_pages,
        retry_failed=args.retry_failed,
        retry_missing=args.retry_missing,
        reparse_failed_only=args.reparse_failed_only,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
