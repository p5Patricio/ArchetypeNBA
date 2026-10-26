# AGENTS.md — ArchetypeNBA

Context for any AI coding agent (or human) picking this project up. **Snapshot date: 2026-10-26.** Numbers marked "as of" decay; re-measure before relying on them. Deep dives live in [`docs/`](docs/README.md); this file is the map and the rulebook.

## 1. TL;DR

| Item | Value |
|------|-------|
| What | Two products in one repo: (a) **ArchetypeNBA analytics platform** (FastAPI + Next.js: archetypes, shot zones, matchups, props, etc.); (b) a **quantitative betting research system** that predicts NBA games, *paper-trades* them (no real money, ever) and is built to **improve itself with evidence**. |
| Goal of (b) | A closed loop: capture odds → predict → paper-bet → settle → measure (CLV = price taken vs the **same book's** closing quote; model skill = Brier vs **Pinnacle's de-vigged close**) → compare candidate models in shadow → promote only when statistics say so. |
| Stack | Python 3.12, FastAPI, SQLModel/SQLAlchemy 2, Alembic, PostgreSQL 18 (tests: in-memory SQLite), NumPy/pandas/scikit-learn, `nba_api`, The Odds API; Next.js 16 / React 19 / Tailwind 4 frontend. |
| Repo | `github.com/p5Patricio/ArchetypeNBA` (`main` is the only long-lived branch; PRs #1–#17+ merged). |
| Production | One Windows 11 PC runs a scheduled task every 15 minutes (`NBA-Odds-Tick`). **That PC executes the `main` checkout**, so unmerged code must never live there. |
| State | Pipeline live since the 2026-10-20 opener. Baseline Elo champion + one shadow challenger. Too little data to judge anything yet (see §9). |
| Next task | Replace the broken injury scraper with a real free source of injuries/lineups and test it as a model signal (see §10). |

First five commands on a fresh machine (details in [`docs/SETUP.md`](docs/SETUP.md)):

```bash
cd backend && python -m pytest -q                         # 633+ tests, all offline, ~2 min
python scripts/run_tick.py --dry-run                      # what the scheduled tick would do (no network, no writes)
python scripts/paper_report.py                            # performance, CLV, model skill, model league
python scripts/model_league.py status                     # champion/challenger table
python -m alembic current                                 # must equal the head (d7a2f5b81c39 as of this snapshot)
```

## 2. Non-negotiable rules

1. **Paper trading only.** Never add code that places real bets, handles money or sportsbook accounts.
2. **Free tiers only.** No paid APIs/services without the user's explicit approval. The Odds API Starter gives 500 credits/month; guard it (`--min-remaining 25`).
3. **Never fabricate data.** Hardcoded "consensus" odds, default `-110` prices, sample injury reports etc. were all removed or must be removed; a missing value stays missing. A fallback that invents data is a bug.
4. **No visible windows from background jobs.** Scheduled/background Python must run with **`pythonw.exe`** directly. `powershell -WindowStyle Hidden` or `python.exe` flash a console and steal focus (it interrupted the user's meetings and games). Verify with a process watch, not by eye.
5. **Secrets and data stay out of git.** `backend/.env`, database dumps, `logs/`, the Odds API key (httpx INFO logs print it; they are silenced), Telegram/Gemini tokens. Dumps are `*.dump` + `*.manifest.json` and git-ignored.
6. **Tests are offline and deterministic.** No network, no real database, seeded randomness. SQLite in-memory for unit tests.
7. **Production checkout discipline.** The machine that runs the tick executes whatever is checked out in its main working tree. Develop in a separate `git worktree`, merge to `main`, then pull. Schema changes follow the lockstep deploy in §7.
8. **No silent policy/model changes.** Betting policy and model parameter changes are registered as a **new `model_version` row** so every bet stays attributable.
9. **Do not scrape sites whose terms forbid it.** Rejected: ESPN hidden API (Disney ToU), OddsPortal (ToS + Cloudflare). For anything new, read the terms first and ask the user when the terms are ambiguous (see the NBA injury report note in §10).
10. **Ask before irreversible or outward-facing actions** (merge, push, delete, register machine-level tasks, spend API credits beyond the routine tick). The user has given a *standing* authorization to open PRs and merge to `main` for this project's work (2026-10-17, earlier agent session). **Re-confirm it once at the start of your session**: permission is per session and Claude Code's auto-mode classifier blocks "merge without review" otherwise.

## 3. Working agreements with the user

- The user writes Spanish (Mexico, timezone `America/Mexico_City`). **Reply in the user's language; write all artifacts (code, comments, docs, commits, PRs) in English.**
- Short answers by default; one question at a time, then wait; verify technical claims before stating them; disagree with evidence when the user is wrong.
- **Conventional Commits, no AI attribution trailers** (no `Co-Authored-By`, no "generated with" in commits). The user's global config forbids it. PR bodies carry a short "Generated with Claude Code" footer by convention.
- Prefers modern CLI tools (`rg`, `fd`, `bat`, `sd`, `eza`) over `grep/find/cat/sed/ls`; they were not installed on the original PC (Windows), so use the dedicated file tools of your agent environment plus `rg` where available.
- The user does not want to be interrupted by background activity (see rule 4).
- They approve outcomes, not process: report verified results, failures and skipped checks plainly.

## 4. Repository map

```
backend/
  app/
    main.py, config.py, deps.py, models.py, schemas.py      # FastAPI app, Settings, DB session, all SQLModel tables
    api/v1/            # routers (players, props, system, seasons, ...)
    analytics/         # pure math: elo.py, features.py, betting_policy.py, props_engine.py
    services/          # business logic (see §5); tick.py orchestrates the pipeline
    repositories/, etl/
  alembic/versions/    # 001 → ad04e02dc85c → 4125a71b06bf → 9c3e5a7d1f42 → b7d41e9a2c85 → c4e8a1d63f27 → d7a2f5b81c39 (head)
  scripts/             # CLIs: run_tick, paper_report, model_league, model_lab, backfill_elo, record_predictions, capture_odds_snapshot, bulk_ingest_nba, ...
  tests/               # pytest suite (offline); tests/synthetic_league.py generates fake leagues
frontend/              # Next.js app (props page, shutdown modal, scouting modules); npm run dev | build | start
scripts/               # Windows ops: register_tick_task.ps1, start_services.ps1, stop_services.ps1, setup_windows_autostart.ps1
odd/tasks/             # one markdown plan per feature (ODD workflow, see §7) — the best history of WHY things are as they are
docs/                  # architecture, quant methodology, operations, setup, DB transfer, decisions, roadmap
logs/                  # git-ignored runtime logs (tick.log rotating 2 MB x3, tick.lock)
```

Legacy at the repo root (`api.py`, `nba_data_processor.py`, `nba_player_analyzer.py`, tracked `.xlsx` files, `backend/app/etl/pipeline.py` Excel ETL) predates the Postgres platform. A cleanup was proposed but **not executed and is riskier than it looks**: `backend/app/services/report.py` imports `nba_player_analyzer`, `backend/app/etl/pipeline.py` is used by `services/data_update.py` (not only `seed_database.py`), and copies of the legacy modules live both at the root and in `backend/`. Map the importers before deleting anything.

## 5. How the quant system works

```
every 15 min (Windows Task Scheduler, only while the user is logged on)
  pythonw.exe backend/scripts/run_tick.py
    1 opening   once per LOCAL day: GET /odds (h2h, spreads, totals; 7 books incl. Pinnacle) → odds_history        3 credits
    2 closing   games tipping off within 30 min: GET /odds (+1 props event) → odds_history + closing marker       3–4 credits
    3 results   games started >3 h ago: nba_api PlayerGameLogs → player_game_log → game final → Elo update → settle bets → CLV
    4 learn     evaluate challengers; weekly candidate proposal (4-minute budget)
    5 record    predictions for the champion AND shadow challengers; paper bets only from the champion
```

Each step is isolated (a failure never blocks `record`); a lock file prevents overlap; the tick is stateless and decides from DB markers (`odds_snapshot_capture`).

| Concern | Where | Key facts |
|---------|-------|-----------|
| Odds capture | `odds_api_service.py`, `odds_ingestion.py`, `odds_snapshot.py` | Per-bookmaker quotes (`odds_history`), `bookmakers=pinnacle,draftkings,fanduel,betmgm,williamhill_us,betrivers,bovada`; rows inserted only when `book_last_update` changes; markers `opening`/`closing`/`closing_props` per game. |
| Champion model | `analytics/elo.py`, `services/elo_service.py` (`EloRatingService`) | 538-style Elo: K=20, home advantage **60** (not 100: walk-forward bias), carryover 0.75 to 1505, MOV exponent 0.8, 28 Elo points per point, margin sigma 14.14. Registered as `model_version` `elo_538` 1.1 (id 1). The unrelated legacy `app.services.elo.EloService` is a different class. |
| Challenger | `analytics/features.py`, `services/margin_features_model.py` | `margin_features`: ridge (margin) + logistic (win) on 12 leak-free features; params are JSON in `model_version.params`; inference is numpy-only. Registered as `lab-20260613-51ff86` (id 2), shadow only. |
| Betting policy | `analytics/betting_policy.py`, `services/prediction_recorder.py` | Bet only if (p_model − p_fair_Pinnacle) ≥ 2 pp AND EV with blended p′ = 0.5·p_model + 0.5·p_fair ≥ 2% at the best price quoted at Pinnacle's line. Flat 1 u and ¼ Kelly (caps 2%/bet, 10%/day, 4%/game), one bet per strategy/game/market/side, horizon 20 h, quotes ≤ 6 h old, never at/after tip-off. Push is a refund on integer lines. |
| Settlement and CLV | `services/settlement.py`, `results_sync.py` | h2h and spreads only. CLV only for games with a `closing` marker, same book/market/side/line; otherwise NULL. |
| Evaluation | `services/model_evaluation.py`, `league_report.py`, `paper_report.py` | Paired per-game log loss (primary), Brier, margin NLL, Brier vs Pinnacle's de-vigged close; seeded paired bootstrap. |
| Promotion | `services/model_promotion.py`, `scripts/model_league.py` | Gates in §6. Audit trail in `model_evaluation`. Kill switch `LEARNING_AUTOPROMOTE`. |
| Candidate lab | `services/model_lab.py`, `scripts/model_lab.py` | Time-split: select on seasons [T-9, T-2], hold-out [T-1, T]; Elo random search (40 configs, seed) + `margin_features`; historical gate: hold-out log-loss gain ≥ 0.0005 and materially different. |

Database (20 model tables + `alembic_version`; PostgreSQL): platform tables (`season`, `team`, `player`, `player_season_stats`, `team_season_stats`, `player_game_log`, `player_shot`, `player_advanced_stats`, `player_similarity`, `player_contract`, `player_matchup_stats`) and quant tables (`sportsbook`, `game`, `odds_history`, `odds_snapshot_capture`, `team_elo_rating` (per model), `model_version`, `model_prediction`, `simulated_bet`, `model_evaluation`) plus views `v_closing_odds`, `v_paper_performance`.

## 6. Decisions that shaped the system (why, not just what)

| Decision | Why | Where to read more |
|----------|-----|--------------------|
| Game lines first (h2h/spreads), props later | Cheapest data under a 500-credit quota: one call covers every game | `odd/tasks/season-readiness.md` |
| Pinnacle as the sharp reference, de-vigged | Its close is the best free estimate of the true probability | `docs/QUANT_MODULE.md` |
| Judge by CLV and Brier vs the close, not ROI | ROI needs thousands of bets; CLV/Brier converge faster | `docs/QUANT_MODULE.md` |
| Elo home advantage 60, not 100 | At 100 the home side was overrated 1.2–1.9 points over the last 5 seasons (tuned in-sample on 2021-22..2025-26: reported Brier slightly optimistic) | `odd/tasks/elo-prediction-recorder.md` |
| Policy deliberately "aggressive" on opening week | Elo cannot see offseason moves; more bets = faster verdict on whether the baseline has any edge. Judged by CLV | same |
| Challengers record predictions only | No shadow bets, so bankrolls are never mixed; compare by proper scoring rules | `odd/tasks/model-learning-loop.md` |
| Look budget for promotions | Re-testing a challenger daily promoted equal models ~20% of the time; weekly decision-grade looks at confidence 1 − 0.05/(k·12) gave ~1% (simulated) | same |
| Promotion gates | n ≥ 150 paired games, ≥ 14 days live, 30-day cooldown, one-sided bound > 0 on log-loss gain, margin NLL not worse, market-Brier gap within 0.005; retire if significantly worse (n ≥ 100) or 150 days with n ≥ 300; the last Elo model is protected; the previous champion is judged only on games since its demotion | same |
| Dedicated DB marker table for captures | Inferring "already captured" from `odds_history` re-spent credits when prices did not move | `odd/tasks/season-readiness.md` |
| `pythonw.exe` for scheduled work | Console flash stole focus (rule 4) | PR #16 |
| Worktrees for development | The tick runs the main checkout | §7 |
| nba_api for results (free, keyless) | One call per tick only when games are unresolved | `odd/tasks/elo-prediction-recorder.md` |

Rejected/not done: paid odds feeds (OpticOdds ~$5k/mo), scraping ESPN/OddsPortal, Docker Postgres (port 5432 conflicts with the native instance), shadow bets for challengers, totals/props settlement (not implemented), CI (none configured), Excel cleanup.

## 7. Workflow conventions

- **Branches and PRs.** Branch from `origin/main`; Conventional Commits; one PR per cohesive work unit with a *Chain Context* section (position, base, depends on, follow-up, review budget). PRs over 400 changed lines are marked `size:exception` with the reason (tests count). Merge with merge commits (not squash) so stacked history stays clean; each PR is merged to `main` before the next one starts. No CI exists: run `python -m pytest -q` yourself and say so in the PR.
- **ODD (organic driven development).** For substantial work create `odd/tasks/<feature>.md` *before the first source write* (objective, problem, decisions, constraints, tasks with ids, acceptance criteria, checks, progress, follow-ups, next step) and update it as tasks complete. These files are the project's decision log.
- **Delegation.** Work was done by bounded "writer" agents with a precise brief and verified by a separate read-only "verifier" agent that tried to break the claims (it found real bugs several times: a season-selection regression, challenger failures aborting the champion, repeated-looks inflation, last-Elo-model stall). Keep doing independent verification for anything that touches money-like logic, promotion, or production scheduling.
- **RDD review ritual (`gentle-ai review ...`).** On the original PC the CLI asks for consent per candidate; the user has declined every time. If it appears, relay the consent envelope to the user verbatim and never answer for them.
- **Worktree development.** `git worktree add ../ArchetypeNBA-worktrees/<name> -b <branch> origin/main`. Run Python from the worktree's `backend/`; check `python -c "import app; print(app.__file__)"` resolves inside it. `backend/.env` is only in the main checkout; reading real data from a worktree needs the URL passed deliberately.
- **Lockstep schema deploy** (production PC): `pg_dump` the affected tables (or use `scripts/db_transfer.py export`) → `Disable-ScheduledTask NBA-Odds-Tick` → merge → `git pull` → `alembic upgrade head` → dry runs (`run_tick.py --dry-run`, `paper_report.py`) → `Enable-ScheduledTask` → one real tick. New code cannot read an un-migrated schema and old code fails in its Elo write path after the migration.
- **Memory.** The original agent used Engram (local SQLite memory). It does **not** travel with the repo. Everything essential is in this file, `docs/` and `odd/tasks/`. A JSON export of the original memories may be handed over separately (`engram import <file>`).

## 8. Gotchas (each one cost time)

- `backend/app/config.py` loads `backend/.env` with `override=True`: exporting `DATABASE_URL` in the shell does **not** redirect Alembic or the app. Tests/experiments that must not hit the real DB need an explicit guard.
- Real DB on the original PC is a **native PostgreSQL 18.4** on 5432 (user `postgres`, DB `nba_platform`). `backend/docker-compose.yml` exists but is unused; its container conflicts with the native port.
- `Season.id` is not chronological (2023-24 is id 1). Order by `season_label`. A 2026-27 season row exists (inactive) so upcoming games resolve a season; `/api/v1/seasons` hides non-active seasons without player stats; never flip `is_active` casually (it drives the frontend default).
- The `team` table has junk non-NBA rows (EST, WST, MAC, ...), historical abbreviations (NJN→BKN, NOH/NOK→NOP, SEA→OKC) and `full_name == abbreviation` rows. Elo only counts NBA game types `2,4,5,6` (3rd char of `game_id`): preseason `1` and all-star `3` are excluded; 12 neutral-site Cup/international games with two away rows are skipped.
- Player names from the odds feed carry diacritics; matching normalizes both sides (`normalize_player_key`).
- `odds_history` uniqueness uses `NULLS NOT DISTINCT` (PostgreSQL 15+); SQLite in tests emulates it in Python. `price_decimal`, `fair_decimal`, `clv_pct` are generated columns; `closing_price` must be positive.
- Closing-line caveats: a book that dropped a market looks like "unchanged", so a stale quote can pass as the close; CLV coverage is low because books move lines (35% of bets as of 2026-10-26); 13 of 43 tipped-off games had no closing capture because the PC was off. These cannot be backfilled on free tiers.
- The tick decides "today" with the **machine's local timezone** (opening once per local day, daily caps). Keep `America/Mexico_City` or accept the shift.
- Git on Windows prints LF→CRLF warnings (`core.autocrlf=true`); they are noise.
- `nba_api` can be slow or block datacenter IPs; calls use 30–45 s timeouts. An empty `season_type` returns all game types in a window.
- `scripts/start_services.ps1` starts the backend on **38921** and the frontend on **38920** (not 8000/3000). The backend process must be restarted to pick up code changes.
- **Known fabrication / rule-3 violations still in the code**: `services/injury_scraper.py` (invented fallback injuries, see §10) and `analytics/props_engine.py::load_baselines_from_db` (opens a SQLite file that does not exist and falls back to hardcoded star baselines; its season weights key on the non-chronological `season.id`). The props page and `daily_runner.py` still use them.
- **Credit guard gap**: `POST /api/v1/props/run-analysis` and `GET /api/v1/props/today?refresh=true` call The Odds API (up to 6 credits: 2 events × 3 markets) plus Gemini, *outside* the tick's `--min-remaining` guard. The props cache file is served without checking its age.
- **Hardcoded interpreter paths**: `scripts/run_backend.bat` and `scripts/run_pipeline.bat` contain this PC's Python path. `scripts/register_tick_task.ps1` now discovers Python (`-PythonExe`, `backend/.venv`, `run_pipeline.bat` if the path exists, then PATH), but the `.bat` files still need editing on a new machine.
- **Dependencies**: the code uses psycopg 3 (`postgresql+psycopg://`); `requirements.txt`/`pyproject.toml` were fixed to list `psycopg[binary]` (earlier they listed only `psycopg2-binary`, which would break a clean install). `ETL_BATCH_SIZE` in `config.py` is defined but unused. The README links a `LICENSE` file that does not exist; the licence holder is the owner's call.
- **Feature sets are frozen per model**: `MarginFeaturesModel` raises if the stored `feature_names` differ from the code's `FEATURE_NAMES`, so adding features in place would make challenger id 2 unloadable. Version the feature set in code (keep the old list loadable) before adding any.

## 9. State of the system (as of 2026-10-26)

| Metric | Value |
|--------|-------|
| Tests | 633 backend tests pass (+ new ones from later PRs); frontend `tsc --noEmit` clean |
| Database | PostgreSQL 18.4, 229 MB, Alembic head `d7a2f5b81c39`; 23 seasons of game logs (2003-04..2025-26), 59k Elo rows per model |
| Capture | Since 2026-10-06 (opening lines) and 2026-10-20 (full tick); Odds API credits left: 371 (resets on the 1st of each month); task healthy, 0 failed ticks |
| Paper trading (2026-10-20 → 10-26) | flat: 56 bets (49 settled), P/L −5.28 u, ROI −11.4%; ¼ Kelly: 44 bets, −13.34 u. Bankrolls 94.7 u / 86.7 u. **Tiny samples, not evidence of anything.** |
| CLV | average +3.5% flat / +4.8% Kelly over 18 / 12 bets with a comparable close (35% coverage; survivorship toward unchanged lines) — treat as noise |
| Skill vs market | Brier model 0.2495 vs Pinnacle close 0.2013 on 30 games: the market is better, as expected for a baseline |
| League | champion `elo_538` 1.1; challenger `margin_features` 41/150 paired games, log-loss gain +0.005 (CI −0.017..+0.030). Earliest possible promotion mid-November. No promotion yet |
| Open edges | shutdown endpoint has no CSRF/origin guard; postponed games cost one free nba_api call per tick for up to 14 days; totals/props bets are not settled; the frontend lacks a model-league page |

Honest expectation: most challengers will end retired; real progress needs new *signal* (injuries/lineups, totals/props models, better priors), not more hyperparameter search.

## 10. Next task: free injuries and lineups as a model signal

Verified 2026-10-26:

- `backend/app/services/injury_scraper.py` targets `https://official.nba.com/nba-injury-report-2024-25-season/` (a stale season URL) and parses a 6-column HTML table with a regex. The real page is a **list of links to PDFs**, so the parser never matches and `fetch_injury_report()` always returns `_get_fallback_sample_report()`: **invented injuries** that feed the Gemini layer in `props.py` / `daily_runner.py`. Remove the fabrication (rule 3).
- The official report exists as PDFs at `https://ak-static.cms.nba.com/referee/injury/Injury-Report_YYYY-MM-DD_HH_MMAM|PM.pdf` (Eastern time), published roughly every 15 minutes (page: `https://official.nba.com/nba-injury-report-2026-27-season/`). Teams must submit statuses by 5 pm local the day before and update on game day. 2025-26 PDFs are reachable at the same path; check how far back it goes.
- **Terms**: the page footer states NBA.com content may not be duplicated, redistributed or manipulated. Low-frequency personal use for research is a gray area: **ask the user before adding automated downloads**, keep requests rare (a few per day, honest User-Agent), do not redistribute the PDFs or the derived raw data.
- Lineups/starters: unverified. Candidates to evaluate: `nba_api` live/box score endpoints (starting five appear shortly before tip-off). Expect a short window before the tick's 30-minute closing window.

Modelling caveats the next agent must handle:

1. **Train/serve skew.** History can be reconstructed from `player_game_log` (who actually played/DNP, minutes), which is *post-game* knowledge; at serving time only the pre-game *status* (Out/Doubtful/Questionable/Probable) exists. Train on features that exist at prediction time, e.g. availability probability by status, or the star-minutes-lost proxy, and verify historical PDFs if obtainable.
2. **Leakage.** Every feature must be computable strictly before tip-off; use the same builder for training and prediction (`FeatureState` pattern in `analytics/features.py`).
3. **Evaluation.** First make the feature set versionable in code (see §8, "Feature sets are frozen per model"), then register the new set as a *new `margin_features` version*, run `scripts/model_lab.py` for the historical gate, and let it run in shadow; promotion is decided by `learn`, not by hand. Expect the historical gain to be small: a +0.0026 gain needs thousands of paired games to be detectable.
4. Keep tests offline: store a few real PDFs/text fixtures, never fetch in tests.

Other backlog (see [`docs/ROADMAP.md`](docs/ROADMAP.md)): totals and props models through the same registry; settle totals/props bets; frontend league page; promotion notifications; shutdown-endpoint hardening; second odds feed (SportsGameOdds free tier); CI; legacy cleanup.

## 11. Moving to a new PC (checklist)

1. Old PC: pause the tick (`Disable-ScheduledTask NBA-Odds-Tick`), run `python backend/scripts/db_transfer.py export`, verify, copy the `.dump` + `.manifest.json` and `backend/.env` through a secure channel (never git/chat).
2. New PC: install the same PostgreSQL major (18), clone the repo, create the venv, `pip install -r backend/requirements.txt`, `python backend/scripts/db_transfer.py import ...`, set `backend/.env`, run tests, `paper_report.py`.
3. Register the tick on the new PC (Windows: `scripts/register_tick_task.ps1`; Linux/macOS: cron/systemd in `docs/OPERATIONS.md`) and **unregister it on the old PC** (`scripts/register_tick_task.ps1 -Unregister`): two machines capturing would double-spend the same API quota and fork the data.

Full runbook: [`docs/DB_TRANSFER.md`](docs/DB_TRANSFER.md), [`docs/SETUP.md`](docs/SETUP.md).

## 12. Index

[`docs/README.md`](docs/README.md) · [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) · [`docs/QUANT_MODULE.md`](docs/QUANT_MODULE.md) · [`docs/OPERATIONS.md`](docs/OPERATIONS.md) · [`docs/SETUP.md`](docs/SETUP.md) · [`docs/DB_TRANSFER.md`](docs/DB_TRANSFER.md) · [`docs/DECISIONS.md`](docs/DECISIONS.md) · [`docs/ROADMAP.md`](docs/ROADMAP.md) · [`odd/tasks/`](odd/tasks/) (feature plans, newest = `model-learning-loop.md`).
