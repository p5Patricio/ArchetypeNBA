# Feature: season-readiness

## Objective
Make unattended odds capture reliable and credit-safe before the 2026-27 NBA season opener (2026-10-20), because closing lines and opening lines are perishable and cannot be backfilled on free tiers.

## Problem
- Capture tasks are not registered; only one snapshot exists (2026-10-06), so no closing lines and no CLV.
- Closing-snapshot detection infers "already captured" from `odds_history.captured_at`. A closing run where no book changed its price inserts 0 rows, so the next run can re-spend 3 credits on the same game; a manual opening run near tip-off can suppress that game's closing capture; props events beyond N in a cluster are never captured.
- The closing schedule (17:00-23:30 local) misses weekend afternoon games.

## Scope
- Explicit capture marker table (`odds_snapshot_capture`) + migration + service changes + tests.
- Registration script: closing coverage from 10:30 local.
- Apply migration to the local DB, register the scheduled tasks, verify with one live run.

## Constraints
- Free tier only: The Odds API Starter, 500 credits/month, 497 left on 2026-10-16.
- Real DB is native PostgreSQL 18.4 (config.py loads backend/.env with override=True). Tests run on in-memory SQLite.
- Scheduled tasks run only while the user is logged on and the PC is awake (no wake timers configured).
- Merging PRs into main was denied by the permission classifier on 2026-10-16; merging is the user's decision. This branch is stacked on `feat/quant-paper-trading` (PR #6).
- Artifacts in English; registration script console text stays Spanish like the other scripts.

## TDD
- Mode: off. Source: no project/session TDD configuration. Runner: `python -m pytest -q` from `backend/`.

## Delivery
- Strategy: ask-on-risk; chain strategy stacked-to-main (cached). Forecast ~400 changed lines. PR #7 stacked on #6.
- RDD: on (default); assess each work-unit commit.

## Tasks
- [ ] S1 Merge PRs #1-#6 into main — BLOCKED: denied by permission classifier; waiting for the user.
- [x] S2 Capture marker table, migration, service logic, tests — route: delegated writer. Commit 2f66f98: `odds_snapshot_capture` (kinds opening/closing/closing_props, partial unique index), success-only markers via `OddsApiService.last_call_ok`, props-only runs spend only props credits. Checks: pytest 168 passed; offline alembic up/down render. Worst case ~18 credits/day (~504/month) if every game spans two runs; guard floor 25 protects the quota.
- [x] S3 Registration script: closing from 10:30 local — route: delegated writer (same writer, separate commit). Commit 2575ea0.
- [x] S4 Apply migration to the local DB, register tasks, run one live verification — route: inline (bounded actions). Migration b7d41e9a2c85 applied to the real DB. Tasks NBA-Odds-Opening (11:00) and NBA-Odds-Closing (10:30-23:30 every 30 min) registered, state Ready. Live opening run: 804 quotes, 46 markers, quota 497→494. Found and fixed: PowerShell wrapped Python's stderr (exit code 1, UTF-16 log); logging now goes to stdout and the task writes UTF-8 and returns the real exit code. Closing task test run: exit 0, nothing_due, 0 credits.
- [ ] S5 Push and open PR #7 stacked on #6 — route: inline

## Acceptance criteria
- A closing run is recorded per game even when 0 quotes were inserted; the next run does not spend credits for that game.
- A manual opening run never suppresses a closing capture.
- Props capture is tracked separately so games beyond N in a cluster are picked in later runs while still inside the window.
- `NBA-Odds-Opening` and `NBA-Odds-Closing` registered and `Ready`; one live run logs to `logs/odds_snapshot.log` without leaking the API key.

## Checks
- `cd backend && python -m pytest -q`
- `alembic upgrade head` on the local DB, `alembic downgrade -1` / `upgrade head` round trip
- `Get-ScheduledTask NBA-Odds-*`

## Progress
- Branch feat/season-readiness created from feat/quant-paper-trading.
- RDD: S2/S3 slice medium; user declined review.
- Tasks run the code in the working tree: keep this checkout on a branch containing PR #6 and #7 (or main once merged); switching to an older branch breaks the scheduled captures.

## Follow-ups (out of scope)
- Prediction recorder: persist model_prediction / simulated_bet at analysis time (perishable, cannot be backfilled).
- Settlement job: fill game scores, bet results, closing price and CLV from player_game_log / v_closing_odds.
- Baseline game-line model (Elo vs de-vigged Pinnacle) since game lines are the cheapest data under the free quota.
- Champion/challenger retraining with promotion gates.
- Shutdown endpoint CSRF hardening (separate spawned task).

## Next step
S5: push and open PR #7. S1 (merging #1-#6) waits for the user. Then the prediction recorder before opening night (2026-10-20).
