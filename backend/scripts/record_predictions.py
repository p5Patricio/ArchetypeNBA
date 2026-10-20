"""
Records Elo predictions and paper bets for the games that tip off soon (see app/services/prediction_recorder.py).

    python scripts/record_predictions.py                       # games tipping off within the next 20 hours
    python scripts/record_predictions.py --dry-run             # compute and print, write nothing
    python scripts/record_predictions.py --horizon-hours 30 --max-quote-age-minutes 120
    python scripts/record_predictions.py --dry-run --now 2026-10-20T14:00:00-06:00   # replay a past moment

The run is idempotent (predictions and bets are never duplicated) and never places a bet at or after tip-off.
Apply the migrations (alembic upgrade head) and register the model (scripts/backfill_elo.py --evaluate
--register) before the first run. A naive --now is read as local time.

Exit codes: 0 ok (including "nothing to do"), 1 the recorder cannot run (for example, model not registered).
"""
import argparse
import sys
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import List, Optional

# Add backend directory to sys.path
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from app.services.prediction_recorder import (  # noqa: E402
    DEFAULT_HORIZON_HOURS,
    DEFAULT_MAX_QUOTE_AGE_MINUTES,
    PredictionRecorder,
    RecorderError,
    RecorderSummary,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Record Elo predictions and paper bets at decision time.")
    parser.add_argument("--dry-run", action="store_true", help="compute and print without writing to the database")
    parser.add_argument(
        "--horizon-hours",
        type=float,
        default=DEFAULT_HORIZON_HOURS,
        help="only games tipping off within this many hours (default: %(default)s)",
    )
    parser.add_argument(
        "--max-quote-age-minutes",
        type=float,
        default=DEFAULT_MAX_QUOTE_AGE_MINUTES,
        help="ignore quotes whose game was last captured longer ago than this (default: %(default)s)",
    )
    parser.add_argument("--now", default=None, help="ISO 8601 timestamp to run as (testing); default: the clock")
    return parser


def _pct(values: List[float]) -> str:
    return f"min {min(values):.1%}, median {median(values):.1%}, max {max(values):.1%}"


def format_summary(summary: RecorderSummary) -> str:
    verb = "would write" if summary.dry_run else "wrote"
    placed = ", ".join(f"{name}: {count}" for name, count in sorted(summary.bets_placed.items())) or "none"
    lines = [
        f"[{'dry-run' if summary.dry_run else 'record'}] as of {summary.now.isoformat()}",
        f"games in window: {summary.games_considered}; passed the rating guards: {summary.games_processed}",
        f"predictions {verb}: {summary.predictions_written} (already recorded: {summary.predictions_existing})",
        f"bets {'that would be placed' if summary.dry_run else 'placed'}: {placed}",
        f"candidate sides priced against the sharp line: {len(summary.candidates)}",
    ]
    eligible = [c for c in summary.candidates if c.eligible]
    if summary.candidates:
        lines.append(f"  eligible: {len(eligible)} ({len(eligible) / len(summary.candidates):.0%})")
    if eligible:
        lines.append(f"  raw edge of eligible: {_pct([c.raw_edge for c in eligible])}")
        lines.append(f"  EV of eligible: {_pct([c.ev for c in eligible])}")
    if len(summary.models) > 1:
        lines.append("models (only the champion bets):")
        for stats in summary.models.values():
            lines.append(
                f"  {stats.name} {stats.version:<8}{stats.role:<11} games {stats.games_predicted:>3}  "
                f"predictions {verb} {stats.predictions_written} (existing {stats.predictions_existing}), "
                f"missing ratings {stats.skipped_missing_ratings}"
            )
    if summary.skipped:
        lines.append("skip reasons:")
        lines.extend(f"  {reason:<28}{count:>5}" for reason, count in sorted(summary.skipped.items()))
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    now = datetime.fromisoformat(args.now).astimezone() if args.now else None

    from app.deps import get_db_context  # imported late so --help never builds a DB engine

    with get_db_context() as session:
        recorder = PredictionRecorder(
            session,
            now=now,
            horizon_hours=args.horizon_hours,
            max_quote_age_minutes=args.max_quote_age_minutes,
        )
        try:
            summary = recorder.run(dry_run=args.dry_run)
        except RecorderError as exc:
            print(f"[ERROR] {exc}")
            return 1
    print(format_summary(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
