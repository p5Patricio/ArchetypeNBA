# Architecture

How ArchetypeNBA is put together today: the analytics web platform, and the quantitative paper-trading system that runs next to it on a schedule. Everything here was checked against the code on 2026-10-26; when a number decays (credits, table sizes) the date is stated. For the method behind the maths read [`QUANT_MODULE.md`](QUANT_MODULE.md); for running it read [`OPERATIONS.md`](OPERATIONS.md).

## Quick path

1. One-screen picture: [section 1](#1-system-at-a-glance).
2. What happens every 15 minutes: [section 2](#2-the-tick-pipeline).
3. Where data lives: [section 3](#3-data-model).
4. Which file does what: [section 4](#4-module-map).
5. Settings that change behavior: [section 7](#7-configuration).

## 1. System at a glance

Two products share one repository and one PostgreSQL database.

| Product | What it is | Runs as | Touches |
|---------|-----------|---------|---------|
| Analytics platform | Archetypes, shot zones, matchups, lineups, player props with Monte Carlo | FastAPI (`backend/app/main.py`) + Next.js (`frontend/`) | Platform tables; The Odds API, Gemini, Telegram on demand (props only) |
| Quant research system | Captures odds, predicts games, paper-trades, settles, measures CLV, compares models in shadow, promotes only on statistical evidence | A scheduled `backend/scripts/run_tick.py` plus operator CLIs | Quant tables and `player_game_log`; The Odds API and `nba_api` |

The two products do not call each other. **No HTTP endpoint exposes the quant tables**; the quant system is operated through scripts and read through `paper_report.py` and `model_league.py`.

### Components

| Component | Responsibility | Where |
|-----------|---------------|-------|
| Tick | One stateless pass: capture odds, ingest results, settle, learn, predict | `backend/app/services/tick.py`, `backend/scripts/run_tick.py` |
| Scheduler | Starts the tick every 15 minutes | Windows Task `NBA-Odds-Tick` (`scripts/register_tick_task.ps1`); cron/systemd elsewhere ([`OPERATIONS.md`](OPERATIONS.md)) |
| Odds capture | Quotes from 7 bookmakers into `odds_history`, with capture markers | `odds_api_service.py`, `odds_ingestion.py`, `odds_snapshot.py` |
| Results | Final scores from `nba_api`, then incremental Elo | `results_sync.py`, `elo_service.py` |
| Models | Champion Elo, shadow challengers, registry | `analytics/elo.py`, `analytics/features.py`, `margin_features_model.py`, `model_registry.py` |
| Recorder and policy | Predictions for every active model, paper bets from the champion only | `prediction_recorder.py`, `analytics/betting_policy.py` |
| Settlement | Grades bets, fills closing-line value (CLV) | `settlement.py`, `market_close.py` |
| Learning loop | Paired evaluation, promotion/retirement/rollback, weekly candidate lab | `model_evaluation.py`, `model_promotion.py`, `model_lab.py` |
| Reports | What a human reads | `paper_report.py`, `league_report.py`, `scripts/paper_report.py`, `scripts/model_league.py` |
| Web API | Platform endpoints | `backend/app/api/v1/*` |
| Frontend | Platform UI | `frontend/src` |

### Process boundaries

| Process | Started by | Lifetime | Network |
|---------|-----------|----------|---------|
| Tick | Scheduler, every 15 min, only while the user session is open (Windows) | Seconds to minutes; the task is killed at 10 min; the learn step stops itself at 4 min | The Odds API, `nba_api` |
| Operator CLIs (`paper_report`, `model_league`, `model_lab`, `backfill_elo`, `record_predictions`, `capture_odds_snapshot`) | A person | On demand | Only `capture_odds_snapshot` (paid) and nothing else |
| Backend API | `scripts/start_services.ps1` -> `scripts/run_backend.bat` (uvicorn, 127.0.0.1:38921) | Long-running | Props endpoints call The Odds API and Gemini on demand |
| Frontend | `scripts/run_frontend.bat` (`next start`, 127.0.0.1:38920) | Long-running | The backend only |

What the schedule decides versus what a human decides:

| On the schedule (automatic) | On demand (human) |
|-----------------------------|-------------------|
| Odds capture, results, settlement, CLV | Registering a challenger outside the weekly cadence (`model_lab.py --register`) |
| Challenger evaluation, promotion, retirement, rollback (unless `LEARNING_AUTOPROMOTE=false`) | Manual `promote` / `retire` with a reason |
| Weekly candidate proposal | Dry-run `propose`, `evaluate`, `status` |
| Prediction and paper-bet recording | Schema migrations, database backup and restore |

## 2. The tick pipeline

```mermaid
flowchart TD
    S["Scheduler: every 15 min"] --> R["run_tick.py"]
    R --> LK{"tick.lock free?"}
    LK -- "no (held, younger than 20 min)" --> X["exit 0: nothing done"]
    LK -- yes --> MC["count missed closing lines (last 12 h)"]
    MC --> O["1 opening: once per local day, whole slate, 3 credits"]
    O --> C["2 closing: games tipping off within 30 min, 3-4 credits"]
    C --> RS["3 results: nba_api, final scores, Elo update, settle bets, fill CLV"]
    RS --> L["4 learn: evaluate challengers, weekly proposal, 4 min budget"]
    L --> RC["5 record: predictions for all active models, bets from the champion"]
    RC --> OUT["summary to logs/tick.log, exit 0 or 1"]
```

Each step runs inside its own error boundary: an exception becomes an `error` result and the next step still runs. The tick keeps no state of its own; every decision is read from the database markers, so a missed tick costs nothing and a repeated tick spends nothing.

| Step | Runs when | Cost | Writes |
|------|-----------|------|--------|
| `opening` | No `opening` marker exists for today's machine-local date and at least one event is upcoming | 3 credits (`/events` is free) | `game`, `odds_history`, `odds_snapshot_capture` (kind `opening`) |
| `closing` | An upcoming event tips off within `--window-minutes` (30) and has no `closing` marker; one props event per run without a `closing_props` marker | 3 credits for game lines plus 1 per props event | same tables; kinds `closing`, `closing_props` |
| `results` | Always runs; it calls the network only if a `scheduled` game tipped off more than 3 h ago (normally one call; two around a season boundary because it fetches per season label), and otherwise only settles bets and fills CLV from what is already in the database | 0 credits; one free `nba_api` call at most | `player_game_log`, `game` (scores, `final`), `team_elo_rating`, `simulated_bet` (status, profit, closing fields) |
| `learn` | Always; evaluation is DB only, the proposal at most every `LEARNING_PROPOSAL_DAYS` (7) days (1 day after a failed lab) | 0 credits | `model_evaluation`, `model_version` (roles), new challenger rows and their Elo ratings |
| `record` | Always (DB only, so it also runs when capture or results failed) | 0 credits | `model_prediction`, `simulated_bet` |

Safety rules in the runner:

| Rule | Detail |
|------|--------|
| Lock | `logs/tick.lock` holds pid and start time; created atomically; a lock older than 20 min is stale and replaced; released in `finally` |
| Credit guard | A paid call is refused if the credits left after it would be below `--min-remaining` (25); an unknown quota also refuses |
| Success-only markers | A capture marker is written only after an HTTP 200 paid call, so a failed call is retried by the next tick |
| Exit code | 0 when no step failed (also when another tick holds the lock); 1 when at least one step errored. A deliberately skipped step (guard, nothing due) is not an error |
| Dry run | `--dry-run` takes no lock, never touches the network or the odds service, writes nothing and no log file, and prints worst-case credits |

### Data flow

```mermaid
flowchart LR
    ODDS["The Odds API"] --> OH["odds_history"]
    ODDS --> CAP["odds_snapshot_capture"]
    NBA["nba_api"] --> PGL["player_game_log"]
    NBA --> GAME["game: scores, final"]
    PGL --> ELO["team_elo_rating"]
    PGL --> FEAT["feature state"]
    ELO --> REG["model registry"]
    FEAT --> REG
    REG --> PRED["model_prediction"]
    OH --> REC["prediction_recorder"]
    CAP --> REC
    PRED --> REC
    REC --> BET["simulated_bet"]
    GAME --> SET["settlement and CLV"]
    BET --> SET
    OH --> SET
    CAP --> SET
    PRED --> EVAL["paired evaluation"]
    GAME --> EVAL
    OH --> EVAL
    EVAL --> AUD["model_evaluation"]
    EVAL --> ROLE["model_version roles"]
```

## 3. Data model

PostgreSQL 15 or newer is required (`NULLS NOT DISTINCT`). The unit tests run on in-memory SQLite and emulate the PostgreSQL-only features.

```mermaid
erDiagram
    season ||--o{ game : has
    team ||--o{ game : "home or away"
    game ||--o{ odds_history : quoted
    sportsbook ||--o{ odds_history : offers
    game ||--o{ odds_snapshot_capture : "marked by"
    model_version ||--o{ model_prediction : makes
    game ||--o{ model_prediction : about
    model_prediction ||--o{ simulated_bet : "bet on"
    odds_history ||--o{ simulated_bet : "price taken, closing price"
    model_version ||--o{ team_elo_rating : "own ratings"
    team ||--o{ team_elo_rating : rated
    model_version ||--o{ model_evaluation : "champion or challenger"
    model_version ||--o| model_version : parent
    game {
        bigint id PK
        text nba_game_id UK
        text provider_event_id UK
        timestamptz commence_time
        text status
        smallint home_score
        smallint away_score
    }
    odds_history {
        bigint id PK
        bigint game_id FK
        smallint sportsbook_id FK
        enum market
        enum side
        numeric line
        int price_american
        numeric price_decimal "generated"
        timestamptz book_last_update
        timestamptz captured_at
    }
    model_version {
        int id PK
        text name
        text version
        jsonb params
        text role "champion, challenger, retired"
    }
    model_prediction {
        bigint id PK
        int model_version_id FK
        bigint game_id FK
        numeric model_prob
        numeric fair_decimal "generated"
        numeric projection
    }
    simulated_bet {
        bigint id PK
        bigint prediction_id FK
        numeric price_taken
        enum strategy
        numeric stake_units
        numeric clv_pct "generated"
        enum status
    }
```

### Quant tables: the columns and constraints that matter

| Table | Purpose | Key columns | Constraints worth knowing |
|-------|---------|-------------|---------------------------|
| `sportsbook` | Bookmakers | `key` (provider key), `region` (`us` or `eu`), `is_sharp` | `key` unique; only `pinnacle` is sharp |
| `game` | One NBA game as the odds feed sees it | `nba_game_id` (joins `player_game_log.game_id`), `provider_event_id` (The Odds API id), `season_id`, `home_team_id`, `away_team_id`, `commence_time`, `status`, scores | Both ids unique; `home_team_id <> away_team_id`; `status` in `scheduled, live, final, postponed` |
| `odds_history` | Append-only quotes, one row per (book, market, side, line, book update) | `market` and `side` are native enums; `player_id` and `line` are NULL for game markets; `price_american`; `price_decimal` | `price_american <= -100 or >= 100`; unique key `uq_odds_history_quote` over `(game_id, sportsbook_id, market, player_id, side, line, book_last_update)` with `NULLS NOT DISTINCT`; BRIN index on `captured_at`; `price_decimal` is a generated column |
| `odds_snapshot_capture` | Explicit "this game was captured" markers | `kind` in `opening, closing, closing_props`, `credits_spent`, `quotes_seen`, `quotes_inserted` | Partial unique index on `(game_id, kind)` for `closing` and `closing_props` only; `opening` may repeat |
| `model_version` | Registry | `name` = model family, `version`, `params` (JSONB: everything inference needs), `brier_oos`, `role`, `promoted_at`, `retired_at`, `parent_id`, `notes` | `(name, version)` unique; `role` check; **partial unique index allows one champion at most** |
| `team_elo_rating` | Per-model Elo timeline | `model_version_id` (NOT NULL), `team_id`, `season_id`, `game_id`, `rating_before`, `rating_after`, `win_probability` | Unique `(model_version_id, team_id, season_id, game_id)` |
| `model_prediction` | Every probability a model published before tip-off | `market`, `side`, `line`, `model_prob`, `projection` (expected home margin), `predicted_at` | `0 < model_prob < 1`; unique per `(model_version_id, game_id, market, player_id, side, line)` with `NULLS NOT DISTINCT`; `fair_decimal = 1 / model_prob` generated |
| `simulated_bet` | Paper bets | `prediction_id`, `odds_taken_id`, `price_taken`, `line_taken`, `fair_prob_at_bet`, `ev_per_unit`, `strategy`, `stake_units`, `bankroll_before`, `closing_*`, `status`, `profit_units`, `placed_at`, `settled_at` | `stake_units > 0`; `closing_price` NULL or `> 0`; `status = 'pending'` or `settled_at` set; unique `(prediction_id, strategy)`; `clv_pct = price_taken / closing_price - 1` generated; partial index on pending |
| `model_evaluation` | Audit trail of every evaluation and proposal | `champion_id`, `challenger_id`, `n_games`, `n_market_games`, `metrics` (JSONB: every number and the bootstrap seed), `decision`, `reason` | `decision` in `insufficient_data, keep, promote, retire, rollback, proposal, dry_run` |

Reason prefixes carry meaning: `monitor:` (a look that could not act), `manual:` (a human override), `error:` (a failed lab run that holds the weekly cadence).

### Views

Both exist only in migration `9c3e5a7d1f42` (PostgreSQL), so run `alembic upgrade head` rather than `create_all` on a real database.

| View | Definition |
|------|-----------|
| `v_closing_odds` | Latest quote per (game, book, market, player, side, line) captured at or before tip-off |
| `v_paper_performance` | Per strategy: settled bets, win rate, P/L, ROI on settled stake, average CLV, share of bets that beat the close |

The Python reports recompute these numbers themselves so they work on SQLite too.

### Platform tables

`season`, `team`, `player`, `player_season_stats`, `team_season_stats`, `player_game_log`, `player_shot`, `player_advanced_stats`, `player_similarity`, `player_contract`, `player_matchup_stats`. The quant system reads `team`, `season` and above all **`player_game_log`**, the single source of truth for results (a team's score is the sum of its players' `pts`).

Table count: the models define 20 tables (11 platform, 9 quant: `sportsbook`, `game`, `odds_history`, `odds_snapshot_capture`, `team_elo_rating`, `model_version`, `model_prediction`, `simulated_bet`, `model_evaluation`); a live database also holds `alembic_version`.

### Migration chain

`001` -> `ad04e02dc85c` (game logs, shots, advanced stats, similarity, Elo table) -> `4125a71b06bf` (contracts, matchups) -> `9c3e5a7d1f42` (quant schema and views) -> `b7d41e9a2c85` (capture markers) -> `c4e8a1d63f27` (unique bet per prediction and strategy) -> `d7a2f5b81c39` (roles, `model_evaluation`, per-model Elo; **head**). The migrations are hand-written for PostgreSQL; `alembic current` must print the head after every deploy.

## 4. Module map

### `backend/app/analytics` (pure functions, no I/O)

| File | One line |
|------|----------|
| `elo.py` | FiveThirtyEight-style Elo: update, margin-of-victory multiplier, season carryover, expected margin, `spread_probabilities` (win/push/loss), `EloParams` |
| `features.py` | `FeatureState` and `build_feature_set`: the 12 leak-free features used for training and for serving |
| `betting_policy.py` | Blend, EV with pushes, Kelly with pushes, stake caps, `evaluate_candidate` |
| `props_engine.py` | Shared odds maths (`american_to_decimal`, `devig_two_way`, `normalize_player_key`) and the Monte Carlo player-props engine behind `/props` |

### `backend/app/services` (quant system)

| File | One line |
|------|----------|
| `odds_api_service.py` | The Odds API client: free `/events`, game lines (3 credits), event props (1 credit per market), quota headers, best-line selection for props |
| `odds_ingestion.py` | Quotes into `sportsbook`, `game`, `odds_history`; idempotent; accent-insensitive names; season resolution that never flips `is_active` |
| `odds_snapshot.py` | Opening and closing capture logic, plan and cost, credit guard, capture markers |
| `tick.py` | The five-step orchestrator, lock file, summaries, missed-closing count |
| `results_sync.py` | `nba_api` player logs for a date window into `player_game_log`, finalize games, trigger Elo |
| `elo_service.py` | Builds games from `player_game_log`, replays Elo, persists ratings per model, walk-forward evaluation, registers `elo_538` 1.1 |
| `model_registry.py` | Roles, champion lookup, Elo reference and its protection, family registry (`elo_538`) |
| `margin_features_model.py` | Ridge + logistic training, numpy-only inference, the `margin_features` family |
| `prediction_recorder.py` | Predictions for every active model; paper bets from the champion only |
| `settlement.py` | Grades h2h and spread bets, profit, closing-line value |
| `market_close.py` | Pinnacle's de-vigged closing probability, shared by the report and the evaluation |
| `model_lab.py` | Historical candidate lab: time split, Elo random search, `margin_features`, historical gate, registration |
| `model_evaluation.py` | Paired live evaluation, bootstrap, look budget, the decision rule |
| `model_promotion.py` | Evaluation pass, atomic swap and retirement, manual overrides, proposals, league rows |
| `league_report.py` | Data and text of the "Model league" section |
| `paper_report.py` | Data and text of the paper-trading report |

Adjacent, not part of the loop: `injury_scraper.py` (broken, fabricates data: see [`ROADMAP.md`](ROADMAP.md) item 1), `gemini_analyzer.py` and `telegram_service.py` (props pipeline), and `db_transfer.py` (the export, verify and import logic behind `scripts/db_transfer.py`, see [`DB_TRANSFER.md`](DB_TRANSFER.md)).

Platform services (not documented here): `cache`, `clustering`, `data_update`, `doppelgangers`, `elo` (a legacy, unrelated `EloService`), `financial`, `historical`, `lineup`, `matchup_service`, `parallel_zones`, `pizza_chart`, `player`, `real_shotchart`, `report`, `similarity`, `team`, `training`, `versus`.

### Scripts

| Script | Purpose | Writes? |
|--------|---------|---------|
| `backend/scripts/run_tick.py` | One tick | Yes (not with `--dry-run`) |
| `backend/scripts/paper_report.py` | Paper-trading report, no flags | No |
| `backend/scripts/model_league.py` | `status`, `evaluate`, `propose`, `promote`, `retire` | Only `evaluate --apply`, `propose` without `--dry-run`, `promote`, `retire` |
| `backend/scripts/model_lab.py` | Historical lab report | Only with `--register` |
| `backend/scripts/backfill_elo.py` | Rebuild or update Elo, evaluate, register `elo_538` | Yes (not with `--dry-run`) |
| `backend/scripts/record_predictions.py` | Run the recorder by hand | Yes (not with `--dry-run`) |
| `backend/scripts/capture_odds_snapshot.py` | One manual opening or closing capture (spends credits) | Yes (not with `--dry-run`) |
| `backend/scripts/bulk_ingest_nba.py` | Historical `nba_api` ingestion, seasons 2003-04 to 2025-26, no flags | Yes |
| `backend/scripts/db_transfer.py` | `export`, `verify`, `import` and `manifest` for the whole database, with exact row-count checks ([`DB_TRANSFER.md`](DB_TRANSFER.md)) | `export` writes files outside the repository; `import` writes the target database |
| `backend/scripts/seed_database.py`, `test_live_training.py` | Legacy Excel seeding and a manual training check | Legacy |
| `scripts/register_tick_task.ps1` | Register, unregister or preview the Windows task | Machine config |
| `scripts/start_services.ps1`, `stop_services.ps1`, `setup_windows_autostart.ps1`, `delayed_stop.ps1` | Start and stop the web services | Processes |

### Tests

`backend/tests` (offline, deterministic, seeded). `tests/synthetic_league.py` generates fake leagues for the lab and the leak checks; tests marked `simulation` are Monte Carlo checks of the statistical rules (seconds, not milliseconds). 757 tests passed on 2026-10-26.

## 5. API surface touching the quant parts

| Endpoint | What it does | Quant relevance |
|----------|-------------|-----------------|
| `GET /api/v1/health` | Status and `db_connected` | Used by `start_services.ps1` to wait for readiness |
| `GET /api/v1/seasons` | Seasons; hides seasons that have no player stats unless they are active | Protects the frontend from the empty 2026-27 row |
| `GET /api/v1/props/today` | Cached Monte Carlo player props | Reads a 1 h in-memory cache, then the on-disk cache file (no age check); `refresh=true` recomputes |
| `POST /api/v1/props/run-analysis` | Recompute the props slate now | **Spends The Odds API credits** (up to 2 events x 3 markets = 6) and Gemini quota, outside the tick's credit guard |
| `POST /api/v1/system/shutdown` | Stops both web services through `scripts/delayed_stop.ps1` | Windows only; **no CSRF or origin guard** (see [`ROADMAP.md`](ROADMAP.md)) |

There is no endpoint for odds, predictions, bets, evaluations or the model league.

## 6. Frontend parts that touch it

| File | Role |
|------|------|
| `frontend/src/app/props/page.tsx` | Props table and the "run analysis" button |
| `frontend/src/lib/api.ts` | `getTodayProps`, `runPropsAnalysis`, `shutdownServices`; API base from `NEXT_PUBLIC_API_BASE` (default `http://localhost:8000`, inlined at build time) |
| `frontend/src/components/ShutdownModal.tsx`, `Navbar.tsx` | The shutdown button |

There is no model-league page yet ([`ROADMAP.md`](ROADMAP.md)).

## 7. Configuration

`backend/app/config.py` loads `backend/.env` and a repo-root `.env` with `load_dotenv(override=True)`: **the file wins over variables exported in the shell**, so exporting `DATABASE_URL` does not redirect the app or Alembic.

| Setting | Default | Controls |
|---------|---------|----------|
| `DATABASE_URL` | `postgresql://postgres:postgres@localhost:5432/nba_platform` | The database. The code rewrites `postgresql://` to `postgresql+psycopg://` (psycopg 3) in `app/deps.py` and `alembic/env.py` |
| `THE_ODDS_API_KEY` | empty | Enables capture and live props. Empty, or containing `your_`, counts as not configured |
| `LEARNING_AUTOPROMOTE` | `true` | Kill switch. Off: evaluations are recorded as `dry_run`, no role changes, no registration of proposed candidates |
| `LEARNING_MIN_GAMES` | 150 | Paired games needed to promote |
| `LEARNING_MIN_DAYS_LIVE` | 14 | Days a challenger must have been predicting |
| `LEARNING_COOLDOWN_DAYS` | 30 | Minimum days between promotions |
| `LEARNING_PROPOSAL_DAYS` | 7 | Cadence of the candidate lab |
| `LEARNING_MAX_CHALLENGERS` | 3 | Active challenger slots |
| `LEARNING_LOOK_INTERVAL_DAYS` | 7 | Days between decision-grade looks per challenger |
| `LEARNING_MAX_LOOKS` | 12 | Decision-grade looks per challenger-champion pairing |
| `LEARNING_MAX_AGE_DAYS` | 150 | Age after which a challenger without a pass is retired (needs 300 paired games) |
| `GEMINI_API_KEY`, `GEMINI_MODEL` | empty, `gemini-3.6-flash` | The props AI layer |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | empty | Optional props report to Telegram |
| `PROPS_SIMULATION_RUNS` | 10000 | Monte Carlo runs per prop |
| `REDIS_URL` | `redis://localhost:6379/0` | Optional cache; if Redis is absent the cache is silently disabled |
| `CORS_ORIGINS` | localhost and 127.0.0.1 on 38920, 38921, 3000, 8000, 8001 | Browser origins allowed by the API |
| `DEBUG` | `false` | SQLAlchemy `echo` |
| `ETL_BATCH_SIZE` | 100 | Defined but not referenced anywhere in the code |

Everything else that defines behavior (Elo constants, betting thresholds, the credit floor, tick windows) is a **module constant**, not a setting; the values are listed in [`QUANT_MODULE.md`](QUANT_MODULE.md). Changing them is a code change and, for betting policy or model parameters, a new `model_version`.

Time zone: the tick decides "today" (one opening per day, daily stake caps) with the **machine's local zone**. The project assumes `America/Mexico_City`.

## Next step

Operating the system: [`OPERATIONS.md`](OPERATIONS.md). Understanding the numbers: [`QUANT_MODULE.md`](QUANT_MODULE.md).
