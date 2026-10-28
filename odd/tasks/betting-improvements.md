# Feature: betting-improvements

## Objective
Improve the sports-betting side of ArchetypeNBA in function, UI and UX using only free tiers, following the verified recommendations of [`docs/RESEARCH_BETTING_IMPROVEMENTS.md`](../../docs/RESEARCH_BETTING_IMPROVEMENTS.md) and the open items of [`docs/ROADMAP.md`](../../docs/ROADMAP.md). Paper trading only.

## Problem
- CLV is measured against the bet's own (often soft) book, per bet, with flat and Kelly counted twice for the same game: it cannot support a claim of skill (research E10).
- Stakes use a fixed quarter-Kelly although model error is the dominant uncertainty (E1).
- No benchmark separates "the model has skill" from "line shopping pays".
- The model league and the paper-trading results are readable only in a terminal.
- `injury_scraper.py` returns invented injuries (rule 3); the shutdown endpoint has no origin check; there is no CI; a bare `pytest` hangs under WSL; postponed games are polled for 14 days; `props_engine` falls back to hardcoded baselines.

## Why
The market is efficient (research section 1); real progress needs trustworthy measurement first, honest data, then better signals. UI/UX work makes the evidence visible to the owner.

## Scope
Free sources only. No real-money features. No paid APIs. Automated download of NBA injury PDFs stays **off by default** until the owner answers the terms question (`AGENTS.md` rule 9, research section 4).

## Constraints
- All source written by Antigravity agents on model `Gemini 3.8 Flash (High)` only (owner instruction, 2026-10-28); Claude plans, reviews, verifies and merges.
- One git worktree and branch per work package under `../ArchetypeNBA-worktrees/`; the main checkout runs the tick and is touched only by `git pull` after a merge (rule 7).
- Schema changes follow the lockstep deploy (`docs/OPERATIONS.md` section 4).
- Tests offline and deterministic; run `python -m pytest tests -q` (never a bare `pytest`).
- Conventional Commits, no AI attribution trailers in commits.

## TDD
- Mode: on for backend logic (failing test first where practical). Runner: `python -m pytest tests -q` from `backend/`. Frontend: `npx tsc --noEmit` and `npm run lint`.

## Delivery
- One pull request per work package, merged to `main` one at a time after its tests pass. Backend wave first (WP1-WP6), frontend wave after (WP7-WP9), docs last.

## Tasks
Wave A (backend, parallel):
- [ ] WP1 Pinnacle-referenced CLV, clustered per game, in `paper_report` plus a read-only `GET /api/v1/paper/*` API; totals/props audit script (research items 1 and 7) - delegated.
- [ ] WP2 Staking and benchmark arm: `kelly_shrunk` and `market_edge` strategies (enum migration, recorder, settlement, report) (items 2 and 3) - delegated, lockstep deploy.
- [ ] WP3 League API (`GET /api/v1/league`, cached) and promotion notifications over Telegram (ROADMAP 3 backend, 4) - delegated.
- [ ] WP4 Data honesty: remove the fabricated injury fallback, explicit "unavailable", terms-gated PDF parser, lineup logger for `nba_api` live boxscore (items 5 and 6) - delegated.
- [ ] WP5 Quality and safety: CI workflow, `testpaths`, shutdown origin/host check (ROADMAP 5, 9) - delegated.
- [ ] WP6 Correctness: postponed-game polling, `props_engine` baselines from the database, props credit guard and cache freshness (ROADMAP 7, 11, hygiene) - delegated.
- [ ] WP10 Multiple-comparison control in the candidate lab (item 4) - delegated.

Wave B (frontend, after the APIs merge):
- [ ] WP7 Model league page.
- [ ] WP8 Paper-trading dashboard (KPIs, bankroll, CLV vs Pinnacle, bets table with filters).
- [ ] WP9 Props page UX and design pass (states, mobile, accessibility, data freshness, credit usage).

Wave C:
- [ ] WP11 Docs, ROADMAP and decisions updated; final verification and a production deploy.

## Acceptance criteria
- Each pull request: tests green with the count stated, `tsc --noEmit` clean for frontend work, the work package's own criteria met (see its brief in the commit/PR body).
- `paper_report.py` shows Pinnacle-referenced CLV with standard error and independent-game count.
- No code path returns invented data.
- The tick keeps running (exit code 0) through every merge and the lockstep deploy.

## Checks
Pending.

## Progress
2026-10-28: plan created from the research report; worktrees prepared.

## Follow-ups (out of scope)
- Totals and props models (measure first with the audit script from WP1).
- Legacy cleanup (ROADMAP 10): risky, importers mapped but removal deferred.
- Second odds feed (ROADMAP 8) and closing-quote presence (ROADMAP 6) need terms and schema work; revisit after WP1 results.

## Next step
Merge this plan, then launch Wave A.
