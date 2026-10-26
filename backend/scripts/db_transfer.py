"""
Moves the whole PostgreSQL database to another machine with integrity checks on both ends
(logic: app/services/db_transfer.py, runbook: docs/DB_TRANSFER.md).

    python scripts/db_transfer.py export [--out-dir DIR] [--name NAME] [--database-url URL] [--pg-bin DIR]
    python scripts/db_transfer.py verify DUMP [--pg-bin DIR]
    python scripts/db_transfer.py import --dump FILE [--target-url URL] [--create-db]
                                         [--replace --confirm-database NAME] [--skip-analyze] [--pg-bin DIR]
    python scripts/db_transfer.py manifest DUMP_OR_MANIFEST

`export` writes <name>.dump (pg_dump custom format) and <name>.manifest.json (exact row count of every table,
server and Alembic versions, sha256) into ../ArchetypeNBA-backups by default; it refuses to write inside the
repository. `verify` needs no database. `import` verifies first, restores into an EMPTY database in one transaction
and compares the exact row count of every table with the manifest.

The database URL defaults to DATABASE_URL from backend/.env. The password never goes into argv of pg_dump/pg_restore;
to keep it out of this command line too, leave it out of the URL and set PGPASSWORD (or use a pgpass file).

Exit codes: 0 ok; 1 an operation failed or a table did not match the manifest; 2 refused before anything was
changed (bad input, failed integrity check, unmet precondition).
"""
import argparse
import sys
from pathlib import Path
from typing import Callable, List, Optional

# Add backend directory to sys.path
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from app.services.db_transfer import (  # noqa: E402
    MANIFEST_SUFFIX,
    DbTarget,
    SqlInspector,
    SubprocessRunner,
    TransferError,
    TransferService,
    discover_pg_tools,
    format_comparison,
    format_size,
    load_manifest,
    manifest_path_for,
)

ServiceFactory = Callable[[Optional[str]], TransferService]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export, verify and import the whole PostgreSQL database.")
    commands = parser.add_subparsers(dest="command", required=True, metavar="{export,verify,import,manifest}")

    export = commands.add_parser("export", help="dump the database and write a manifest next to the dump")
    export.add_argument("--out-dir", default=None, help="output folder (default: ../ArchetypeNBA-backups; never inside the repo)")
    export.add_argument("--name", default=None, help="file stem (default: nba_platform_<YYYYmmdd_HHMM>)")
    export.add_argument("--database-url", default=None, help="source database (default: DATABASE_URL from backend/.env)")
    export.add_argument("--pg-bin", default=None, help="folder with pg_dump and pg_restore (default: PATH, then the usual install folders)")
    export.set_defaults(handler=run_export)

    verify = commands.add_parser("verify", help="check a dump against its manifest (sha256 + readable archive); no database needed")
    verify.add_argument("dump", help="path to the .dump file; <name>.manifest.json must sit next to it")
    verify.add_argument("--pg-bin", default=None, help="folder with pg_dump and pg_restore")
    verify.set_defaults(handler=run_verify)

    restore = commands.add_parser("import", help="restore a dump into an empty database and compare every table")
    restore.add_argument("--dump", required=True, help="path to the .dump file; <name>.manifest.json must sit next to it")
    restore.add_argument("--target-url", default=None, help="target database (default: DATABASE_URL from backend/.env)")
    restore.add_argument("--create-db", action="store_true", help="create the target database when it does not exist")
    restore.add_argument("--replace", action="store_true", help="wipe a NON-empty target first (needs --confirm-database)")
    restore.add_argument("--confirm-database", default=None, metavar="NAME", help="exact target database name, required with --replace")
    restore.add_argument("--skip-analyze", action="store_true", help="do not run ANALYZE after the restore")
    restore.add_argument("--pg-bin", default=None, help="folder with pg_dump and pg_restore")
    restore.set_defaults(handler=run_import)

    show = commands.add_parser("manifest", help="print a manifest (accepts the .dump or the .manifest.json path)")
    show.add_argument("path", help="path to the .dump or the .manifest.json file")
    show.set_defaults(handler=run_manifest)
    return parser


def default_database_url() -> str:
    from app.config import settings  # imported late so --help never reads backend/.env

    return settings.DATABASE_URL


def build_service(pg_bin: Optional[str]) -> TransferService:
    runner = SubprocessRunner()
    folder = Path(pg_bin) if pg_bin else None
    return TransferService(
        runner,
        SqlInspector,
        lambda required_major: discover_pg_tools(runner, required_major=required_major, pg_bin=folder),
        log=lambda message: print(message, flush=True),
    )


def _print_warnings(warnings: List[str]) -> None:
    for warning in warnings:
        print(f"WARNING: {warning}")


def run_export(args: argparse.Namespace, make_service: ServiceFactory) -> int:
    service = make_service(args.pg_bin)
    source = DbTarget.from_url(args.database_url or default_database_url())
    result = service.export_database(source, out_dir=Path(args.out_dir) if args.out_dir else None, name=args.name)
    manifest = result.manifest
    print(f"\nExported {manifest.name}")
    print(f"  dump:      {result.dump_path} ({format_size(manifest.dump_size_bytes)})")
    print(f"  manifest:  {result.manifest_path}")
    print(f"  sha256:    {manifest.dump_sha256}")
    print(f"  contents:  {len(manifest.tables)} tables, {manifest.total_rows:,} rows")
    print(f"  alembic:   database {manifest.alembic_database_version or 'none'}, code head {manifest.alembic_code_head or 'unknown'}")
    _print_warnings(result.warnings)
    print("Copy BOTH files to the other machine, then run: python scripts/db_transfer.py verify <dump>")
    return 0


def run_verify(args: argparse.Namespace, make_service: ServiceFactory) -> int:
    result = make_service(args.pg_bin).verify_dump(Path(args.dump))
    _print_warnings(result.warnings)
    print(f"\nVERIFIED: {result.dump_path.name} is intact and matches {result.manifest_path.name}.")
    return 0


def run_import(args: argparse.Namespace, make_service: ServiceFactory) -> int:
    service = make_service(args.pg_bin)
    if not args.target_url:
        print("No --target-url given: importing into DATABASE_URL from backend/.env")
    target = DbTarget.from_url(args.target_url or default_database_url())
    result = service.import_dump(
        Path(args.dump),
        target,
        create_db=args.create_db,
        replace=args.replace,
        confirm_database=args.confirm_database,
        skip_analyze=args.skip_analyze,
    )
    print()
    print(format_comparison(result.rows, result.alembic_expected, result.alembic_actual))
    _print_warnings(result.warnings)
    if not result.ok:
        bad = len(result.mismatches) + (0 if result.alembic_expected == result.alembic_actual else 1)
        print(f"\nRESULT: MISMATCH - {bad} check(s) failed, see the table above. The restored data cannot be trusted.")
        return 1
    print(f"\nRESULT: OK - all {len(result.rows)} tables and the Alembic revision match the manifest.")
    print(f"Next: cd backend && alembic current   (expect {result.alembic_actual or 'no revision'}), then python -m pytest -q")
    return 0


def run_manifest(args: argparse.Namespace, make_service: ServiceFactory) -> int:
    path = Path(args.path)
    manifest = load_manifest(path if path.name.endswith(MANIFEST_SUFFIX) else manifest_path_for(path))
    print(manifest.to_json(), end="")
    return 0


def main(argv: Optional[List[str]] = None, service_factory: Optional[ServiceFactory] = None) -> int:
    args = build_parser().parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        try:  # a cp1252 console must not crash the run on a non-ASCII message
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError, OSError):
            pass
    try:
        return args.handler(args, service_factory or build_service)
    except TransferError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return exc.exit_code
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
