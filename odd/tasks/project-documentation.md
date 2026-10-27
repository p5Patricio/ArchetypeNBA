# Feature: project-documentation

## Objective
A new agent on a different PC can understand, run, operate and extend the project from the repository alone.

## Problem
- No `AGENTS.md`; README describes only the analytics platform (and says 61 tests); `ARCHITECTURE_REPORT.md` is a pre-implementation proposal; the quant system (odds capture, Elo, recorder, settlement, learning loop, scheduled tick) is documented only in `odd/tasks/*` plans.
- No `.env.example`, no setup guide, no operations runbook, no decision log.

## Deliverables
- `AGENTS.md` + `CLAUDE.md` pointer (written by the previous agent; source of truth for decisions).
- `docs/`: `README.md` (index), `ARCHITECTURE.md`, `QUANT_MODULE.md`, `OPERATIONS.md`, `SETUP.md`, `DECISIONS.md`, `ROADMAP.md`; `DB_TRANSFER.md` and `backend/.env.example` come from the `db-transfer` feature (merged, PR #19).
- `README.md` refreshed (quant module section, correct test count, architecture tree, links); banners on `ARCHITECTURE_REPORT.md` and `NBA_Data_Sources_Report.md` marking them as historical/research.
- `odd/README.md` index of feature plans with status.

## Constraints
- Facts verified against the code, not copied from memory; numbers carry a date.
- Artifacts in English. Progressive disclosure: answer first, details after, tables over prose.
- No secrets, no absolute user paths in committed docs (use relative paths), no real API keys.

## Tasks
- [x] P1 `AGENTS.md`, `CLAUDE.md` — inline (needs conversation context)
- [x] P2 `docs/*` and README/banners/odd index — delegated writer, verified against code. Done 2026-10-26: `docs/{README,ARCHITECTURE,QUANT_MODULE,OPERATIONS,SETUP,DECISIONS,ROADMAP}.md`, `odd/README.md`, the README refresh and the historical banners on `ARCHITECTURE_REPORT.md` and `NBA_Data_Sources_Report.md`. Follow-up commits after PR #18 and PR #19: removed the extra psycopg install notes, documented the portable Python discovery, linked the transfer runbook, added decisions D-48 to D-54. Checks: every command's flags read from `--help`; all relative links resolve (checked with a script); `cd backend && python -m pytest -q` gives 757 passed (2026-10-26, includes the transfer tool's tests).
- [x] P3 Independent accuracy check of the docs against the code — delegated verifier (2026-10-26). Result: the quant documentation was accurate (constants, thresholds, CLI flags, tables, Alembic chain, 294 links). Seven defects found and fixed: four wrong routes and stale tech-stack claims in the product README (UMAP/Canvas Confetti/Radix), the `sslmode` limitation in `docs/DB_TRANSFER.md` (it IS forwarded), `.env.example` CORS defaults and ETL_BATCH_SIZE note, stale test counts and PR range in AGENTS.md, the `RESULT: OK` last-line wording, and a false MIT licence claim (no LICENSE file; the README now says no licence is chosen).
- [x] P4 Merge the docs branch, then pull main on the production checkout — inline. `feat/db-transfer` is already merged (PR #19) and `main` was merged into the docs branch

## TDD
- Mode: off. Docs only; `python -m pytest -q` must still pass.
