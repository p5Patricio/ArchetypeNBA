"""
Historical candidate lab: searches Elo hyperparameters and trains margin_features on the past, selects on one
window of seasons, reports on the two latest (hold-out) seasons and says which candidates may become challengers.

    python scripts/model_lab.py --seed 42                     # read-only report
    python scripts/model_lab.py --json lab.json               # also write the numbers as JSON
    python scripts/model_lab.py --register --dry-run          # show what --register would insert
    python scripts/model_lab.py --register --confirm-database nba_platform

The default run only reads the database. --register inserts the gate-passing candidates as challengers (and runs
the initial rating backfill of the Elo ones); on PostgreSQL it also needs --confirm-database with the database name.
--max-seconds ends the search gracefully and marks the report as partial.
"""
import argparse
import json
import sys
import time
from pathlib import Path
from typing import List, Optional

# Add backend directory to sys.path
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from app.services.model_lab import (  # noqa: E402
    DEFAULT_CONFIGS,
    CandidateResult,
    LabError,
    LabReport,
    Metrics,
    PairedDelta,
    RegistrationRefused,
    RegistrationResult,
    champion_elo_params,
    load_lab_data,
    register_candidates,
    run_lab,
)
from app.services import model_registry  # noqa: E402

DEFAULT_MAX_SECONDS = 240.0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Historical candidate lab for the model learning loop.")
    parser.add_argument("--seed", type=int, default=42, help="seed of the Elo search, the training and the bootstrap")
    parser.add_argument("--configs", type=int, default=DEFAULT_CONFIGS, help="Elo configurations to search")
    parser.add_argument("--max-seconds", type=float, default=DEFAULT_MAX_SECONDS, help="time budget; the report is partial beyond it")
    parser.add_argument("--json", dest="json_path", default=None, help="write the full report as JSON to this file")
    parser.add_argument("--register", action="store_true", help="insert the gate-passing candidates as challengers")
    parser.add_argument("--dry-run", action="store_true", help="with --register: print what would be registered, write nothing")
    parser.add_argument("--confirm-database", default=None, help="database name to confirm a --register on PostgreSQL")
    return parser


def _delta(delta: Optional[PairedDelta]) -> str:
    if delta is None:
        return "n/a"
    return f"{delta.mean:+.4f} [{delta.ci_low:+.4f}, {delta.ci_high:+.4f}]"


def _metrics_row(label: str, m: Metrics, delta: Optional[PairedDelta]) -> str:
    return (
        f"{label:<30}{m.n:>6}{m.log_loss:>9.4f}{m.brier:>8.4f}{m.accuracy:>7.3f}{m.mae_margin:>7.2f}"
        f"{m.margin_nll:>8.3f}{m.calibration_slope:>7.2f}{m.calibration_intercept:>+7.2f}   {_delta(delta)}"
    )


_HEADER = f"{'':<30}{'games':>6}{'logloss':>9}{'brier':>8}{'acc':>7}{'mae':>7}{'nll':>8}{'slope':>7}{'icpt':>7}   gain vs champion [95% CI]"


def _params_text(params: dict) -> str:
    return f"K={params['K']:.1f} HA={params['home_advantage']:.0f} carry={params['carryover']:.3f} mov={params['mov_exponent']:.3f}"


def format_report(report: LabReport) -> str:
    lines = [
        f"Model lab: seed {report.seed}, {report.n_games} games, "
        f"{report.configs_evaluated}/{report.configs_requested} Elo configurations evaluated"
        + (" (PARTIAL)" if report.partial else ""),
        f"selection window: {report.split['selection'][0]} .. {report.split['selection'][-1]} ({len(report.split['selection'])} seasons)",
        f"hold-out seasons: {', '.join(report.split['holdout'])}",
        f"champion: elo_538 {_params_text(report.champion_params)}",
        "",
        "Selection window - top Elo configurations (pooled walk-forward)",
        _HEADER,
        _metrics_row("champion", report.champion_selection, None),
    ]
    for rank, result in enumerate(report.elo_top, 1):
        lines.append(_metrics_row(f"#{rank}", result.selection, result.selection_gain) + f"   {_params_text(result.params)}")
    margin = next((c for c in report.candidates if c.kind != model_registry.ELO_FAMILY_NAME and c.selection), None)
    if margin is not None:
        lines.append(_metrics_row("margin_features (wf)", margin.selection, margin.selection_gain))

    lines += ["", "Hold-out (never used for selection)", _HEADER, _metrics_row("champion", report.champion_holdout, None)]
    for candidate in report.candidates:
        lines.append(_metrics_row(candidate.label, candidate.holdout, candidate.holdout_gain))
    lines += ["", "Verdicts"]
    for candidate in report.candidates:
        lines.append(_verdict(candidate))
    if report.notes:
        lines += ["", *[f"note: {note}" for note in report.notes]]
    lines.append(f"\nruntime: {report.elapsed_seconds:.1f}s")
    return "\n".join(lines)


def _verdict(candidate: CandidateResult) -> str:
    gate = candidate.gate
    if gate.passed:
        return f"  {candidate.label}: PASSES the historical gate (hold-out log loss gain {gate.gain:+.4f}, differs from active models)"
    return f"  {candidate.label}: rejected - " + "; ".join(gate.reasons)


def format_registration(result: RegistrationResult) -> str:
    verb = "would register" if result.dry_run else "registered"
    lines = ["", f"Registration ({'dry run' if result.dry_run else 'live'})"]
    shown = result.planned if result.dry_run else result.registered
    for item in shown:
        name, version = (item.name, item.version)
        lines.append(f"  {verb}: {name} {version} as challenger")
    for row_id, rows in result.backfilled_rows.items():
        lines.append(f"  model {row_id}: {rows} rating rows backfilled")
    lines += [f"  skipped: {reason}" for reason in result.skipped]
    if not shown and not result.skipped:
        lines.append("  nothing to register")
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None, session_factory=None) -> int:
    args = build_parser().parse_args(argv)
    if args.dry_run and not args.register:
        print("--dry-run only matters with --register; the default run never writes", file=sys.stderr)
    if session_factory is None:
        from app.deps import get_db_context  # imported late so --help never builds a DB engine

        session_factory = get_db_context
    try:
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError, OSError):
        pass

    started = time.monotonic()
    with session_factory() as session:
        try:
            _, champion_params = champion_elo_params(session)
            report = run_lab(
                load_lab_data(session),
                champion_params,
                model_registry.list_active(session),
                seed=args.seed,
                n_configs=args.configs,
                deadline=started + args.max_seconds,
            )
        except LabError as exc:
            print(f"model lab cannot run: {exc}", file=sys.stderr)
            return 1
        print(format_report(report))
        if args.json_path:
            Path(args.json_path).write_text(json.dumps(report.to_dict(), indent=2, default=str), encoding="utf-8")
            print(f"\nreport written to {args.json_path}")
        if args.register:
            try:
                result = register_candidates(
                    session, report, dry_run=args.dry_run, confirm_database=args.confirm_database
                )
            except RegistrationRefused as exc:
                print(f"\nnot registering: {exc}", file=sys.stderr)
                return 2
            print(format_registration(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
