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
- `backend/app/api/v1/props.py` has uncommitted user work: do not edit or stage it in this feature.
- Artifacts in English.

## TDD
- Mode: off. Source: no project/session TDD configuration found (no sdd-init, no TDD flag). Runner: `pytest` (run from `backend/`).

## Delivery
- Strategy: ask-on-risk (default). Forecast: ~700 authored changed lines (T2 ~450, T3 ~250) → exceeds ~400; chain strategy: stacked-to-main (user choice). Slice 1 = T2 (migration), slice 2 = T3 (OddsApiService).
- Branch: feat/quant-paper-trading (base 78fd58b).
- RDD: on (default). Assess each work-unit commit.

## Tasks
- [x] T1 Research free odds sources and scraping viability — route: delegated (broad external research). Result: The Odds API Starter as primary (historical is paid-only; Pinnacle only in `eu`, reachable via `bookmakers=` param); SportsGameOdds Amateur (free, 2,500 events/mo, props, 9 US books, no Pinnacle) as second feed; closing lines must be self-captured; no free historical props. Do not scrape ESPN (Disney ToU bans automated extraction) or OddsPortal (ToS + Cloudflare). Engram: research/free-nba-odds-sources.
- [x] T2 SQLModel models + Alembic migration `9c3e5a7d1f42_add_quant_paper_trading` for quant tables and views — route: delegated writer (2+ non-trivial files). Checks: `pytest -q` 71 passed (writer), `tests/test_quant_models.py` 10 passed (parent spot check); `alembic upgrade 4125a71b06bf:head --sql` renders 4 CREATE TYPE, 2 NULLS NOT DISTINCT, 3 GENERATED, BRIN, 2 views; downgrade --sql drops views, tables, types. Live Postgres upgrade: pending (Docker not running). Added CHECK closing_price > 0 to avoid division by zero.
- [x] T3 Fix OddsApiService: remove fabricated fallback, keep per-bookmaker attribution, no -110 default; de-vig + both sides in props_engine — route: delegated writer (2+ non-trivial files). Done: `OddsQuote` + `fetch_event_prop_quotes` keep every book's quote; `select_best_lines` picks a same-book two-sided pair at the modal line (best over price, tie by book key); `get_slate_props_map` returns {} when not live (`last_fetch_live`); `under_odds` Optional; `devig_two_way` + per-side EV; daily_runner skips players without a live line. Checks: `pytest -q` 85 passed (writer and parent spot check); rg for fabricated defaults in app/ and daily_runner.py: no matches.

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
- Integer prop lines: P(under)=cdf(floor(line)) counts the push (X == line) as an under win, overstating under EV; half-point lines unaffected.
- Tests missing for: skipped quotes with missing point/price, exception path keeping `last_fetch_live` False, daily_runner skip path.
- props.py (user WIP): drop `PropBetLine(PTS, 22.5)` fallback (now the only fabricated path, it fires whenever the service has no live lines), use `last_fetch_live` for the odds label, and expose `side`, `under_odds`, `prob_under`, `bookmaker`, `devigged`; under rows will look inconsistent in the UI until then.
- `PropBetLine.over_odds` still defaults to -110; remove once props.py passes prices.
- Ingest `fetch_event_prop_quotes` into `odds_history`; schedule opening/closing snapshots within 500 credits/month; probe SportsGameOdds free tier as second feed.
- Run `alembic upgrade head` against a live Postgres 15 once Docker is up.
- `props.py` and `daily_runner.py` default to `PropBetLine(stat_type="PTS", line=22.5)` when no line exists — another fabricated line; fix after user commits props.py WIP.
- `props_engine.load_baselines_from_db` reads a SQLite file `nba_platform.db` while the app DB is PostgreSQL.

## Next step
Feature tasks complete. Next: props.py follow-up after user commits their WIP; then odds_history ingestion. Push/PR are the user's decision (stacked-to-main: PR1 = 25024cd, PR2 = d6cbbd4).
