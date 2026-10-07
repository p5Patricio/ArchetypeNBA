# Feature: quant-paper-trading

## Objective
Build the persistence layer for a quantitative NBA betting module (odds history, model predictions, simulated bets with CLV) and make the odds ingestion trustworthy, using only free data sources.

## Problem
- No `game`, odds history, prediction, or simulated-bet tables exist; paper trading and CLV cannot be measured.
- `OddsApiService` returns hardcoded "consensus" lines when no live data exists, overwrites quotes across bookmakers (no attribution), and defaults missing under prices to -110.
- `props_engine` computes edge against vigged implied probability and only evaluates the over side.

## Why
Paper-trading metrics (ROI, CLV) are meaningless if quotes are fabricated or unattributed.

## Scope
- Research free odds sources (APIs with free tiers, scraping viability). Read-only.
- SQLModel models + Alembic migration for: sportsbook, game, odds_history, model_version, model_prediction, simulated_bet, plus views v_closing_odds and v_paper_performance.
- Fix the three OddsApiService problems.

## Constraints
- No paid services. Free tiers only (The Odds API Starter: 500 credits/month).
- Target DB: PostgreSQL 15 (backend/docker-compose.yml). Tests run on in-memory SQLite via SQLModel.metadata.create_all.
- Do not touch legacy didactic modules.
- User WIP (props cache, on-demand analysis, shutdown) committed on `feat/props-on-demand-and-shutdown` (342be52, 64e49da, 9a80e2f); this branch is rebased on top of it. props.py is now editable.
- Artifacts in English.

## TDD
- Mode: off. Source: no project/session TDD configuration found (no sdd-init, no TDD flag). Runner: `pytest` (run from `backend/`).

## Delivery
- Strategy: ask-on-risk (default). Forecast: ~700 authored changed lines (T2 ~450, T3 ~250) → exceeds ~400; chain strategy: stacked-to-main (user choice). Slice 1 = T2 (migration), slice 2 = T3 (OddsApiService).
- Branch: feat/quant-paper-trading, rebased onto feat/props-on-demand-and-shutdown. Rebased hashes: schema a05e4b6, odds fix 6fc4acc, docs 0a610e0.
- PR chain (stacked-to-main): A props-on-demand-and-shutdown -> main; B schema; C odds integrity; D props/ingestion follow-ups.
- RDD: on (default). Assess each work-unit commit.

## Tasks
- [x] T1 Research free odds sources and scraping viability — route: delegated (broad external research). Result: The Odds API Starter as primary (historical is paid-only; Pinnacle only in `eu`, reachable via `bookmakers=` param); SportsGameOdds Amateur (free, 2,500 events/mo, props, 9 US books, no Pinnacle) as second feed; closing lines must be self-captured; no free historical props. Do not scrape ESPN (Disney ToU bans automated extraction) or OddsPortal (ToS + Cloudflare). Engram: research/free-nba-odds-sources.
- [x] T2 SQLModel models + Alembic migration `9c3e5a7d1f42_add_quant_paper_trading` for quant tables and views — route: delegated writer (2+ non-trivial files). Checks: `pytest -q` 71 passed (writer), `tests/test_quant_models.py` 10 passed (parent spot check); `alembic upgrade 4125a71b06bf:head --sql` renders 4 CREATE TYPE, 2 NULLS NOT DISTINCT, 3 GENERATED, BRIN, 2 views; downgrade --sql drops views, tables, types. Live Postgres upgrade: pending (Docker not running). Added CHECK closing_price > 0 to avoid division by zero.
- [x] T3 Fix OddsApiService: remove fabricated fallback, keep per-bookmaker attribution, no -110 default; de-vig + both sides in props_engine — route: delegated writer (2+ non-trivial files). Done: `OddsQuote` + `fetch_event_prop_quotes` keep every book's quote; `select_best_lines` picks a same-book two-sided pair at the modal line (best over price, tie by book key); `get_slate_props_map` returns {} when not live (`last_fetch_live`); `under_odds` Optional; `devig_two_way` + per-side EV; daily_runner skips players without a live line. Checks: `pytest -q` 85 passed (writer and parent spot check); rg for fabricated defaults in app/ and daily_runner.py: no matches.

- [x] T4 Commit user WIP as work units on its own branch — route: inline (git). Commits 342be52 (ignore cache), 64e49da (props on demand), 9a80e2f (shutdown). Checks: backend `pytest -q` 61 passed, frontend `npx tsc --noEmit` exit 0.
- [x] T5 props.py: drop fabricated 22.5 fallback, odds label from `last_fetch_live`, expose side/under_odds/prob_under/bookmaker/devigged in API, Telegram text and props page; remove `PropBetLine.over_odds` -110 default — route: delegated writer. Commit f7b002e. Also fixed nonexistent `TelegramService.send_message` call and frontend recommendation/percent bugs. Checks: pytest 91 passed; tsc exit 0; eslint on touched files 0 errors.
- [x] T6 Integer-line push handling in props_engine + missing tests (skipped quotes, exception path, daily_runner skip) — route: delegated writer (same writer as T5, separate commit). Commit 99694cd. EV = p_win*d - 1 + p_push; half-point lines unchanged (regression test). Checks: pytest 104 passed.
- [x] T7 Odds ingestion into odds_history: game lines (/odds h2h,spreads,totals incl. Pinnacle via bookmakers=) and props quotes, idempotent, opening/closing snapshot script within 500 credits/month — route: delegated writer. Commits a4b2018 (ingestion + accent-insensitive name matching), fd839bf (CLI + Windows task registration script, not registered), bfd1457 (closing default 1 props event: ~420 credits/month), 8cd8834 (silence httpx URL logs that leaked apiKey into local logs; local logs redacted; untracked .codex-run-logs). Live run: opening snapshot 2026-10-06 → 46 games, 774 quotes (258 per market, 72 Pinnacle), quota 500→497. Checks: pytest 157 passed.
- [x] T8 Live Postgres: docker compose up, `alembic upgrade head`, verify tables/views — route: inline (bounded action). Real DB is native PostgreSQL 18.4 (config.py loads .env with override=True, so a shell DATABASE_URL does not redirect; Docker compose db unused and stopped). Upgrade/downgrade/upgrade ran on the real DB (additive, data intact: 6602 players, 670272 game logs). Rolled-back transaction confirmed generated price_decimal, v_closing_odds picks latest pre-tip quote, CHECK rejects price 50, NULLS NOT DISTINCT dedupe.
- [ ] T9 Push branches and open stacked PRs with gh — route: inline (git/gh)

## Acceptance criteria
- T2: `alembic upgrade head --sql` renders valid PostgreSQL DDL; downgrade drops everything it created; `pytest` passes; models create on SQLite.
- T3: no hardcoded lines returned by the service; each quote carries its bookmaker key; missing side stays missing; edge uses no-vig probability; tests cover all three.

## Checks
- `cd backend && pytest -q`
- `cd backend && alembic upgrade head --sql` (offline; Docker/Postgres not running locally)

## Progress
- Branch created. T1, T2, T3 done.
- T2 commit 25024cd. RDD: medium, slice_budget_reached; user declined review for this candidate.
- T3 commit d6cbbd4. RDD: high (process_boundary in daily_runner.py); user declined review; off-path independent verifier: no confirmed defects, 20 targeted tests passed.

## Follow-ups (out of scope)
- Harden POST /api/v1/system/shutdown against cross-site requests (spawned as a separate task).
- Register Windows scheduled tasks via scripts/register_odds_snapshot_tasks.ps1 (not run; needs user OK).
- Second feed (SportsGameOdds free tier) not integrated.
- Excel legacy cleanup proposed in the initial report, not executed.
- `props.py` and `daily_runner.py` default to `PropBetLine(stat_type="PTS", line=22.5)` when no line exists — another fabricated line; fix after user commits props.py WIP.
- `props_engine.load_baselines_from_db` reads a SQLite file `nba_platform.db` while the app DB is PostgreSQL.

## Next step
T9: push and open stacked PRs. Then decide whether to register the scheduled snapshot tasks (persistent machine config, needs explicit user OK). User authorized commits, push and PRs (gh) on 2026-10-06.
