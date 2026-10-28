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
- [x] WP1 Pinnacle-referenced CLV, clustered per game, in `paper_report` plus a read-only `GET /api/v1/paper/*` API; totals/props audit script (research items 1 and 7) - delegated.
- [x] WP2 Staking and benchmark arm: `kelly_shrunk` and `market_edge` strategies (enum migration, recorder, settlement, report) (items 2 and 3) - delegated, lockstep deploy.
- [x] WP3 League API (`GET /api/v1/league`, cached) and promotion notifications over Telegram (ROADMAP 3 backend, 4) - delegated.
- [x] WP4 Data honesty: remove the fabricated injury fallback, explicit "unavailable", terms-gated PDF parser, lineup logger for `nba_api` live boxscore (items 5 and 6) - delegated.
- [x] WP5 Quality and safety: CI workflow, `testpaths`, shutdown origin/host check (ROADMAP 5, 9) - delegated.
- [x] WP6 Correctness: postponed-game polling, `props_engine` baselines from the database, props credit guard and cache freshness (ROADMAP 7, 11, hygiene) - delegated.
- [x] WP10 Multiple-comparison control in the candidate lab (item 4) - delegated.

Wave B (frontend, after the APIs merge):
- [x] WP7 Model league page.
- [x] WP8 Paper-trading dashboard (KPIs, bankroll, CLV vs Pinnacle, bets table with filters).
- [x] WP9 Props page UX and design pass (states, mobile, accessibility, data freshness, credit usage).

Wave C (the rest of the roadmap, added 2026-10-28 after the first deployment):
- [x] WP-P Closing-quote presence record (ROADMAP 6): table `odds_capture_presence`, migration `f1a9c3d7e5b2` (also replaces the `v_closing_odds` view, backward compatible for captures without presence rows), `absent_at_close` exclusion in CLV.
- [x] WP-L Legacy cleanup (ROADMAP 10): report code moved to `app/services/scouting_report/`, 19 dead prototype files removed with zero-user evidence in `odd/tasks/legacy-cleanup.md`; the Excel ETL and its data files kept.
- [x] WP-T Totals (ROADMAP 2, game lines): grading with pushes, same-book and Pinnacle CLV, `market_edge`-only paper bets attached to a model-free `market_pinnacle` benchmark model (role `benchmark`, migration `a2c4e6f8b1d3`, D-57). Props models deliberately deferred.
- [x] WP-F Second odds feed (ROADMAP 8): SportsGameOdds client, disabled without a key, never bets alone, unverified against live responses.

Wave D:
- [ ] WP11 Docs, ROADMAP and decisions updated; final verification and a production deploy.

## Acceptance criteria
- Each pull request: tests green with the count stated, `tsc --noEmit` clean for frontend work, the work package's own criteria met (see its brief in the commit/PR body).
- `paper_report.py` shows Pinnacle-referenced CLV with standard error and independent-game count.
- No code path returns invented data.
- The tick keeps running (exit code 0) through every merge and the lockstep deploy.

## Checks
- Backend suite on the integrated branch: 843 passed, 4 skipped (baseline 755 + 88 new), run by Claude, not taken from the agents' reports.
- `tsc --noEmit` clean; `next build --webpack` succeeds (Turbopack refuses the shared `node_modules` symlink of the worktrees); eslint clean on the new files (30 pre-existing errors elsewhere untouched).
- Migration `e3f8b1a4c9d2` applied to a throwaway copy of the production database (`nba_staging`): enum shows flat, kelly_fractional, kelly_shrunk, market_edge.
- Pinnacle CLV recomputed independently with SQL: 21 of 21 h2h games within 0.0002 log units of the service.
- New API endpoints (`/paper/*`, `/league`) answered with real data from the copy; `POST /system/shutdown` without Origin returns 403.
- UI: `/paper`, `/league`, `/props` captured in headless Edge at desktop and with DevTools mobile emulation at 390 px; the top bar overflowed on every page (pre-existing) and was fixed (document width 390 on all three).
- Wave C: 893 passed, 4 skipped on the integrated branch; migrations f1a9c3d7e5b2 and a2c4e6f8b1d3 applied to a fresh copy of the production database (check constraint now lists benchmark; `v_closing_odds` 4070 rows; Pinnacle CLV unchanged at +0.34%); the real recorder run on that copy created `market_pinnacle` and the league report still lists only the champion and challengers.
- WP-T first design (totals bets under the champion's model_version) was rejected in review: it attributed to the champion a prediction it never made (rule 8).
- Not exercised on real quotes: totals bets and the presence rows (no fresh quotes were available when tested); the recorder with the two new strategies (it only reads scheduled games, so a replay is impossible); first real use is the first tick after deployment.

## Progress
2026-10-28: plan created from the research report; worktrees prepared. Wave A (WP1-WP6, WP10) and Wave B (WP7-WP9) written by Antigravity agents on Gemini 3.8 Flash (High), merged locally into `integration/betting`, verified by Claude. Navbar mobile fix added. Pull requests and deployment wait for the owner's approval to merge.

## Follow-ups (out of scope)
- Props models and props paper bets: props bets are not recorded anywhere and one event per tick is too small a sample.
- A model-driven totals predictor: no verified evidence of an edge (closing-total error sd 17.7 points).
- The second feed needs the owner's API key and a probe run (`scripts/sgo_probe.py`) before it can be trusted.
- On the props page (mobile) the Filtros button overlaps the last category chip.

## Next step
Open the pull requests, get the owner's approval to merge, then deploy in lockstep (pause the tick, backup, pull, `alembic upgrade head`, dry runs, resume, one real tick) and check the first tick with the two new strategies.
