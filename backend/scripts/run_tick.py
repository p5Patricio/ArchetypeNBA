"""
Runs one tick: odds capture (opening once per local day, closing near tip-off) plus prediction recording.

    python scripts/run_tick.py [--dry-run] [--window-minutes 30] [--props-events 1] [--min-remaining 25]
                               [--skip opening closing record]

Scheduled by `NBA-Odds-Tick` (scripts/register_tick_task.ps1): it starts at user log on and repeats every
15 minutes. Each run is stateless and decides from DB markers (see app/services/tick.py), so repeated or
missed runs cost nothing. Output goes to stdout and to logs/tick.log (2 MB x 3 backups).
`--dry-run` prints what every step would do and its worst-case credits; it makes no network call, takes no
lock, writes no log file and issues no INSERT (it does read the database).

Exit codes: 0 no step failed (also when another tick holds the lock), 1 at least one step failed.
"""
import argparse
import logging
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Callable, ContextManager, List, Optional

# Add backend directory to sys.path
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from sqlmodel import Session

from app.services.odds_api_service import OddsApiService
from app.services.odds_snapshot import DEFAULT_MIN_REMAINING
from app.services.tick import (
    DEFAULT_STEPS,
    DEFAULT_TICK_PROPS_EVENTS,
    DEFAULT_TICK_WINDOW_MINUTES,
    default_steps,
    run_tick,
)

LOG_DIR = backend_dir.parent / "logs"
LOG_FILE = LOG_DIR / "tick.log"
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"

_installed_handlers: List[logging.Handler] = []


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run one capture + prediction-recording tick.")
    parser.add_argument("--dry-run", action="store_true", help="print what each step would do; no network, no DB writes")
    parser.add_argument(
        "--window-minutes",
        type=int,
        default=DEFAULT_TICK_WINDOW_MINUTES,
        help="closing: capture events tipping off within this many minutes (default: %(default)s)",
    )
    parser.add_argument(
        "--props-events",
        type=int,
        default=DEFAULT_TICK_PROPS_EVENTS,
        help="closing: events to fetch player props for, 1 credit each (default: %(default)s)",
    )
    parser.add_argument(
        "--min-remaining",
        type=int,
        default=DEFAULT_MIN_REMAINING,
        help="never spend credits if fewer than this many would remain afterwards (default: %(default)s)",
    )
    parser.add_argument(
        "--skip",
        nargs="*",
        default=[],
        choices=[name for name, _ in DEFAULT_STEPS],
        metavar="STEP",
        help=f"steps to skip ({', '.join(name for name, _ in DEFAULT_STEPS)})",
    )
    return parser


def configure_logging(log_file: Optional[Path]) -> None:
    """stdout always; the rotating file only when `log_file` is given. Replaces handlers from an earlier call."""
    root = logging.getLogger()
    for handler in _installed_handlers:
        root.removeHandler(handler)
        handler.close()
    _installed_handlers.clear()

    try:  # a cp1252 console must not crash the run on a non-ASCII player name
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError, OSError):
        pass
    handlers: List[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(RotatingFileHandler(log_file, maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8"))
    formatter = logging.Formatter(LOG_FORMAT)
    for handler in handlers:
        handler.setFormatter(formatter)
        root.addHandler(handler)
        _installed_handlers.append(handler)
    root.setLevel(logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)  # httpx INFO lines contain the apiKey query param


@contextmanager
def _database_session():
    from app.deps import get_db_context  # imported late so --help never builds a DB engine

    with get_db_context() as session:
        yield session


def main(
    argv: Optional[List[str]] = None,
    session_factory: Optional[Callable[[], ContextManager[Session]]] = None,
) -> int:
    args = build_parser().parse_args(argv)
    configure_logging(None if args.dry_run else LOG_FILE)
    log = logging.getLogger("run_tick")

    service = OddsApiService()
    if args.dry_run:
        service = None  # a dry run must never reach the network
    elif not service.is_configured:
        log.error("THE_ODDS_API_KEY is not configured (backend/.env); capture steps will fail, recording still runs.")

    try:
        with (session_factory or _database_session)() as session:
            summary = run_tick(
                session,
                service,
                datetime.now(timezone.utc),
                dry_run=args.dry_run,
                window_minutes=args.window_minutes,
                props_events=args.props_events,
                min_remaining=args.min_remaining,
                steps=default_steps(skip=args.skip),
            )
    except Exception:
        log.exception("tick aborted before any step could run (database unavailable?)")
        return 1

    log.info("\n%s", summary)
    return summary.exit_code


if __name__ == "__main__":
    sys.exit(main())
