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
- [ ] T3 Fix OddsApiService: remove fabricated fallback, keep per-bookmaker attribution, no -110 default; de-vig + both sides in props_engine — route: delegated writer (2+ non-trivial files)

## Acceptance criteria
- T2: `alembic upgrade head --sql` renders valid PostgreSQL DDL; downgrade drops everything it created; `pytest` passes; models create on SQLite.
- T3: no hardcoded lines returned by the service; each quote carries its bookmaker key; missing side stays missing; edge uses no-vig probability; tests cover all three.

## Checks
- `cd backend && pytest -q`
- `cd backend && alembic upgrade head --sql` (offline; Docker/Postgres not running locally)

## Progress
- Branch created. T1 and T2 done.

## Follow-ups (out of scope)
- `props.py` and `daily_runner.py` default to `PropBetLine(stat_type="PTS", line=22.5)` when no line exists — another fabricated line; fix after user commits props.py WIP.
- `props_engine.load_baselines_from_db` reads a SQLite file `nba_platform.db` while the app DB is PostgreSQL.

## Next step
Commit T2, assess RDD, then run T3.
