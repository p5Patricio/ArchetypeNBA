"""
Register the ``line_move`` live test (D-71): a ``model_version`` row (role ``shadow``) whose params are the line-move
ridges refit for the live season. PAPER ONLY.

    python scripts/register_line_move.py --dry-run          # fit and print, write nothing (read-only transaction)
    python scripts/register_line_move.py                    # fit and register line_move 1
    python scripts/register_line_move.py --version 2 --spread-threshold 0.5

The fit is exactly what the leak-safe walk-forward evaluation (``scripts/line_movement_report.py``) uses to predict
the season: margin_features refit on every past season, both ridges trained on every past season with an opening
line (SBRO archive) plus the OddsPapi Pinnacle games of earlier seasons, whose target is close - entry at the
bettable instant and whose features are computed as of that instant. Games of the live season never enter the fit.
An existing (name, version) is never overwritten: a new parameter set is a new version (rule 8).
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))


def build_parser() -> argparse.ArgumentParser:
    from app.services.historical_lines import default_data_dir

    base = default_data_dir()
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dry-run", action="store_true", help="fit and print only; read-only transaction")
    parser.add_argument("--version", default="1")
    parser.add_argument("--season", default=None, help="live season label (default: the season of today)")
    parser.add_argument("--spread-threshold", type=float, default=0.25)
    parser.add_argument("--total-threshold", type=float, default=0.5)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--sbro-dir", type=Path, default=base / "raw" / "sbro")
    parser.add_argument("--kaggle-csv", type=Path, default=base / "raw" / "kaggle_cviaxmiwnptr" / "nba_2008-2026.csv")
    return parser


def fit_params(session, args, season: str) -> dict:
    from app.services import line_movement as lm
    from app.services import line_move_strategy as lms
    from scripts.line_movement_report import leak_safe_inputs, load_archive, model_predictions

    archive = load_archive(session, args)
    if archive is None:
        raise SystemExit(f"no archive lines found ({args.sbro_dir}, {args.kaggle_csv})")
    paths = lm.load_pinnacle_paths(session)
    entries, overrides, stats, refused, _ = leak_safe_inputs(session, paths, archive[1], lm.ENTRY_FIRST_AFTER)
    args.n_boot = 1  # no bootstrap needed for a fit
    model = model_predictions(session, entries, args, archive=archive, overrides=overrides, export_season=season)
    exports = model[3].exports
    labels = {g.game_id: g for g in archive[1]}
    season_of = archive[2]
    before = sum(1 for p in entries if p.nba_game_id in labels and season_of[labels[p.nba_game_id].season_id] < season)
    training = {
        "fitted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "live_season": season,
        "spread_train_seasons": exports.get("spreads_train_seasons"),
        "total_train_seasons": exports.get("totals_train_seasons"),
        "spread_train_games": getattr(exports.get("spreads"), "n", None),
        "total_train_games": getattr(exports.get("totals"), "n", None),
        "oddspapi_entry_games_before_season": before,
        "entry_refused": len(refused),
        "seed": args.seed,
        "source": "SBRO opens + OddsPapi Pinnacle entries at the bettable instant (D-71)",
    }
    return lms.build_params(
        exports, {"spreads": args.spread_threshold, "totals": args.total_threshold}, training
    )


def main(argv: Optional[List[str]] = None, session_factory=None, fit=None) -> int:
    args = build_parser().parse_args(argv)
    if session_factory is None:
        from app.deps import get_db_context

        session_factory = get_db_context
    from app.models import MODEL_ROLE_SHADOW, ModelVersion
    from app.services import line_move_strategy as lms
    from app.services.historical_lines import set_read_only
    from app.services.odds_ingestion import OddsIngestionService
    from sqlalchemy import select

    season = args.season or OddsIngestionService.season_label_for(datetime.now(timezone.utc).date())
    with session_factory() as session:
        if args.dry_run:
            set_read_only(session)
        existing = session.execute(
            select(ModelVersion).where(ModelVersion.name == lms.FAMILY_NAME, ModelVersion.version == args.version)
        ).scalar_one_or_none()
        if existing is not None:
            print(f"{lms.FAMILY_NAME} {args.version} already exists (id {existing.id}, role {existing.role}); "
                  "register a new --version instead (rule 8).")
            session.rollback()
            return 1
        params = (fit or fit_params)(session, args, season)
        spreads, totals = params["spreads"], params["totals"]
        print(f"{lms.FAMILY_NAME} {args.version} (role {MODEL_ROLE_SHADOW}) for season {season}"
              f"{' [DRY RUN: nothing written]' if args.dry_run else ''}")
        print(f"  thresholds {params['thresholds']}; sigma spread {params['sigma_spread']:.2f}, total "
              f"{params['sigma_total']:.2f}")
        for name, fit_ in (("spreads", spreads), ("totals", totals)):
            features = params["spread_features" if name == "spreads" else "total_features"]
            coefs = ", ".join(f"{f} {c:+.3f}" for f, c in zip(features, fit_["coef"]))
            print(f"  {name}: n {fit_['n']}, alpha {fit_['alpha']:g}, intercept {fit_['intercept']:+.3f}; "
                  f"standardized coefficients: {coefs}")
        print("  training: " + json.dumps(params["training"], sort_keys=True))
        if args.dry_run:
            session.rollback()
            return 0
        row = ModelVersion(
            name=lms.FAMILY_NAME, version=args.version, params=params, role=MODEL_ROLE_SHADOW,
            notes="Line-move live test (D-71): paper bets at the bettable instant, judged by Pinnacle CLV and ROI",
        )
        session.add(row)
        session.commit()
        print(f"  registered: model_version id {row.id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
