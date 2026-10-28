"""
Market audit script (read-only):
  (a) Closing-total error on settled games: n, mean, sd of (final total - closing line).
  (b) Typical vig of stored player-prop closing quotes (over/under pairs).

Degrades gracefully to "no data" messages when tables/quotes are empty.

Usage:
    python backend/scripts/market_audit.py
"""
from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import List, Optional

# Add backend directory to sys.path
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from app.services.market_audit import format_market_audit, run_market_audit


def main(argv: Optional[List[str]] = None, session_factory=None) -> int:
    if session_factory is None:
        from app.deps import get_db_context  # late import so --help does not build engine

        session_factory = get_db_context

    try:
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError, OSError):
        pass

    with session_factory() as session:
        result = run_market_audit(session)
        print(format_market_audit(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
