# Feature: project-documentation

## Objective
A new agent on a different PC can understand, run, operate and extend the project from the repository alone.

## Problem
- No `AGENTS.md`; README describes only the analytics platform (and says 61 tests); `ARCHITECTURE_REPORT.md` is a pre-implementation proposal; the quant system (odds capture, Elo, recorder, settlement, learning loop, scheduled tick) is documented only in `odd/tasks/*` plans.
- No `.env.example`, no setup guide, no operations runbook, no decision log.

## Deliverables
- `AGENTS.md` + `CLAUDE.md` pointer (written by the previous agent; source of truth for decisions).
- `docs/`: `README.md` (index), `ARCHITECTURE.md`, `QUANT_MODULE.md`, `OPERATIONS.md`, `SETUP.md`, `DECISIONS.md`, `ROADMAP.md`; `DB_TRANSFER.md` and `backend/.env.example` come from the `db-transfer` feature.
- `README.md` refreshed (quant module section, correct test count, architecture tree, links); banners on `ARCHITECTURE_REPORT.md` and `NBA_Data_Sources_Report.md` marking them as historical/research.
- `odd/README.md` index of feature plans with status.

## Constraints
- Facts verified against the code, not copied from memory; numbers carry a date.
- Artifacts in English. Progressive disclosure: answer first, details after, tables over prose.
- No secrets, no absolute user paths in committed docs (use relative paths), no real API keys.

## Tasks
- [x] P1 `AGENTS.md`, `CLAUDE.md` — inline (needs conversation context)
- [ ] P2 `docs/*` and README/banners/odd index — delegated writer, verified against code
- [ ] P3 Independent accuracy check of the docs against the code — delegated verifier
- [ ] P4 Merge `feat/db-transfer`, then docs, then pull main — inline

## TDD
- Mode: off. Docs only; `python -m pytest -q` must still pass.
