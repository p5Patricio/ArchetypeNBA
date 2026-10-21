"""
The model league: who is champion, how the challengers are doing, and the controls to change that.

    python scripts/model_league.py status
    python scripts/model_league.py evaluate                  # dry run: evaluates, writes nothing (the default)
    python scripts/model_league.py evaluate --apply          # writes audit rows and applies the decisions
    python scripts/model_league.py propose [--dry-run]       # run the historical lab and register challengers
    python scripts/model_league.py promote 3 --reason "..." [--force]
    python scripts/model_league.py retire 3 --reason "..."

`status` and `evaluate` (without --apply) only read the database. Everything that writes (evaluate --apply,
propose without --dry-run, promote, retire) needs --confirm-database <name> on anything but SQLite, like the
lab. promote/retire are MANUAL overrides: they skip the statistical gate but never the invariants (one champion,
atomic swap) and always write an audit row whose reason starts with "manual:". `evaluate --apply` also respects
LEARNING_AUTOPROMOTE (off = decisions are recorded as dry_run and nothing changes).

Exit codes: 0 ok, 1 error, 2 refused (guard or invariant).
"""
import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

# Add backend directory to sys.path
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from app.services import model_promotion  # noqa: E402
from app.services.model_lab import DEFAULT_CONFIGS, LabError, RegistrationRefused, check_registration_target  # noqa: E402

DEFAULT_MAX_SECONDS = 240.0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Model league: status, evaluation, proposals and manual overrides.")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--confirm-database", default=None, help="database name, required to write on anything but SQLite")
    common.add_argument("--now", default=None, help="ISO timestamp to evaluate at (default: the current time)")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("status", parents=[common], help="the league table, the last evaluations and the role changes")

    evaluate = commands.add_parser("evaluate", parents=[common], help="evaluate every challenger against the champion")
    mode = evaluate.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="write audit rows and apply the decisions")
    mode.add_argument("--dry-run", action="store_true", help="evaluate only, write nothing (default)")

    propose = commands.add_parser("propose", parents=[common], help="run the historical lab and register the gate-passing candidates")
    propose.add_argument("--dry-run", action="store_true", help="show what would be registered, write nothing")
    propose.add_argument("--seed", type=int, default=42)
    propose.add_argument("--configs", type=int, default=DEFAULT_CONFIGS)
    propose.add_argument("--max-seconds", type=float, default=DEFAULT_MAX_SECONDS, help="time budget; the lab is partial beyond it")

    promote = commands.add_parser("promote", parents=[common], help="MANUAL: make a model the champion (the old one becomes a challenger)")
    promote.add_argument("model_id", type=int)
    promote.add_argument("--reason", required=True)
    promote.add_argument("--force", action="store_true", help="also during the cooldown, and for a retired model")

    retire = commands.add_parser("retire", parents=[common], help="MANUAL: retire a challenger")
    retire.add_argument("model_id", type=int)
    retire.add_argument("--reason", required=True)
    return parser


def _when(moment: Optional[datetime]) -> str:
    return "-" if moment is None else moment.strftime("%Y-%m-%d")


def format_status(session, now: datetime) -> str:
    rows = model_promotion.league_rows(session)
    lines = [f"Model league ({now.isoformat()})"]
    if not rows:
        return "\n".join(lines + ["  No model registered."])
    lines.append(f"  {'id':>3}  {'model':<30}{'role':<11}{'parent':>7}{'preds':>7}{'final':>7}  {'last evaluation'}")
    for row in rows:
        last = "-" if row.last_decision is None else f"{row.last_decision} ({_when(row.last_evaluated_at)})"
        lines.append(
            f"  {row.model_id:>3}  {row.label:<30}{row.role:<11}{'-' if row.parent_id is None else row.parent_id:>7}"
            f"{row.predictions:>7}{row.final_games:>7}  {last}"
        )
    changes = model_promotion.role_changes(session, limit=10)
    lines.append("")
    lines.append("Role changes (newest first)")
    if not changes:
        lines.append("  none yet")
    for change in changes:
        lines.append(f"  {_when(change.evaluated_at)}  model {change.challenger_id}: {change.decision} - {change.reason}")
    return "\n".join(lines)


def _guard(session, args) -> None:
    check_registration_target(session.get_bind().url, args.confirm_database)


def _parse_now(value: Optional[str]) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    moment = datetime.fromisoformat(value)
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=timezone.utc)


def main(argv: Optional[List[str]] = None, session_factory=None) -> int:
    args = build_parser().parse_args(argv)
    if session_factory is None:
        from app.deps import get_db_context  # imported late so --help never builds a DB engine

        session_factory = get_db_context
    try:
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError, OSError):
        pass
    now = _parse_now(args.now)

    with session_factory() as session:
        try:
            if args.command == "status":
                print(format_status(session, now))
            elif args.command == "evaluate":
                if args.apply:
                    _guard(session, args)
                print(model_promotion.format_pass(model_promotion.run_evaluation_pass(session, now, apply=bool(args.apply))))
            elif args.command == "propose":
                if not args.dry_run:
                    _guard(session, args)
                started = time.monotonic()
                outcome = model_promotion.run_proposal(
                    session, now, dry_run=args.dry_run, seed=args.seed, n_configs=args.configs,
                    deadline=started + args.max_seconds, confirm_database=args.confirm_database,
                )
                print(f"Proposal ({'dry run' if args.dry_run else 'live'}): {outcome.summary}")
                for note in outcome.report.notes:
                    print(f"  note: {note}")
                for candidate in outcome.report.candidates:
                    verdict = "passes" if candidate.gate.passed else "rejected - " + "; ".join(candidate.gate.reasons)
                    print(f"  {candidate.label}: hold-out gain {candidate.gate.gain:+.4f}, {verdict}")
                for item in outcome.registration.planned if args.dry_run else outcome.registration.registered:
                    print(f"  {'would register' if args.dry_run else 'registered'}: {item.name} {item.version}")
                for reason in outcome.registration.skipped:
                    print(f"  skipped: {reason}")
            elif args.command == "promote":
                _guard(session, args)
                row = model_promotion.manual_promote(session, args.model_id, args.reason, now, force=args.force)
                print(f"model {args.model_id} is now the champion (audit row {row.id}: {row.reason})")
            elif args.command == "retire":
                _guard(session, args)
                row = model_promotion.manual_retire(session, args.model_id, args.reason, now)
                print(f"model {args.model_id} retired (audit row {row.id}: {row.reason})")
        except (RegistrationRefused, model_promotion.ManualOverrideRefused) as exc:
            print(f"refused: {exc}", file=sys.stderr)
            return 2
        except LabError as exc:
            print(f"the lab cannot run: {exc}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
