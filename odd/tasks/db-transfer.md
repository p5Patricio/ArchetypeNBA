# Feature: db-transfer

## Objective
Move the complete PostgreSQL database (229 MB on 2026-10-26) to a different PC without losing anything, with integrity checks on both ends and no data or secrets in git.

## Problem
- The next AI agent will work on a different PC. The database holds irreplaceable data: odds captured every few minutes since 2026-10-06 (closing lines cannot be backfilled on free tiers), predictions, paper bets, model registry and evaluations, plus 23 seasons of game logs and Elo ratings (rebuildable, but slow).
- There is no tool to export/import it, no manifest to verify a restore, and no `.env.example`.

## Design decisions
1. Python CLI `backend/scripts/db_transfer.py` (cross-platform; the new PC may not be Windows) on top of `pg_dump -Fc` / `pg_restore`, with logic in `backend/app/services/db_transfer.py` so it is unit-testable with a fake process runner.
2. `export`: consistent snapshot of the WHOLE database (tables, sequences, views, enums, indexes, `alembic_version`), `--no-owner --no-privileges`. Writes `<name>.dump` and `<name>.manifest.json` (created_at, source server version, pg_dump version, alembic version in the database and in the code, DB `timezone` setting, exact row count of every table, size, sha256, git commit). Default output dir `../ArchetypeNBA-backups/`; refuses to write inside the git working tree.
3. `verify`: sha256 against the manifest and `pg_restore --list` (the dump is readable) with no database needed.
4. `import`: verifies integrity, checks the target server major version >= the dump's source major, refuses a non-empty target unless `--replace --confirm-database NAME`, restores in a single transaction (all or nothing) with `--exit-on-error`, runs `ANALYZE`, then compares EXACT row counts of every table and the alembic version with the manifest and exits non-zero on any mismatch. `--create-db` creates the database if missing.
5. Binaries: PATH, `--pg-bin`, or common install locations (Windows `Program Files\PostgreSQL\*\bin`, Homebrew, Debian/Ubuntu `/usr/lib/postgresql/*/bin`); pick one whose major is >= the server's.
6. Secrets: the password travels only in the subprocess environment (`PGPASSWORD`), never in argv, logs or the manifest.
7. The dump is NOT committed (size, odds-provider terms). It travels by USB/cloud/scp together with the manifest; `.env` travels separately through a secure channel.
8. Only one PC may run the capture tick at a time (same Odds API key quota, diverging databases): documented cutover order.

## Tasks
- [ ] D1 `db_transfer` service + CLI + unit tests — route: delegated writer
- [ ] D2 `docs/DB_TRANSFER.md` runbook and `backend/.env.example` — route: delegated writer (same writer, separate commit)
- [ ] D3 Real validation: export the real database, import it into a scratch database on the same server, compare every table — route: inline
- [ ] D4 PR and merge — route: inline

## Constraints
- Free tools only (PostgreSQL client tools). The real database is read only for D1/D2; D3 writes only to a scratch database that is dropped afterwards.
- Artifacts in English.

## TDD
- Mode: off. Runner: `python -m pytest -q` from `backend/`.

## Next step
Run D1 and D2.
