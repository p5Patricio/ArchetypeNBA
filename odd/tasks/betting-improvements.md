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

Wave D (closing the gaps the stop hook and the first review found):
- [x] WP-S1 Shadow totals predictor `totals_pace` (role `shadow`, migration `b3d5f7a9c1e4`), evaluated against Pinnacle's close; no bets.
- [x] WP-S2 Player-prop quotes are now persisted (finding: 40 `closing_props` captures spent 40 credits, saw 12,325 quotes and inserted 0) and a shadow props model `props_nb` is evaluated against the same book's close; props BETS stay unbuilt until the evaluation reaches n >= 200.
- [x] WP-S3 SportsGameOdds parser validated against the examples in the provider's own documentation (found and fixed: statID filter, 'reg' period, signed American strings, `/account/usage` shape); still unverified against a live response.

Wave E:
- [x] WP11 Docs, ROADMAP and decisions updated; final verification and a production deploy.

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
- Wave D: 931 passed, 4 skipped on the combined branch; migration chain e3f8b1a4c9d2 -> b3d5f7a9c1e4 applied to a fresh copy of production; `totals_pace` and `props_nb` appear as shadow models, the league and the bets by market are unchanged. The `unmatched names` figure of the props audit on that copy (12,325) is just quotes seen minus quotes inserted by captures made before this release.
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

## Progress addendum (2026-10-30): the props storage did not work on real data
Two days after deploying WP-S2, production still showed `closing_props` captures with quotes_seen > 0 and quotes_inserted = 0; the tick log reported every quote as `invalid`. Root cause: `fetch_event_prop_quotes` read only the bookmaker-level `last_update` while the live API stamps the market (the game-lines parser already used `market.last_update or book.last_update`), so `book_last_update` was empty and the ingestion dropped every quote. The unit tests and the agent's fixtures all put the stamp on the bookmaker, which is why 931 tests were green. Fixed with a one-line change plus a regression test whose payload carries the stamp only on the market. Lesson: fixtures must come from real payloads; the first production capture after a deploy is part of the verification.

## Progress addendum (2026-10-31): injuries, lineups, SGO capture and the Gemini model
Owner decisions: automated NBA injury report downloads allowed (game days only, at most 3 per day, personal research); SportsGameOdds used for a daily capture plus a later staged historical backfill; `gemini-3.6-flash` replaced by `gemini-3.8-flash` (3.6 as fallback).
- Verified live before building: SportsGameOdds does NOT return player injury status on the free plan (players carry only name, team, id); its documentation does. Historical data from 2024 is available on the free plan with final scores, per-player stats and the last odds of 4-6 books, but open/close odds fields come back empty.
- Verified on the real report: the NBA PDF text must be extracted in layout mode; the new parser reads a real report as 95 rows, the same as an independent count of data lines, and the staging copy stored them with 83 of 95 players matched.
- Verified live on a staging copy of production: the `sgo` tick step captured 8 events for 8 objects and stored 1,724 quotes (main markets and props for about 55 players per market, nine books) plus 24 consensus rows kept outside `odds_history`.
- Tests: 970 passed, 4 skipped on the integrated branch; migrations `c5e7a9b1d3f6` and `d6f8b0c2e4a7` applied to a fresh copy of production.
- Still to do: the injury-aware shadow model and the weekly view (need a few days of stored injury reports), the SportsGameOdds historical backfill and its evaluation against the consensus.

