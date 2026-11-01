"""
Registration script for the injury-aware challenger model (elo_injury).

Auditable and idempotent script:
1. Refuses if an active elo_injury challenger is already registered (idempotent exit 0).
2. Refuses if LEARNING_MAX_CHALLENGERS would be exceeded.
3. Fits and evaluates walk-forward log loss gain using historical player game logs.
4. Refuses if the walk-forward gain is not positive with the lower bound of its 95% CI above -0.0005.
5. In live mode (no --dry-run), creates a NEW model_version row with role='challenger'.
   Rule 8: champion is never touched.

Usage:
    python backend/scripts/register_injury_challenger.py [--dry-run] [--force]
"""
import argparse
from datetime import date, datetime, timezone
import hashlib
from pathlib import Path
import sys
from typing import List, Optional

backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from sqlalchemy import select
from sqlmodel import Session

from app.config import settings
from app.models import MODEL_ROLE_CHALLENGER, ModelVersion
from app.services import model_registry
from app.services.elo_injury_model import (
    DEFAULT_MAX_SNAPSHOT_AGE_HOURS,
    DEFAULT_REPLACEMENT_RATE,
    DEFAULT_ROTATION_MIN_MPG,
    FAMILY_NAME,
    fit_walk_forward_injury_adjustment,
)


def main(argv: Optional[List[str]] = None, session_factory=None) -> int:
    parser = argparse.ArgumentParser(description="Register elo_injury model as a challenger.")
    parser.add_argument("--dry-run", action="store_true", help="Evaluate and print without committing changes")
    parser.add_argument("--force", action="store_true", help="Force registration ignoring statistical gate")
    parser.add_argument("--seasons", type=int, default=5, help="Number of walk-forward test seasons (default: 5)")
    parser.add_argument("--min-mpg", type=float, default=DEFAULT_ROTATION_MIN_MPG, help="Rotation min mpg")
    parser.add_argument("--bootstrap", type=int, default=2000, help="Bootstrap samples for CI")
    parser.add_argument("--seed", type=int, default=42, help="Seed for bootstrap")
    args = parser.parse_args(argv)

    if session_factory is None:
        from app.deps import get_db_context

        session_factory = get_db_context

    with session_factory() as session:
        # 1. Idempotency check: is an active elo_injury challenger already registered?
        existing = session.execute(
            select(ModelVersion).where(
                ModelVersion.name == FAMILY_NAME,
                ModelVersion.role == MODEL_ROLE_CHALLENGER,
            )
        ).scalar_one_or_none()

        if existing is not None:
            print(
                f"elo_injury challenger already registered: id={existing.id}, "
                f"version='{existing.version}', role='{existing.role}'. Idempotent exit 0."
            )
            return 0

        # 2. Check challenger capacity
        active_challengers = session.execute(
            select(ModelVersion).where(ModelVersion.role == MODEL_ROLE_CHALLENGER)
        ).scalars().all()
        max_challengers = settings.LEARNING_MAX_CHALLENGERS

        if len(active_challengers) >= max_challengers and not args.force:
            names = [f"{c.name} {c.version}" for c in active_challengers]
            print(
                f"Refusing registration: LEARNING_MAX_CHALLENGERS limit reached "
                f"({len(active_challengers)} active challengers >= {max_challengers}).\n"
                f"Active challengers: {names}"
            )
            return 1

        # 3. Walk-forward statistical evaluation
        print("Running walk-forward evaluation on historical seasons...")
        eval_result = fit_walk_forward_injury_adjustment(
            session=session,
            n_test_seasons=args.seasons,
            min_mpg=args.min_mpg,
            bootstrap_samples=args.bootstrap,
            seed=args.seed,
        )

        print(f"Walk-forward evaluation results (n_games={eval_result.n_games}):")
        print(
            f"  Fitted Beta:      {eval_result.overall_beta:.4f} "
            f"[95% CI: {eval_result.overall_beta_ci[0]:.4f} to {eval_result.overall_beta_ci[1]:.4f}]"
        )
        print(
            f"  Log Loss Gain:    {eval_result.log_loss_gain:+.5f} "
            f"[95% CI: {eval_result.log_loss_gain_ci[0]:+.5f} to {eval_result.log_loss_gain_ci[1]:+.5f}]"
        )
        print(
            f"  Brier Score Gain: {eval_result.brier_gain:+.5f} "
            f"[95% CI: {eval_result.brier_gain_ci[0]:+.5f} to {eval_result.brier_gain_ci[1]:+.5f}]"
        )
        print(f"  Residual Sigma:   {eval_result.sigma:.2f} points")
        print(f"  Caveat:           {eval_result.caveat}")

        # 4. Statistical gate check
        passes_gate = (eval_result.log_loss_gain > 0.0) and (eval_result.log_loss_gain_ci[0] > -0.0005)
        if not passes_gate and not args.force:
            print(
                f"Refusing registration: walk-forward log loss gain ({eval_result.log_loss_gain:+.5f}) "
                f"with 95% CI lower bound ({eval_result.log_loss_gain_ci[0]:+.5f}) did not pass the gate "
                f"(requires gain > 0 and CI lower > -0.0005)."
            )
            return 1

        # 5. Champion parent reference (champion is untouched)
        champion = model_registry.get_champion(session)
        parent_id = champion.id if champion is not None else None

        # Build candidate parameters
        today = date.today()
        raw_hash = f"{eval_result.overall_beta:.4f}_{eval_result.sigma:.2f}_{today}"
        version_hash = hashlib.sha256(raw_hash.encode()).hexdigest()[:6]
        version_str = f"lab-{today.strftime('%Y%m%d')}-{version_hash}"

        params = {
            "family": FAMILY_NAME,
            "beta": eval_result.overall_beta,
            "beta_ci": list(eval_result.overall_beta_ci),
            "sigma": eval_result.sigma,
            "rotation_min_mpg": args.min_mpg,
            "replacement_rate": DEFAULT_REPLACEMENT_RATE,
            "max_snapshot_age_hours": DEFAULT_MAX_SNAPSHOT_AGE_HOURS,
            "log_loss_gain": eval_result.log_loss_gain,
            "log_loss_gain_ci": list(eval_result.log_loss_gain_ci),
            "brier_gain": eval_result.brier_gain,
            "brier_gain_ci": list(eval_result.brier_gain_ci),
            "trained_through": str(today),
            "caveat": eval_result.caveat,
        }
        notes = (
            f"Injury-aware challenger model: Elo plus player availability adjustment "
            f"(beta={eval_result.overall_beta:.4f}, sigma={eval_result.sigma:.2f}, "
            f"walk-forward log loss gain {eval_result.log_loss_gain:+.5f}). Upper-bound caveat applies."
        )

        if args.dry_run:
            print(
                f"[DRY RUN] Would register new ModelVersion: name='{FAMILY_NAME}', "
                f"version='{version_str}', role='{MODEL_ROLE_CHALLENGER}', parent_id={parent_id}."
            )
            print(f"[DRY RUN] Params: {params}")
            return 0

        # Live registration (Rule 8: creates NEW model_version row, champion untouched)
        row = ModelVersion(
            name=FAMILY_NAME,
            version=version_str,
            params=params,
            role=MODEL_ROLE_CHALLENGER,
            parent_id=parent_id,
            notes=notes,
        )
        session.add(row)
        session.commit()
        print(f"Registered {FAMILY_NAME} challenger successfully: id={row.id}, version='{version_str}'")
        return 0


if __name__ == "__main__":
    sys.exit(main())
