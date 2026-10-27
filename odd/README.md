# ODD: the feature plans

ODD (organic driven development) is how this project is built: before the first source write of any substantial change, a plan file is created in [`tasks/`](tasks/) and kept up to date as work is done. Those files are the project's decision history: they record the objective, the problem, the constraints, the numbers that were measured and the reasons, task by task. When you wonder why something is the way it is, look here first, then in [`../docs/DECISIONS.md`](../docs/DECISIONS.md), which distils them.

## Quick path

1. Find the feature in the index below.
2. Read its plan top to bottom; the checked tasks carry the evidence (commits, test counts, measured results).
3. Starting new substantial work? Copy the [template](#template-for-a-new-plan) before writing code.

## Index

| Plan | Objective | Status | Pull requests |
|------|-----------|--------|---------------|
| [`quant-paper-trading.md`](tasks/quant-paper-trading.md) | A persistence layer for odds history, predictions and simulated bets with CLV, and trustworthy odds ingestion, using only free sources | Delivered (T1 to T9) | #1 props on demand and shutdown (the user's work, the base of the stack), #2 quant schema, #3 odds integrity, #4 live props lines, #5 odds ingestion, #6 snapshot CLI, credit budget and key-leak fix |
| [`season-readiness.md`](tasks/season-readiness.md) | Make unattended odds capture reliable and credit-safe before the 2026-10-20 opener | Delivered (S2 to S5). S1, merging #1 to #6, is still unchecked in the file but those pull requests merged on 2026-10-17 | #7 explicit capture markers, wider closing coverage, honest exit codes |
| [`elo-prediction-recorder.md`](tasks/elo-prediction-recorder.md) | A baseline Elo for game lines, a recorder that persists every prediction and paper bet at decision time, a logon-triggered tick, then results, settlement and CLV | Delivered (E1 to E5). Open follow-ups: totals and props, postponed-game polling, closing-quote presence | #8 Elo engine and backfill (E1), #9 recorder and betting policy (E2), #10 season-selection fix found while operating, #11 logon tick (E3), #12 results sync and settlement (E4); E5 was operations on the real database |
| [`model-learning-loop.md`](tasks/model-learning-loop.md) | A closed, auditable loop that proposes candidate models, runs them in shadow, compares them with proper statistics and promotes or rolls back only on evidence | Delivered (L1 to L4). Open follow-ups: totals and props models, a frontend page, notifications | #13 registry and shadow predictions (L1), #14 feature model and lab (L2), #15 evaluation, promotion and the `learn` step (L3). Related: #16 `pythonw.exe` for the scheduled tick, #17 close-out of the plan; L4 was operations |
| [`db-transfer.md`](tasks/db-transfer.md) | Move the complete PostgreSQL database to another PC without losing anything, with integrity checks on both ends and no data or secrets in git | Done (D1 to D4). Validated on 2026-10-26: 21 tables, 831,058 rows, a 17.3 MB dump of the 229 MB database; the restored copy matched every table and reproduced the live `paper_report.py`, `model_league.py status` and `run_tick.py --dry-run` | #19 export, verify and import tool, runbook (`docs/DB_TRANSFER.md`), `.env.example`, ignore rules |
| (no plan file) portable install | `requirements.txt` and `pyproject.toml` declare the psycopg 3 driver the code uses; the tick registration discovers Python on any PC; `AGENTS.md` corrected against the code | Done; recorded in the commit messages of the pull request and in `AGENTS.md` section 8 | #18 |
| [`project-documentation.md`](tasks/project-documentation.md) | A new agent on another PC can understand, run, operate and extend the project from the repository alone | In progress: P1 (`AGENTS.md`) and P2 (`docs/`, README, this index) done; P3 (independent accuracy check) and P4 (merge the docs branch) pending | This work (no number yet) |

## How the plans are used

| Rule | Detail |
|------|--------|
| Create before the first source write | Substantial means coordinated steps or progress worth recovering after an interruption. A small, understood change needs no plan |
| One file per feature | `odd/tasks/<feature-name>.md`; reuse the same name for the same feature, never overwrite another feature's file |
| Check a box only with evidence | Record the commit, the test count or the measured result next to the task; list failed, skipped and pending checks honestly |
| Update as you go | Accepted changes of scope update the plan; business scope changes still need the user |
| Keep the follow-ups | Anything found and deliberately left out goes under "Follow-ups"; the roadmap ([`../docs/ROADMAP.md`](../docs/ROADMAP.md)) is built from them |
| Pull requests | Each work unit is a pull request with a chain context; the plan records which commits belong to which slice (see D-45 in [`../docs/DECISIONS.md`](../docs/DECISIONS.md)) |

The original author also mirrored each plan into a local memory store. That store does not travel with the repository; the plan files do.

## Template for a new plan

```markdown
# Feature: <feature-name>

## Objective
## Problem
## Why
## Scope
## Constraints
## TDD
- Mode: off | on. Source. Runner: `python -m pytest -q` from `backend/`.
## Delivery
- Strategy, chain strategy, forecast of changed lines.
## Tasks
- [ ] T1 <outcome> - route: inline | delegated. Checks and evidence.
## Acceptance criteria
## Checks
## Progress
## Follow-ups (out of scope)
## Next step
```

## Next step

For the reasons distilled from these plans: [`../docs/DECISIONS.md`](../docs/DECISIONS.md).
