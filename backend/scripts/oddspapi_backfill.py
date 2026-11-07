"""
OddsPapi backfill: missed Pinnacle closes and open-to-close price paths of finished NBA games (D-70).

    python scripts/oddspapi_backfill.py --dry-run              # ZERO network: the plan, the budget, the coverage
    python scripts/oddspapi_backfill.py --max-requests 60      # one run, at most 60 requests (billable + free)
    python scripts/oddspapi_backfill.py --no-backfill          # skip priority 3 (Jan-Jun 2026)
    python scripts/oddspapi_backfill.py --report               # coverage only (no network)

Priorities: 1 final games without a ``closing`` capture, 2 final current-season games without a path (newest first),
3 Jan-Jun 2026 fixtures (leftover budget). Listings are billed and limited by ``ODDSPAPI_MONTHLY_BUDGET`` (counted
in ``oddspapi_request`` per UTC month); historical paths are free but 5 s apart. Needs ``ODDSPAPI_API_KEY`` for a
real run (``ODDSPAPI_ENABLED`` gates only the tick step). Raw payloads are cached gzipped under
``~/ArchetypeNBA-data/raw/oddspapi/paths`` (outside git).
"""
import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from app.config import settings  # noqa: E402
from app.services import oddspapi as service  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dry-run", action="store_true", help="print the plan and the budget; no network, no writes")
    parser.add_argument("--report", action="store_true", help="print the coverage only; no network, no writes")
    parser.add_argument("--max-requests", type=int, default=60,
                        help="hard cap on requests in this run, billable or free (default: %(default)s)")
    parser.add_argument("--max-paths", type=int, default=None,
                        help="historical paths to fetch (default: max-requests minus the planned listings and 1)")
    parser.add_argument("--no-backfill", action="store_true", help="leave out priority 3 (Jan-Jun 2026 fixtures)")
    parser.add_argument("--bookmakers", default=None,
                        help=f"comma-separated slugs, at most 3 (default ODDSPAPI_BOOKMAKERS={settings.ODDSPAPI_BOOKMAKERS})")
    parser.add_argument("--no-raw-cache", action="store_true", help="do not keep the gzipped raw payloads")
    return parser


def main(argv: Optional[List[str]] = None, session_factory=None, client_factory=None, now: Optional[datetime] = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    now = now or datetime.now(timezone.utc)
    books = [b.strip() for b in (args.bookmakers or settings.ODDSPAPI_BOOKMAKERS).split(",") if b.strip()]
    if not 1 <= len(books) <= 3:
        print("--bookmakers takes 1 to 3 slugs")
        return 2
    if session_factory is None:
        from app.deps import get_db_context

        session_factory = get_db_context

    with session_factory() as session:
        if args.dry_run or args.report:
            from app.services.historical_lines import set_read_only

            set_read_only(session)
            if args.dry_run:
                max_paths = args.max_paths if args.max_paths is not None else max(0, args.max_requests - 3)
                plan = service.plan_run(
                    session, now, max_paths=max_paths, monthly_budget=settings.ODDSPAPI_MONTHLY_BUDGET,
                    include_backfill=not args.no_backfill,
                )
                print("Dry run: no network, no writes.")
                print(service.format_plan(plan))
                print(f"  this run would send at most {1 + plan.billable_planned + len(plan.paths)} request(s) "
                      f"(1 free /v4/account, {plan.billable_planned} billable listing(s), {len(plan.paths)} free path(s)); "
                      f"bookmakers {','.join(books)}")
            print(service.format_coverage(service.coverage(session, now)))
            session.rollback()
            return 0

        if client_factory is None:
            from app.services.oddspapi_client import DbRequestLedger, OddsPapiClient

            def client_factory(sess):
                return OddsPapiClient(DbRequestLedger(sess), source="cli", max_requests=args.max_requests)

        client = client_factory(session)
        if not client.is_configured:
            print("ODDSPAPI_API_KEY is not configured (repo-root .env or backend/.env); nothing done.")
            return 1
        max_paths = args.max_paths if args.max_paths is not None else max(0, args.max_requests - 3)
        summary = service.run_oddspapi(
            session, client, now, max_paths=max_paths, bookmakers=books, include_backfill=not args.no_backfill,
            min_remaining=settings.ODDSPAPI_MIN_REMAINING,
            raw_dir=None if args.no_raw_cache else service.default_raw_dir(),
        )
        print(service.format_run(summary))
        print(service.format_coverage(service.coverage(session, now)))
        return 0 if summary.status in ("ok", "budget", "quota") else 1


if __name__ == "__main__":
    sys.exit(main())
