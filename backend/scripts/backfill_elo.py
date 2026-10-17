"""
Builds, updates and evaluates the Elo ratings stored in team_elo_rating (derived from player_game_log).

    python scripts/backfill_elo.py                      # --rebuild: recompute everything (idempotent upsert)
    python scripts/backfill_elo.py --update             # rate only games without rows yet
    python scripts/backfill_elo.py --dry-run --evaluate # compute and print, write nothing
    python scripts/backfill_elo.py --evaluate --register

--evaluate prints the per-season walk-forward metrics; --register upserts the elo_538 model_version
(sigma and Brier over the last 5 completed seasons). --dry-run never writes to the database.
"""
import argparse
import sys
from pathlib import Path
from typing import List, Optional

# Add backend directory to sys.path
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from app.services.elo_service import (  # noqa: E402
    BackfillSummary,
    EloRatingService,
    OOS_SEASONS,
    SeasonMetrics,
    out_of_sample_summary,
)

TOP_N = 5


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Backfill, update and evaluate Elo ratings from player_game_log.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--rebuild", action="store_true", help="recompute every rating from scratch (default)")
    mode.add_argument("--update", action="store_true", help="rate only games without rating rows yet")
    parser.add_argument("--evaluate", action="store_true", help="print per-season walk-forward metrics")
    parser.add_argument("--register", action="store_true", help="upsert the elo_538 model_version row")
    parser.add_argument("--dry-run", action="store_true", help="compute and print without writing to the database")
    return parser


def format_metrics(metrics: List[SeasonMetrics]) -> str:
    lines = [
        f"{'season':<9}{'games':>7}{'brier':>8}{'logloss':>9}{'acc':>7}{'mae':>7}{'sigma':>7}{'bias':>7}",
    ]
    for m in metrics:
        lines.append(
            f"{m.season_label:<9}{m.n_games:>7}{m.brier:>8.4f}{m.log_loss:>9.4f}{m.accuracy:>7.3f}"
            f"{m.mae_margin:>7.2f}{m.residual_std:>7.2f}{m.mean_residual:>7.2f}"
        )
    return "\n".join(lines)


def format_summary(summary: BackfillSummary, service: EloRatingService, mode: str) -> str:
    verb = "would write" if summary.dry_run else "wrote"
    lines = [
        f"[{mode}] games used: {summary.games_used}; rating rows {verb}: {summary.rows_written}; "
        f"stale rows deleted: {summary.rows_deleted}"
    ]
    if summary.rebuilt:
        lines.append("[update] a new game predates the newest rated game: fell back to a full rebuild")
    report = summary.report
    if report is not None:
        lines.append(
            f"games seen: {report.games_seen}; skipped: {sum(report.unmapped_abbreviations.values())} non-NBA, "
            f"{report.skipped_not_two_teams} without two teams, {report.skipped_home_away} with ambiguous home/away"
        )
        if report.unmapped_abbreviations:
            unmapped = ", ".join(f"{abbr} ({n})" for abbr, n in sorted(report.unmapped_abbreviations.items()))
            lines.append(f"unmapped abbreviations (games skipped): {unmapped}")
    if summary.final_ratings:
        abbr = service.team_abbreviations()
        ranked = sorted(summary.final_ratings.items(), key=lambda item: item[1], reverse=True)
        fmt = lambda items: ", ".join(f"{abbr.get(team_id, team_id)} {rating:.0f}" for team_id, rating in items)
        lines.append(f"top {TOP_N}: {fmt(ranked[:TOP_N])}")
        lines.append(f"bottom {TOP_N}: {fmt(ranked[-TOP_N:])}")
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    mode = "update" if args.update else "rebuild"

    from app.deps import get_db_context  # imported late so --help never builds a DB engine

    with get_db_context() as session:
        service = EloRatingService(session)
        # --evaluate/--register alone should not rewrite ratings, but a plain run is the default rebuild.
        if args.update:
            summary = service.update_new_games(dry_run=args.dry_run)
        else:
            summary = service.rebuild_all(dry_run=args.dry_run)
        print(format_summary(summary, service, mode))

        if args.evaluate or args.register:
            metrics = service.evaluate_walk_forward()
            if args.evaluate:
                print(format_metrics(metrics))
            sigma, brier = out_of_sample_summary(metrics)
            print(f"out-of-sample (last {OOS_SEASONS} completed seasons): sigma={sigma:.3f} brier={brier:.4f}")
            if args.register:
                if args.dry_run:
                    print("[dry-run] model_version not written")
                else:
                    games = service.load_games()
                    row = service.register_model_version(
                        sigma,
                        brier,
                        trained_through=games[-1].game_date if games else None,
                        seasons_evaluated=[m.season_label for m in metrics],
                    )
                    print(f"model_version {row.name} {row.version} registered (id={row.id})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
