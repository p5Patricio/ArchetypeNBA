"""
Captures an opening or closing odds snapshot into odds_history (The Odds API free tier).

    python scripts/capture_odds_snapshot.py --phase opening [--dry-run]
    python scripts/capture_odds_snapshot.py --phase closing [--props-events 3] [--window-minutes 45]

Credit budget (500/month) and the cost model are documented in app/services/odds_snapshot.py:
opening = 3 credits/day, closing = 3 credits per tip-off cluster + 1 per prop market per event.
`--dry-run` prints the planned calls and their cost without touching the network or the DB.

Exit codes: 0 ok (including "nothing due"), 1 configuration error, 2 aborted by the credit guard.
"""
import argparse
import logging
import sys
from pathlib import Path
from typing import List, Optional

# Add backend directory to sys.path
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from app.services.odds_api_service import DEFAULT_BOOKMAKERS, OddsApiService
from app.services.odds_snapshot import (
    DEFAULT_MIN_REMAINING,
    DEFAULT_PROPS_EVENTS,
    DEFAULT_PROPS_MARKETS,
    DEFAULT_WINDOW_MINUTES,
    PHASES,
    format_plan,
    format_summary,
    plan_snapshot,
    run_snapshot,
    valid_prop_markets,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Capture an opening/closing odds snapshot into odds_history.")
    parser.add_argument("--phase", required=True, choices=PHASES)
    parser.add_argument(
        "--props-events",
        type=int,
        default=None,
        help=f"events to fetch player props for (default: {DEFAULT_PROPS_EVENTS['opening']} opening, "
        f"{DEFAULT_PROPS_EVENTS['closing']} closing)",
    )
    parser.add_argument(
        "--props-markets",
        default=",".join(DEFAULT_PROPS_MARKETS),
        help="comma-separated prop markets, 1 credit each per event (default: player_points)",
    )
    parser.add_argument(
        "--min-remaining",
        type=int,
        default=DEFAULT_MIN_REMAINING,
        help="never spend credits if fewer than this many would remain afterwards (default: 25)",
    )
    parser.add_argument(
        "--window-minutes",
        type=int,
        default=DEFAULT_WINDOW_MINUTES,
        help="closing phase: capture events tipping off within this many minutes (default: 45)",
    )
    parser.add_argument(
        "--bookmakers",
        default=",".join(DEFAULT_BOOKMAKERS),
        help="comma-separated bookmaker keys, at most 10 (default: %(default)s)",
    )
    parser.add_argument("--dry-run", action="store_true", help="print the planned calls and cost; no network, no DB")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    try:
        props_markets = valid_prop_markets([m.strip() for m in args.props_markets.split(",") if m.strip()])
    except ValueError as exc:
        print(f"[ERROR] {exc}")
        return 1
    props_events = DEFAULT_PROPS_EVENTS[args.phase] if args.props_events is None else args.props_events
    bookmakers = [b.strip() for b in args.bookmakers.split(",") if b.strip()]

    if args.dry_run:
        plan = plan_snapshot(args.phase, props_events, props_markets, bookmakers, args.window_minutes)
        print(format_plan(plan, args.min_remaining))
        return 0

    service = OddsApiService()
    if not service.is_configured:
        print("[ERROR] THE_ODDS_API_KEY is not configured (backend/.env).")
        return 1

    from app.deps import get_db_context  # imported late so --dry-run never builds a DB engine

    with get_db_context() as session:
        summary = run_snapshot(
            session,
            service,
            phase=args.phase,
            props_events=props_events,
            props_markets=props_markets,
            min_remaining=args.min_remaining,
            window_minutes=args.window_minutes,
            bookmakers=bookmakers,
        )
    print(format_summary(summary))
    return 2 if summary.status == "aborted_low_credits" else 0


if __name__ == "__main__":
    sys.exit(main())
