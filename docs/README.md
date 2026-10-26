# Documentation index

Everything written about ArchetypeNBA, in one place, with the order to read it in depending on who you are. The root [`AGENTS.md`](../AGENTS.md) is the short map and rulebook (decisions, non-negotiable rules, gotchas, current state); these documents are the deep dives. Facts were checked against the code on 2026-10-26 and numbers carry their date.

## Quick path

| You are | Read, in this order |
|---------|--------------------|
| A new agent or developer | [`AGENTS.md`](../AGENTS.md), then [`ARCHITECTURE.md`](ARCHITECTURE.md), [`SETUP.md`](SETUP.md), [`ROADMAP.md`](ROADMAP.md) |
| An operator | [`OPERATIONS.md`](OPERATIONS.md), then [`SETUP.md`](SETUP.md), [`DB_TRANSFER.md`](DB_TRANSFER.md) (pending merge) |
| A modeller or reviewer | [`QUANT_MODULE.md`](QUANT_MODULE.md), then [`DECISIONS.md`](DECISIONS.md), [`ARCHITECTURE.md`](ARCHITECTURE.md), [`ROADMAP.md`](ROADMAP.md) |

## Documents

| Document | One line |
|----------|----------|
| [`../AGENTS.md`](../AGENTS.md) | The map and rulebook for any agent: rules, working agreements, gotchas, state, next task |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | Components, the tick pipeline, tables and views, module map, API surface, configuration |
| [`QUANT_MODULE.md`](QUANT_MODULE.md) | The methodology: odds maths, Elo, the `margin_features` model, betting policy, CLV and its biases, evaluation and promotion rules, how to read the reports, honest limits |
| [`OPERATIONS.md`](OPERATIONS.md) | Runbook: the scheduled task, credit budget, daily and weekly checks, schema deploys, manual controls, web services, Linux and macOS schedulers, troubleshooting |
| [`SETUP.md`](SETUP.md) | Install and configure from scratch on any OS, fill the database, run the tests, first-day checklist |
| [`DB_TRANSFER.md`](DB_TRANSFER.md) | Export and restore the database when moving machines (**pending merge**, written by the database-transfer work) |
| [`DECISIONS.md`](DECISIONS.md) | Decision log (47 entries): what was decided, why, what was rejected, what followed |
| [`ROADMAP.md`](ROADMAP.md) | Prioritized backlog with acceptance criteria, risks and a first step; item 1 is the next task |
| [`../odd/README.md`](../odd/README.md) | Index of the feature plans in `odd/tasks/` (the decision history) and what ODD is |
| [`../README.md`](../README.md) | The product description and quick start |

### Historical, kept for context

| Document | Status |
|----------|--------|
| [`../ARCHITECTURE_REPORT.md`](../ARCHITECTURE_REPORT.md) | The April 2026 proposal to move from Excel to PostgreSQL; superseded by [`ARCHITECTURE.md`](ARCHITECTURE.md) |
| [`../NBA_Data_Sources_Report.md`](../NBA_Data_Sources_Report.md) | Research on free NBA data sources; the current feed decisions are in [`DECISIONS.md`](DECISIONS.md) and the open ones in [`ROADMAP.md`](ROADMAP.md) |
| [`superpowers/plans/`](superpowers/plans/) | Two May 2026 implementation plans for the original platform's data engine and product integration |

## Conventions

| Topic | Rule |
|-------|------|
| Language | Artifacts (code, comments, docs, commits, pull requests) are in English; conversation follows the user's language |
| Paths | Relative to the repository root; no user names, no real keys, no passwords in committed files |
| Numbers | Carry a date; re-measure before relying on them |
| Update when | A behavior, a constant, a command or a schema changes: update the document that owns it in the same pull request |

## Next step

New here? Start with [`../AGENTS.md`](../AGENTS.md).
