"""
Imports free historical NBA game lines (SBRO archive pages, Kaggle CC0 CSV) into ``historical_game_line``.

    python scripts/import_historical_lines.py --dry-run          # parse + reconcile, read-only, prints the report
    python scripts/import_historical_lines.py                    # upsert (idempotent), then commit

Raw files are read from ``~/ArchetypeNBA-data/raw/`` (``ARCHETYPE_DATA_DIR`` overrides the base directory):
``sbro/nba-odds-YYYY-YY.html`` and ``kaggle_cviaxmiwnptr/nba_2008-2026.csv``. They are parsed as data only, never
executed. The reconciliation report counts rows per season, unmatched teams, lines not matched to a
``player_game_log`` game, final scores that disagree with the box score, and cross-source disagreements.
Requires migration ``e9b1d3f5a7c2`` for a real (non dry-run) import.
"""
import argparse
import sys
from pathlib import Path
from typing import List, Optional

backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from app.services import historical_lines as service  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    base = service.default_data_dir() / "raw"
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--sbro-dir", type=Path, default=base / "sbro")
    parser.add_argument("--kaggle-csv", type=Path, default=base / "kaggle_cviaxmiwnptr" / "nba_2008-2026.csv")
    parser.add_argument("--dry-run", action="store_true", help="parse and reconcile only; no database write")
    return parser


def main(argv: Optional[List[str]] = None, session_factory=None) -> int:
    args = build_parser().parse_args(argv)
    lines, reports = service.read_sources(args.sbro_dir, args.kaggle_csv)
    if not lines:
        print(f"No input found (looked at {args.sbro_dir} and {args.kaggle_csv}).")
        return 1
    if session_factory is None:
        from app.deps import get_db_context

        session_factory = get_db_context
    with session_factory() as session:
        report = service.import_lines(session, lines, reports, dry_run=args.dry_run)
        if args.dry_run:
            session.rollback()
        else:
            session.commit()
    print(report.format())
    return 0


if __name__ == "__main__":
    sys.exit(main())
