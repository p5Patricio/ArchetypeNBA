"""
Prints the paper-trading report: strategy performance, CLV coverage, model skill against the de-vigged close
and the bankroll of each strategy. Read-only.

    python scripts/paper_report.py

Numbers that cannot be computed yet (no settled bets, no closing captures) are reported as n/a.
"""
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

# Add backend directory to sys.path
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from app.services.paper_report import build_report, format_report


def main(argv: Optional[List[str]] = None, session_factory=None) -> int:
    if session_factory is None:
        from app.deps import get_db_context  # imported late so --help never builds a DB engine

        session_factory = get_db_context
    try:
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError, OSError):
        pass
    with session_factory() as session:
        print(format_report(build_report(session, datetime.now(timezone.utc))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
