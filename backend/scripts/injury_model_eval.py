"""
Injury model walk-forward evaluation script (read-only).

Runs walk-forward calibration on historical seasons using actual absences from ``player_game_log``.
Prints a formatted per-season and overall table comparing Elo alone against Elo + availability adjustment,
including bootstrap confidence intervals and the train/serve skew upper bound caveat.

Usage:
    python backend/scripts/injury_model_eval.py [--seasons 5] [--min-mpg 15.0] [--bootstrap 2000]
"""
import argparse
from pathlib import Path
import sys
from typing import List, Optional

backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.services.elo_injury_model import fit_walk_forward_injury_adjustment


def format_eval_report(res) -> str:
    lines = [
        "=" * 85,
        "  INJURY-AWARE CHALLENGER MODEL (elo_injury) - WALK-FORWARD EVALUATION",
        "=" * 85,
        "",
        f"{'Season':<12} {'Games':>6} {'Beta':>8} {'Elo LL':>9} {'Adj LL':>9} {'LL Gain':>9} {'Elo Br':>8} {'Adj Br':>8} {'Br Gain':>8}",
        "-" * 85,
    ]
    for s in res.season_results:
        lines.append(
            f"{s.season_label:<12} {s.n_games:>6} {s.beta:>8.4f} {s.elo_log_loss:>9.4f} "
            f"{s.adj_log_loss:>9.4f} {s.log_loss_gain:>+9.5f} {s.elo_brier:>8.4f} {s.adj_brier:>8.4f} {s.brier_gain:>+8.4f}"
        )
    lines.append("-" * 85)
    lines.append(
        f"{'POOLED / ALL':<12} {res.n_games:>6} {res.overall_beta:>8.4f} {'-':>9} {'-':>9} "
        f"{res.log_loss_gain:>+9.5f} {'-':>8} {'-':>8} {res.brier_gain:>+8.4f}"
    )
    lines.append("")
    lines.append("SUMMARY ESTIMATES & 95% BOOTSTRAP CONFIDENCE INTERVALS:")
    lines.append(
        f"  Overall Beta:       {res.overall_beta:.4f}  [95% CI: {res.overall_beta_ci[0]:.4f} to {res.overall_beta_ci[1]:.4f}]"
    )
    lines.append(
        f"  Log Loss Gain:      {res.log_loss_gain:+.5f}  [95% CI: {res.log_loss_gain_ci[0]:+.5f} to {res.log_loss_gain_ci[1]:+.5f}]"
    )
    lines.append(
        f"  Brier Score Gain:   {res.brier_gain:+.5f}  [95% CI: {res.brier_gain_ci[0]:+.5f} to {res.brier_gain_ci[1]:+.5f}]"
    )
    lines.append(f"  Residual Sigma:     {res.sigma:.2f} points")
    lines.append("")
    lines.append("CAVEAT (TRAIN / SERVE SKEW):")
    lines.append(f"  {res.caveat}")
    lines.append("=" * 85)
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None, session_factory=None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate elo_injury model on historical games (read-only).")
    parser.add_argument("--seasons", type=int, default=5, help="Number of walk-forward test seasons (default: 5)")
    parser.add_argument("--min-mpg", type=float, default=15.0, help="Rotation player minimum mpg (default: 15.0)")
    parser.add_argument("--bootstrap", type=int, default=2000, help="Bootstrap samples for CI (default: 2000)")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for bootstrap (default: 42)")
    args = parser.parse_args(argv)

    if session_factory is None:
        from app.deps import get_db_context

        session_factory = get_db_context

    with session_factory() as session:
        res = fit_walk_forward_injury_adjustment(
            session=session,
            n_test_seasons=args.seasons,
            min_mpg=args.min_mpg,
            bootstrap_samples=args.bootstrap,
            seed=args.seed,
        )
        print(format_eval_report(res))

    return 0


if __name__ == "__main__":
    sys.exit(main())
