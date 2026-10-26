# Setup from scratch

How to get ArchetypeNBA running on a new machine, on any operating system: prerequisites, installation, configuration, the database (migrate and ingest, or restore a dump), tests, starting the services and registering the scheduled tick. The quant system needs only the backend and PostgreSQL; the frontend is optional for it. Commands were checked against the repository on 2026-10-26; what could not be run on a development machine is marked **unverified**.

## Quick path

1. Install Python 3.12, PostgreSQL (18 recommended, 15 minimum), Git; Node 20.9 or newer only if you want the web UI.
2. `git clone`, create a virtualenv, `pip install -r backend/requirements.txt`.
3. Create the database and `backend/.env`.
4. `cd backend && python -m alembic upgrade head`.
5. Fill the database: restore a dump ([`DB_TRANSFER.md`](DB_TRANSFER.md)) **or** ingest history and register the champion ([section 6](#6-fill-the-database)).
6. `python -m pytest -q`, then `python scripts/run_tick.py --dry-run`.
7. Register the tick ([section 10](#10-register-the-scheduled-tick)) and walk the [first-day checklist](#11-first-day-verification-checklist).

## 1. Prerequisites

| Tool | Version | Why |
|------|---------|-----|
| Python | 3.12 (tested: 3.12.10). `backend/pyproject.toml` declares 3.10 or newer | Backend, scripts, tests |
| PostgreSQL | **18 recommended, 15 minimum** | The schema uses `UNIQUE ... NULLS NOT DISTINCT`, which needs 15; the production database runs 18.4. Generated columns need 12 |
| Git | any recent | Clone and worktrees |
| Node.js | 20.9 or newer (Next.js 16.2.6 declares `>=20.9.0`; tested with Node 24 and npm 11) | Frontend only |
| PowerShell | Windows PowerShell 5.1 or `pwsh` | Task registration on Windows; four tests are skipped without it |
| Network | Outbound HTTPS | The Odds API, `nba_api` |
| An Odds API key | Free plan, 500 credits per month | Odds capture. Get it from the provider's website. Without it the tick still predicts, settles and learns, but cannot capture |

Install PostgreSQL with your platform's usual route (examples, adjust to your system): the official Windows installer; macOS `brew install postgresql@18`; Debian or Ubuntu through the PostgreSQL project's apt repository. Make sure the server listens on `localhost:5432`.

Docker alternative (**only if no native PostgreSQL holds port 5432**): `backend/docker-compose.yml` starts PostgreSQL 15 and Redis with the credentials defined in that file; its container conflicts with a native instance on the same port, which is why the production PC does not use it. Redis is optional: without it the API cache is silently disabled.

## 2. Clone

```
git clone https://github.com/p5Patricio/ArchetypeNBA.git
cd ArchetypeNBA
```

Development rule: the machine that runs the tick executes whatever is checked out in its main working tree. Do experiments in a worktree (`git worktree add ../ArchetypeNBA-worktrees/<name> -b <branch> origin/main`), never in that tree ([`OPERATIONS.md`](OPERATIONS.md), section 4).

## 3. Python environment

Linux or macOS:

```
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Windows PowerShell:

```
cd backend
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Versions the test suite last passed with (2026-10-26, Windows, Python 3.12.10): fastapi 0.139.2, sqlmodel 0.0.39, SQLAlchemy 2.0.51, alembic 1.19.0, psycopg 3.3.4, numpy 2.5.1, pandas 3.0.3, scikit-learn 1.9.0, nba_api 1.11.4, httpx 0.28.1, pydantic 2.13.4, pytest 9.1.1. `requirements.txt` pins only lower bounds, so a fresh install may resolve newer versions.

## 4. Configuration (`backend/.env`)

Create `backend/.env` (git-ignored; never commit it; never paste it into chat). `backend/.env.example` is the template and lists every setting with its default. The settings are defined in `backend/app/config.py`:

| Variable | Needed for the quant system | Example or default |
|----------|----------------------------|--------------------|
| `DATABASE_URL` | Yes | `postgresql://<user>:<password>@localhost:5432/nba_platform` |
| `THE_ODDS_API_KEY` | For odds capture | your key; empty means capture is disabled |
| `LEARNING_AUTOPROMOTE` | No | `true` (kill switch for automatic role changes) |
| `LEARNING_MIN_GAMES`, `LEARNING_MIN_DAYS_LIVE`, `LEARNING_COOLDOWN_DAYS`, `LEARNING_PROPOSAL_DAYS`, `LEARNING_MAX_CHALLENGERS`, `LEARNING_LOOK_INTERVAL_DAYS`, `LEARNING_MAX_LOOKS`, `LEARNING_MAX_AGE_DAYS` | No | `150`, `14`, `30`, `7`, `3`, `7`, `12`, `150` |
| `GEMINI_API_KEY`, `GEMINI_MODEL` | No (props AI layer) | empty, `gemini-3.6-flash` |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | No (props report) | empty |
| `PROPS_SIMULATION_RUNS` | No | `10000` |
| `REDIS_URL` | No (cache) | `redis://localhost:6379/0` |
| `CORS_ORIGINS` | No | localhost and 127.0.0.1 on the dev and production ports |
| `DEBUG` | No | `false` (`true` echoes every SQL statement) |
| `ETL_BATCH_SIZE` | No | `100`; defined but not used by the code |

Two behaviors to know:

- `config.py` loads `backend/.env` (and a repo-root `.env`) with `override=True`: **the file wins over variables exported in the shell**. A worktree has no `.env` of its own, so it falls back to the default URL, which fails authentication. That is a feature: a worktree cannot hit the real database by accident.
- The tick decides "today" (one opening per day, daily stake caps) with the machine's local time zone. Keep `America/Mexico_City` or accept the shift.

## 5. Create the database and migrate

Create an empty database (use your own user):

```
createdb -U postgres nba_platform
```

or `psql -U postgres -c "CREATE DATABASE nba_platform;"`. Then, from `backend/`:

```
python -m alembic upgrade head
python -m alembic current
```

`current` must print the head, `d7a2f5b81c39` as of 2026-10-26. This creates every table, the native enums, the generated columns, the `NULLS NOT DISTINCT` constraints and the two views (rendered offline on 2026-10-26 and checked to contain 20 model tables plus `alembic_version`). **Always migrate with Alembic rather than `create_all`**: only the migration creates the views. Several legacy scripts call `create_all`; after Alembic that is a no-op.

## 6. Fill the database

### Option A: restore a dump (recommended for the same production state)

Follow [`DB_TRANSFER.md`](DB_TRANSFER.md) (`scripts/db_transfer.py import`, with integrity checks on both ends). The target PostgreSQL must be the same major version as the source or newer (the manifest records it; the source runs 18.x), even though the schema alone only needs 15. A restore brings the history, the champion, the challengers, the odds already captured and the audit trail. It is also the only way to get the odds and closing lines you did not capture yourself.

### Option B: from scratch

Odds history cannot be recreated on a free plan; this builds the results history and the baseline model only. Order matters:

| # | Command (from `backend/`) | What it does |
|---|---------------------------|--------------|
| 1 | `python scripts/bulk_ingest_nba.py` | Takes no arguments. Pulls `nba_api` data for the 23 seasons 2003-04 to 2025-26 into `team`, `player`, `season`, stats and `player_game_log`, and also builds clusters and similarities. Needs the network and a long time (tens of minutes; **unverified**, not run here) |
| 2 | `python scripts/backfill_elo.py --evaluate --register` | Rebuilds the Elo ratings from `player_game_log` for the champion, prints walk-forward metrics per season and registers `elo_538` 1.1 as the champion with its margin sigma and Brier. This is what makes the recorder able to run |
| 3 | `python scripts/model_lab.py` | Optional, read-only: runs the historical lab and prints which candidates would pass the gate |
| 4 | `python scripts/model_lab.py --register --confirm-database nba_platform` | Optional: registers the gate-passing candidates as challengers. Otherwise the tick's `learn` step does this weekly |

Limits of Option B: `bulk_ingest_nba.py` stops at season 2025-26; games played after that are not backfilled (the tick's results step only chases games it holds odds for). Season rows for upcoming games are created automatically by odds ingestion and left inactive. For a database that is current to the day, prefer Option A.

The legacy `scripts/seed_database.py` (Excel ETL for the original platform demo) is not needed for the quant system.

## 7. Run the tests

```
cd backend
python -m pytest -q
```

Expected: **633 passed, 1 warning in about 2 minutes** (2026-10-26, Windows, Python 3.12.10). The suite is offline and deterministic (in-memory SQLite, seeded randomness); it never needs PostgreSQL or the network. Four tests in `tests/test_tick_task_registration.py` are skipped when neither `powershell` nor `pwsh` is installed, so expect a slightly lower pass count on a bare Linux machine. Run it from `backend/` (`pytest.ini` sets `pythonpath = .`).

## 8. Check the system without spending anything

```
python scripts/run_tick.py --dry-run
python scripts/paper_report.py
python scripts/model_league.py status
```

The dry run prints what each of the five steps would do and the worst-case credits; it makes no network call, takes no lock, writes nothing. On a fresh database the report prints `n/a` and "No paper bets recorded yet", which is correct.

## 9. Start the web services

Development:

```
cd backend && python -m uvicorn app.main:app --reload --port 8000
cd frontend && npm install && npm run dev
```

The API is at `http://127.0.0.1:8000` (interactive docs at `/docs`) and the UI at `http://localhost:3000`; the UI reaches the API through `NEXT_PUBLIC_API_BASE` (default `http://localhost:8000`).

Production-style on Windows (ports 38921 for the API and 38920 for the UI, `scripts/start_services.ps1`): set `NEXT_PUBLIC_API_BASE=http://127.0.0.1:38921` in a git-ignored `frontend/.env.local`, run `npm run build` in `frontend/`, edit the hardcoded Python path in `scripts/run_backend.bat` (and `scripts/run_pipeline.bat`) for your machine, then:

```
powershell -ExecutionPolicy Bypass -File .\scripts\start_services.ps1
```

Whether the original PC sets `NEXT_PUBLIC_API_BASE` this way is **unverified**; the repository scripts do not set it. See [`OPERATIONS.md`](OPERATIONS.md), section 6, for stopping, autostart and logs.

## 10. Register the scheduled tick

Windows (the production setup). The register script finds the interpreter by itself, in this order: `-PythonExe`, the virtualenv at `backend\.venv`, the path written inside `scripts/run_pipeline.bat` (only if that path exists on this machine), then the first `python.exe` on `PATH` (the empty Microsoft Store alias in `WindowsApps` is ignored). It stops with an error if none is found. With the virtualenv of [section 3](#3-python-environment) no flag is needed:

```
powershell -ExecutionPolicy Bypass -File .\scripts\register_tick_task.ps1 -WhatIf
powershell -ExecutionPolicy Bypass -File .\scripts\register_tick_task.ps1 -StartNow
```

The first command only previews the task XML and prints the interpreter it chose; pass `-PythonExe <path to python.exe>` to override it. The script swaps `python.exe` for `pythonw.exe` (no console window). `scripts/run_backend.bat` and `scripts/run_pipeline.bat` still hardcode the old PC's Python path: edit them if you use `start_services.ps1` ([section 9](#9-start-the-web-services)). Linux and macOS: use cron or a systemd timer ([`OPERATIONS.md`](OPERATIONS.md), section 7).

**Never register the tick on two machines at once**: both would spend the same 500-credit quota and fork the data. Moving machines: pause and unregister the old tick first.

## 11. First-day verification checklist

- [ ] `python -m pytest -q` passes (633 on 2026-10-26).
- [ ] `python -m alembic current` prints `d7a2f5b81c39`.
- [ ] `python scripts/backfill_elo.py --evaluate --register` ran (or the dump restored the champion), and `python scripts/model_league.py status` lists `elo_538 1.1` as `champion`.
- [ ] `python scripts/run_tick.py --dry-run` exits 0 and lists `opening`, `closing`, `results`, `learn`, `record`.
- [ ] `backend/.env` has `THE_ODDS_API_KEY`; a first real `python scripts/run_tick.py` ends with `exit code: 0` (it spends 3 credits if events are upcoming).
- [ ] `logs/tick.log` exists and shows that tick.
- [ ] The task is registered: `Get-ScheduledTaskInfo -TaskName NBA-Odds-Tick` shows `LastTaskResult : 0` after the first scheduled run.
- [ ] The old machine, if any, no longer has the task.
- [ ] Day 2: `python scripts/paper_report.py` shows predictions for upcoming games; after games finish, bets settle and "Closing captures missed" stays low.

## Next step

Daily operation: [`OPERATIONS.md`](OPERATIONS.md). The big picture: [`ARCHITECTURE.md`](ARCHITECTURE.md).
