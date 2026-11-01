# Operations runbook

> **Current production setup is WSL2 (since 2026-10-27): see [`WSL.md`](WSL.md) for the systemd timers, commands and gotchas.** The PowerShell / Task Scheduler / `pythonw.exe` procedures below describe a native Windows install; section 7 holds the Linux equivalents that WSL uses.

How to keep the paper-trading system running: the scheduled tick, the credit budget, the daily and weekly checks, schema deploys, manual controls, the web services and a troubleshooting table. Commands are shown for Windows PowerShell (the production setup) with Linux/macOS equivalents where they differ. Run them from the repository root unless a `cd` says otherwise. Facts were verified against the code on 2026-10-26; items that could not be checked from a development machine are marked **unverified**.

## Quick path

Is it healthy? (30 seconds)

1. `Get-ScheduledTaskInfo -TaskName NBA-Odds-Tick | Format-List LastRunTime, LastTaskResult, NextRunTime` -> `LastTaskResult : 0`, `LastRunTime` within the last 15 minutes while the PC is on and you are logged in.
2. `Get-Content logs\tick.log -Tail 40` -> the last summary ends with `exit code: 0`.
3. `cd backend; python scripts/paper_report.py` -> no Python error, "Closing captures missed" is small.

If any of the three fails, go to [section 11](#11-troubleshooting).

## 1. The scheduled task

| Item | Value |
|------|-------|
| Name | `NBA-Odds-Tick` |
| Runs | `pythonw.exe -u backend\scripts\run_tick.py`, working directory `backend\` |
| Triggers | At log on, plus a time trigger starting one minute after registration; both repeat every 15 minutes with no end date |
| Conditions | Only while the user is logged on (`InteractiveToken`); only if a network is available; starts late if a run was missed (`StartWhenAvailable`); never wakes the PC; hidden; runs on battery too |
| Overlap | `IgnoreNew`: a second instance is never started while one runs |
| Limit | Killed after 10 minutes |
| Defined by | `scripts/register_tick_task.ps1` (XML, so the indefinite repetition is exact) |

### Why `pythonw.exe`

Running `python.exe` (or `powershell -WindowStyle Hidden`) creates a console window for a moment, and that instant is enough to pull focus out of a meeting or a game. `pythonw.exe` has no console at all. The register script swaps `python.exe` for `pythonw.exe` when it finds it next to the interpreter. Consequence: `sys.stdout` is `None` under the scheduler, so **the only log is `logs/tick.log`**. Verify any change to the launch method with a process watcher (look for `conhost.exe` or `python.exe` appearing during a tick), not by eye. This was a user-facing incident fixed in PR #16.

### Register, unregister, pause, resume, run now

| Action | Command |
|--------|---------|
| Preview the task XML, change nothing | `powershell -ExecutionPolicy Bypass -File .\scripts\register_tick_task.ps1 -WhatIf` |
| Register (also removes the legacy `NBA-Odds-Opening` and `NBA-Odds-Closing` tasks) | `powershell -ExecutionPolicy Bypass -File .\scripts\register_tick_task.ps1` |
| Register and run one tick now | add `-StartNow` |
| Override the interpreter | add `-PythonExe <path to python.exe>`. Without it the script uses `backend\.venv`, then the path in `scripts/run_pipeline.bat` if it exists, then the first `python.exe` on `PATH` (the Microsoft Store alias is ignored) |
| Change the interval (1 to 59 minutes, default 15) | add `-IntervalMinutes <n>`. The window and the quota arithmetic below assume 15 |
| Unregister | `powershell -ExecutionPolicy Bypass -File .\scripts\register_tick_task.ps1 -Unregister` |
| Pause | `Disable-ScheduledTask -TaskName NBA-Odds-Tick` |
| Resume | `Enable-ScheduledTask -TaskName NBA-Odds-Tick` |
| Run one tick now through the scheduler | `Start-ScheduledTask -TaskName NBA-Odds-Tick` |
| Run one tick in your terminal (prints to the screen and to `logs/tick.log`) | `cd backend; python scripts/run_tick.py` |
| Preview a tick: no network, no writes, no log file | `cd backend; python scripts/run_tick.py --dry-run` |

"Access denied" on registration: open PowerShell as administrator. Pause the task before any manual database work and before a deploy; resume afterwards. Never leave two machines registered: they would spend the same credit quota and fork the data ([`SETUP.md`](SETUP.md), moving machines).

### Reading `logs/tick.log`

The file rotates at 2 MB and keeps 3 backups (`tick.log.1` to `tick.log.3`), about 8 MB at most. Each tick logs one line per step and then a multi-line summary. Illustrative shape (not a real capture):

```
<time> [INFO] app.services.tick: tick: step opening -> skipped: opening already captured for <date>
<time> [INFO] run_tick:
Tick <iso time>: completed
  [skipped] opening: opening already captured for <date>
  [skipped] closing: nothing_due: No event tips off within 30 min without a pending closing capture (no credits spent).
  [ok] results: 3 game(s) finalized, 5 bet(s) settled, CLV filled for 2 bet(s)
  [skipped] learn: ...
  [ok] record: 9 game(s) in horizon, ...
  missed closing lines (last 12 h, PC off or tick missed): 0
  exit code: 0
```

| Look for | Meaning |
|----------|---------|
| `[error]` after a step name, or a `Traceback` | A step failed; the others still ran. Read the first one |
| `credits spent: N` or `quota: A -> B (spent N)` | What a paid step cost; `OddsApiService: Quota Remaining: N requests.` is the live balance |
| `missed closing lines (last 12 h, PC off or tick missed): N` | Games that tipped off with no closing capture; those lines are lost for good |
| `another tick holds logs/tick.lock; nothing done` | Overlap prevented; harmless unless it repeats for more than 20 minutes |
| `aborted_low_credits` | The credit guard refused a paid call |

Search it: `Select-String -Path logs\tick.log -Pattern '\[error\]|Traceback'` (Linux/macOS: `rg "\[error\]|Traceback" logs/tick.log`, or `grep -E`).

### Exit codes

| Code | Meaning |
|------|---------|
| `0` | No step errored. Also returned when another tick holds the lock, and when steps were deliberately skipped (credit guard, nothing due, already captured today) |
| `1` | At least one step errored, or the tick could not start at all (for example the database is unreachable: `tick aborted before any step could run`) |

In Task Scheduler, `LastTaskResult` mirrors the Python exit code. `267009` (0x41301) means the task is running right now; `267011` (0x41303) means it has not run yet.

### Lock file

`logs/tick.lock` holds the pid and start time of the running tick, is created atomically and is removed when the tick ends. A lock older than 20 minutes is considered stale and replaced automatically. To clear it by hand, first confirm no tick is running, then delete the file.

### When a tick fails

| What the summary says | Cause | What to do |
|-----------------------|-------|------------|
| `THE_ODDS_API_KEY is not configured` | Missing key in `backend/.env` | Add the key. Recording and learning still ran |
| `call_failed` | HTTP error or timeout on a paid call, or the quota is exhausted | Nothing: no marker was written, so the next tick retries. If it repeats, check the quota and the key |
| `paid opening call wrote no marker (no game resolved); it will retry` | The call succeeded but no event could be mapped to a game (team names or season) | Check the `team` table abbreviations; this costs 3 credits per retry, so fix it quickly or pause the task |
| `results: ... stage(s) failed` | `nba_api` timeout or block | Nothing: stages are isolated and the next tick retries; settlement of already-final games is unaffected |
| `learn` with `ERROR proposal: ...` | The candidate lab failed | A `proposal` row beginning with `error:` holds the cadence for a day; read the traceback in the log |
| `record` fails with "not registered" | No champion in `model_version` | `cd backend; python scripts/backfill_elo.py --evaluate --register` |
| `tick aborted before any step could run` | PostgreSQL is down or the password changed | Start the service, fix `backend/.env`, run `alembic current` |

## 2. Credit budget

The Odds API plan has **500 credits per month**, reset on the 1st (balance on 2026-10-26: 371). `/events` is free and returns the balance in its response headers.

| Call | Cost |
|------|------|
| Opening, whole slate (`h2h`, `spreads`, `totals`, up to 10 bookmakers) | 3 credits, at most once per local day |
| Closing, game lines for every game inside the window that lacks a marker | 3 credits per cluster of games |
| Closing, player props for one event | 1 credit (one market, `player_points`), one event per run |
| On-demand `POST /props/run-analysis` from the web page | Up to 6 credits (2 events x 3 markets), **outside the guard** |

Monthly arithmetic (from `odds_snapshot.py`), assuming about 3 tip-off clusters per game day and 28 game days:

| Item | Per game day |
|------|--------------|
| Opening | 3 |
| Closing game lines (3 clusters x 3) | 9 |
| Props (3 clusters x 1 to 2 runs x 1) | 3 to 6 |
| **Total** | **15 to 18** |

15 to 18 credits x 28 days is 420 to 504 per month against 500. The guard is the hard stop: a paid call is refused when `remaining - cost < --min-remaining` (default 25), and an unknown balance also refuses, so the floor protects the last 25 credits. If credits run out, captures stop (`aborted_low_credits`), but predictions, settlement and learning keep running on what is already stored. The plan is free; do not add a paid tier without the maintainer's approval.

Check the balance: `Select-String -Path logs\tick.log -Pattern 'Quota Remaining' | Select-Object -Last 1`. Rule of thumb: credits left divided by game days left in the month should stay above about 16.

Raising the props events per run from 1 to 3 would cost up to 3 + 3 x (3 + 3 x 2) = 30 credits a day and would exhaust the quota before month end. Do not.

## 2.1 Second odds feed: SportsGameOdds (daily capture enabled)

An integrated second odds feed from SportsGameOdds (https://sportsgameodds.com) provides game lines (moneyline, spreads, totals) and player props (points, rebounds, assists, pra) across additional US bookmakers (Caesars, ESPN BET, BetMGM, DraftKings, FanDuel, Bovada, Unibet, PointsBet, William Hill). The client and parser have been validated against official documentation example responses (`tests/test_sgo_docs_validation.py`) and live responses via `scripts/sgo_probe.py`.

The daily capture is wired as step `sgo` in the scheduled tick (`app/services/tick.py`). It runs once per machine-local day directly after the `opening` capture succeeds, when `SPORTSGAMEODDS_API_KEY` is configured and `SGO_CAPTURE_ENABLED=true`.

### Quota and Budget Math
- **Amateur Quota**: 2,500 objects/month, 10 requests/minute. In SportsGameOdds pricing, 1 "object" is an entire game/event containing its full tree of odds across all bookmakers and markets.
- **Daily Consumption**: The daily capture requests NBA events with `oddsAvailable=true`, `startsAfter=now`, and `startsBefore=now+36h` (typically 5 to 15 games per day).
- **Daily Budget**: Capped by `SGO_DAILY_OBJECT_BUDGET` (default 30 objects). At ~12–15 objects per day over 30 days, monthly consumption is ~360–450 objects, consuming only ~15–18% of the 2,500 monthly quota and preserving >2,000 objects for backfills or high-volume slates.
- **Quota Guard**: Configured via `SPORTSGAMEODDS_MIN_REMAINING_OBJECTS` in `config.py` (default floor 100). If remaining objects drop below this floor, fetches are blocked with `InsufficientQuotaError`. Usage is also checked against `GET /account/usage` (which does not consume quota) and tracked locally in `logs/sportsgameodds_usage.json`.

### How to enable it
1. Register for an API key at https://sportsgameodds.com (the free "Amateur" plan provides 2,500 objects/month, 10 requests/minute, NBA included; **no Pinnacle**).
2. Add your key and optional overrides to `backend/.env`:
   ```env
   SPORTSGAMEODDS_API_KEY=your_actual_key_here
   SGO_CAPTURE_ENABLED=true
   SGO_DAILY_OBJECT_BUDGET=30
   ```
3. Test your key and verify live response structure using the probe CLI:
   ```bash
   cd backend
   python scripts/sgo_probe.py --dry-run          # Preview request without network
   python scripts/sgo_probe.py --capture-dry-run  # Preview daily capture window and budget
   python scripts/sgo_probe.py                    # Send 1 small probe request (2 events) and inspect schema
   ```

### Data Storage & Provenance
- **Dedicated Sportsbooks**: Main-market quotes and player props are stored in `odds_history` under dedicated sportsbooks prefixed with `sgo_` (e.g., `sgo_draftkings`, `sgo_fanduel`) with display name format `<Name> (SportsGameOdds)`. This isolates SGO quotes from The Odds API quotes.
- **Game Mapping**: Events are matched strictly to existing `Game` rows by team names/abbreviations and commence time within a 6-hour tolerance. SGO never creates games.
- **Player Props**: SGO player props (`statEntityID = <playerID>`) resolve the player name via the event's `players` map and match DB players using the same team-scoped, diacritic- and suffix-aware resolver (`resolve_player_id`). Unmatched players are counted, logged, and skipped—never fabricated.
- **Consensus Snapshot Isolation**: SGO full-game consensus quotes (`fairOdds`, `fairSpread`, `fairOverUnder`, and `bookOdds`) are stored in `market_consensus_snapshot` with `source='sgo_fair'`. Consensus lines are **strictly forbidden** from entering `odds_history` so they can never be mistaken for bookable best prices by the paper betting recorder.
- **Capture Idempotency**: Successful captures write an `OddsSnapshotCapture` marker of kind `'sgo_daily'` with `credits_spent = objects_used`, preventing duplicate daily runs.

### Why it never bets alone
- **No Sharp Book**: SportsGameOdds free tier does not include Pinnacle (the sharp benchmark of true market probabilities).
- **No Independent Bets**: The betting policy generates wagers only when model probabilities beat Pinnacle's de-vigged fair price by at least 2 pp. A feed without Pinnacle can never establish a fair market baseline.
- **Best-Price Execution & Cross-Check Only**: SGO quotes act solely as execution candidates when a sharp edge exists and the quote is younger than `max_quote_age_minutes` (360 min). Daily quotes captured in the morning will naturally age out before evening tip-offs unless fresh, ensuring safety.

## 3. Daily and weekly checks

### Daily

| Check | Command | What good looks like |
|-------|---------|----------------------|
| Task health | `Get-ScheduledTaskInfo -TaskName NBA-Odds-Tick` | `LastTaskResult` 0; `NextRunTime` in the future |
| Last ticks | `Get-Content logs\tick.log -Tail 60` | `exit code: 0`; no `[error]` |
| Report | `cd backend; python scripts/paper_report.py` | Settled bets grow; pending bets belong to games not yet played; "Closing captures missed" is 0 or close to it on days the PC was on |
| Credits | see section 2 | Above the rule of thumb |

### Weekly

| Check | Command | What good looks like |
|-------|---------|----------------------|
| League | `cd backend; python scripts/model_league.py status` | A "last candidate proposal" within the last 7 days; challenger `paired n` growing; no promotion or retirement you did not expect |
| Schema | `cd backend; python -m alembic current` | Equals the head (`e3f8b1a4c9d2` as of 2026-10-28) |
| Backup | `cd backend; python scripts/db_transfer.py export` ([section 9](#9-backups)) | A new `.dump` and `.manifest.json` pair that `verify` accepts, copied off the machine |
| Code | `git status` and `git log -1` in the production checkout | Clean tree, on `main`, no unmerged work |
| Disk | Size of `logs\` | A few MB (rotation caps `tick.log`; `backend.log` and `frontend.log` grow without rotation) |

Treat the P/L and CLV lines as noise until there are hundreds of bets ([`QUANT_MODULE.md`](QUANT_MODULE.md), section 13).

## 4. Lockstep schema deploy

The production PC executes whatever is checked out in its main working tree, so unmerged code never lives there. New code cannot read an un-migrated schema, and old code fails in its Elo write path after a migration; hence the order matters. Develop in a separate worktree:

```
git worktree add ../ArchetypeNBA-worktrees/<name> -b <branch> origin/main
cd ../ArchetypeNBA-worktrees/<name>/backend
python -c "import app; print(app.__file__)"     # must resolve inside the worktree
```

`backend/.env` exists only in the main checkout; reading real data from a worktree needs the database URL passed on purpose. A first equivalence script once ran old code against the real database in a non-dry mode (no rows were written, but it was close): use `--dry-run` and check `app.__file__`.

Deploy a change that includes a migration:

| # | Step | Command |
|---|------|---------|
| 1 | Back up everything and verify the backup | `cd backend; python scripts/db_transfer.py export`, then `python scripts/db_transfer.py verify <dump>` |
| 2 | Pause the tick and wait for any running tick to end | `Disable-ScheduledTask -TaskName NBA-Odds-Tick`; confirm `logs\tick.lock` is gone |
| 3 | Merge to `main` (the maintainer's decision), then pull in the production checkout | `git pull` |
| 4 | Migrate | `cd backend; python -m alembic upgrade head`, then `python -m alembic current` |
| 5 | Dry runs | `python scripts/run_tick.py --dry-run` and `python scripts/paper_report.py` |
| 6 | Resume | `Enable-ScheduledTask -TaskName NBA-Odds-Tick` |
| 7 | Verify one real tick | `Start-ScheduledTask -TaskName NBA-Odds-Tick`, then read `logs\tick.log`: `exit code: 0` |

A change without a migration still follows steps 2, 3, 6 and 7. Downgrades exist for every migration (`alembic downgrade -1`), but `d7a2f5b81c39` deletes the rating rows of every model except the legacy one when it is downgraded.

## 5. Manual controls

### `model_league.py`

From `backend/`. Everything that writes needs `--confirm-database nba_platform` (the real database name typed back) on anything but SQLite. Exit codes: 0 ok, 1 error (for example the lab cannot run), 2 refused by a guard or invariant.

| Subcommand | Effect | Writes |
|------------|--------|--------|
| `status [--now ISO]` | Registry table plus the league report | No |
| `evaluate` (or `--dry-run`) | Evaluate every challenger, print the decisions | No (default) |
| `evaluate --apply` | Write audit rows and apply the decisions; respects `LEARNING_AUTOPROMOTE` | Yes |
| `propose --dry-run [--seed N] [--configs N] [--max-seconds S]` | Run the lab, show what would be registered | No |
| `propose [...]` | Run the lab and register gate-passing candidates | Yes |
| `promote <model_id> --reason "..." [--force]` | Make a model the champion (the old one becomes a challenger); skips the statistical gate, keeps the invariants; `--force` also during the 30-day cooldown and for a retired model | Yes |
| `retire <model_id> --reason "..." [--force]` | Retire a challenger; `--force` also the last Elo model (which stalls rating updates and the lab) | Yes |

Every manual change writes an audit row whose reason starts with `manual:`. A reason is mandatory.

### Other switches

| Control | How |
|---------|-----|
| Stop automatic promotion, retirement and registration | Set `LEARNING_AUTOPROMOTE=false` in `backend/.env`. It takes effect on the next tick (each tick is a new process). Evaluations keep being recorded, as `dry_run` for actionable decisions |
| Skip steps in a manual run | `python scripts/run_tick.py --skip learn` (choices: `opening closing results learn record`). The scheduled task passes no arguments, so use the task pause or the setting above instead |
| Spend no credits | `python scripts/run_tick.py --skip opening closing` for a manual run; or pause the task |
| Raise the credit floor | `--min-remaining N` on a manual run |
| One manual capture | `python scripts/capture_odds_snapshot.py --phase opening --dry-run` shows the plan and cost; without `--dry-run` it **spends credits** |
| Re-run the recorder | `python scripts/record_predictions.py --dry-run [--now ISO] [--horizon-hours N]` |
| Rebuild or update Elo | `python scripts/backfill_elo.py --update` (new games only), `--rebuild` (everything), `--model-id N` (one model), `--dry-run`, `--evaluate`, `--register` |
| Run the historical lab | `python scripts/model_lab.py [--seed N] [--configs N] [--max-seconds S] [--json file]`; add `--register --confirm-database nba_platform` to insert challengers |

### Official NBA injury reports and lineups

- **How to enable**: Automated PDF download is enabled by setting `INJURY_PDF_ENABLED=true` in `backend/.env` (default is `false`).
- **Operational limits**:
  - Game days only (0 downloads on days without games).
  - Maximum 3 downloads per day (`INJURY_MAX_DOWNLOADS_PER_DAY=3`): slot 1 after 09:00 local, slot 2 after 14:00 local, slot 3 within 60–120 minutes of first tip-off.
  - Minimum 60-minute cooldown between downloads.
  - Honest User-Agent: `ArchetypeNBA-research/1.0 (personal, low frequency)`.
  - Terms note: Owner authorization (2026-10-31, personal research, low frequency, never redistribute PDFs or raw data; see [`DECISIONS.md`](DECISIONS.md) D-62).
- **Scheduled execution**: In WSL/Linux, `nba-injuries.timer` executes `scripts/fetch_injuries.py` every 30 minutes (the script decides whether a download is due).
- **Testing**:
  ```bash
  python scripts/fetch_injuries.py --dry-run
  ```
- **Read API**: `GET /api/v1/injuries/latest` provides the latest snapshot with player entries grouped by team (`?include_available=true` to include Available players).
- **Props pipeline**: `services/injury_scraper.fetch_injury_report()` automatically uses real database rows if the latest snapshot is less than 36 hours old (otherwise marks `available=False` with reason `'stale'`).

### Injury-aware challenger model (`elo_injury`)

- **Historical walk-forward evaluation (read-only)**:
  Runs the walk-forward evaluation on completed seasons from `player_game_log` without modifying the database:
  ```bash
  python scripts/injury_model_eval.py [--seasons 5] [--min-mpg 15.0] [--bootstrap 2000]
  ```
  Prints a per-season and pooled summary table of fitted $\beta$, Elo vs Elo+injury log loss and Brier scores, gains with 95% bootstrap confidence intervals, and the upper-bound caveat.

- **Auditable challenger registration (`scripts/register_injury_challenger.py`)**:
  Registers an `elo_injury` challenger model under Rule 8 (creates a new `model_version` row; champion is untouched):
  ```bash
  # Step 1: dry run (evaluates walk-forward stats and displays proposed parameters without writes)
  python scripts/register_injury_challenger.py --dry-run

  # Step 2: live registration
  python scripts/register_injury_challenger.py
  ```
  - **Guards and Invariants**:
    1. **Idempotency**: If an active `elo_injury` challenger already exists, it reports the existing model and exits 0 without inserting duplicates.
    2. **Challenger limit**: Refuses with exit code 1 if `LEARNING_MAX_CHALLENGERS` (default 3) is already reached.
    3. **Statistical gate**: Refuses with exit code 1 if walk-forward log loss gain $\le 0.0$ or the 95% bootstrap CI lower bound is $\le -0.0005$.
  - **Train/Serve Skew Upper-Bound Caveat**: Historical walk-forward calibration evaluates actual binary absences from `player_game_log` (played vs did not play). Live serving uses expected absences from pre-game injury status probabilities ($\text{impact} \times (1 - p_{\text{avail}})$), which are noisier. The historical evaluation represents an upper bound on what live serving can achieve.
  - **Serving & Fallback**: Reads the latest `injury_report_snapshot` within 36 hours. If missing or stale (> 36 hours), no adjustment is applied and the model equals Elo exactly (noted in prediction logs). Unmatched player names are ignored and counted, never invented (Rule 3).

### League API and promotion notifications

- **Endpoint `GET /api/v1/league`**: A read-only JSON representation of the model league (champion, challengers with live evaluation metrics, paired $n$ vs the 150 target, log-loss gain with CI, margin NLL gain, Brier-vs-market gap, gate status in words, promotion/retirement history, and the last candidate proposal date). Responses are cached in-memory with a 5-minute TTL to avoid repeated bootstrap recomputations. The endpoint never writes to the database. An empty database returns status 200 with a clean empty structure.
- **Promotion notifications (Telegram)**: Whenever a role change commits during the `learn` step (`promote`, `rollback`, `retire`, or a new challenger is registered by the candidate lab), the system dispatches a plain-text Telegram message summarizing what happened, model names, evidence numbers (paired $n$, gain and CI), and the date.
- **How to enable notifications**: Notifications are opt-in. Set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in `backend/.env` to valid Telegram bot credentials (real values; placeholders containing `your_` are treated as unset). If either is unset, notifications are skipped. A notification failure never causes the tick to fail or roll back: any error is logged as a warning with the token masked, and the tick proceeds normally.

### Weekly View API and Frontend Page

- **Endpoint `GET /api/v1/week?days=7`**: A pure read-only endpoint (no writes to `model_prediction`, `simulated_bet`, or any table) providing scheduled games tipping off within the local day window (`America/Mexico_City`, query param `days` 1 to 14, default 7).
  - Computes on-demand model predictions for the champion Elo model (win probability, expected margin, sigma) and any active shadow challengers.
  - Matches stored market quotes: Pinnacle's de-vigged sharp probability (fair reference), best available price per side with bookmaker key and quote age in minutes.
  - Line-shopping and edge evaluation: computes model edge against Pinnacle fair close, and a read-only "would qualify" candidate flag per side using `analytics.betting_policy.evaluate_candidate` (flat strategy, edge $\ge$ 2 pp, EV $\ge$ 2%) with plain-language skip reasons when not eligible.
  - Official injury report: attaches non-Available players with status and reasons from the latest `injury_report_snapshot` per team, plus snapshot timestamp and a stale flag (older than 36 h). Empty database returns status 200 with `[]`.
- **Frontend page `/week`**: Next.js responsive page organized by day sections with game cards, team logos, model vs market win probability comparison bars, best available odds, candidate paper bet badges, team injury drawers, quote age warnings, day/team filters, and candidate-only toggle. Never gives betting advice (paper trading only). Accessible down to 360 px width.

### Qualitative Gemini AI Layer

- **Configuration location**: Configured in `backend/.env` via `GEMINI_MODEL` (default: `gemini-3.8-flash`) and `GEMINI_FALLBACK_MODEL` (default: `gemini-3.6-flash`).
- **Primary & Fallback Execution**: The qualitative injury analyzer (`app.services.gemini_analyzer.GeminiAnalyzerService`) queries `GEMINI_MODEL`. If the primary model responds with HTTP 404 (model retired or unknown) or HTTP 429 (quota exhaustion or rate limit), it automatically retries once with `GEMINI_FALLBACK_MODEL`. It never retries more than once.
- **Free-Tier Caveat (No Search Grounding)**: Grounding with Google Search is **not available** on the free tier API for these models. The analyzer must not request search grounding.
- **Thinking Tokens & Token Allocation**: `gemini-3.8-flash` spends thinking tokens during structured reasoning; requests allocate a generous `maxOutputTokens` (8,192) to avoid truncation.
- **No Unversioned Aliases**: Aliases such as `gemini-flash-latest` are prohibited because Google hot-swaps underlying model versions without notice, risking uncalibrated shifts in qualitative modifiers.
- **Heuristic Fallback**: If both Gemini models fail or `GEMINI_API_KEY` is unconfigured/empty, the system falls back seamlessly to deterministic rule-based quantitative heuristics (`engine_source="HEURISTIC"`, `model_used=None`).
- **Credential Hygiene**: API keys are supplied via HTTP headers (`x-goog-api-key`) rather than query parameters, and exception logging redacts the API key to guarantee zero key leakage in logs.

## 6. Web services (backend 38921, frontend 38920)

| Action | Command |
|--------|---------|
| Start both, wait for health, open the browser | `powershell -ExecutionPolicy Bypass -File .\scripts\start_services.ps1` (add `-NoBrowser` to skip the browser, `-RunPipeline` to also run the props pipeline `daily_runner.py`, which spends Odds API credits and Gemini quota) |
| Stop both | `powershell -ExecutionPolicy Bypass -File .\scripts\stop_services.ps1` |
| Start at log on (15 s delay) | `powershell -ExecutionPolicy Bypass -File .\scripts\setup_windows_autostart.ps1` (`-TestNow` to try it, `-Unregister` to remove it) |
| Health check | Open `http://127.0.0.1:38921/api/v1/health`; expect `status: ok` and `db_connected: true` |
| Logs | `logs\backend.log`, `logs\frontend.log` |

Notes:

- The backend runs through `scripts/run_backend.bat`, which **hardcodes a Windows Python path**; edit it for your machine. The backend process must be restarted to pick up code changes.
- The frontend is served with `next start`, so it needs `npm run build` first. The API address (`NEXT_PUBLIC_API_BASE`, default `http://localhost:8000`) is inlined at build time; how the production PC sets it for port 38921 is **unverified** (the repository scripts do not set it).
- In development use `python -m uvicorn app.main:app --reload --port 8000` from `backend/` and `npm run dev` (port 3000) from `frontend/`.
- The "shutdown" button in the UI calls `POST /api/v1/system/shutdown`, which has no CSRF or origin check. Keep the backend bound to `127.0.0.1`.

## 7. Linux and macOS

The project only runs in production on Windows. These equivalents are **unverified** here (nothing was run on Linux or macOS), but the tick is a plain command, stateless and protected by its own lock file, so any scheduler works.

Requirements for any scheduler: run `python backend/scripts/run_tick.py` every 15 minutes with `backend/` as the working directory, with the virtualenv's interpreter, and with the time zone set explicitly (the tick decides "today" with the machine's local zone; the project assumes `America/Mexico_City`).

### cron

```
TZ=America/Mexico_City
*/15 * * * * cd /opt/ArchetypeNBA/backend && ./.venv/bin/python -u scripts/run_tick.py >/dev/null 2>>../logs/tick.stderr.log
```

The tick writes `logs/tick.log` itself; stderr is kept only for crashes before logging starts. Some cron implementations ignore a `TZ=` line; if so, prefix the command with `TZ=America/Mexico_City` or set the system zone.

### systemd timer

`/etc/systemd/system/nba-tick.service`:

```
[Unit]
Description=ArchetypeNBA tick
After=network-online.target postgresql.service
Wants=network-online.target

[Service]
Type=oneshot
User=nba
WorkingDirectory=/opt/ArchetypeNBA/backend
Environment=TZ=America/Mexico_City
ExecStart=/opt/ArchetypeNBA/backend/.venv/bin/python -u scripts/run_tick.py
TimeoutStartSec=600
```

`/etc/systemd/system/nba-tick.timer`:

```
[Unit]
Description=Run the ArchetypeNBA tick every 15 minutes

[Timer]
OnCalendar=*:0/15
AccuracySec=30s

[Install]
WantedBy=timers.target
```

Enable and inspect:

```
sudo systemctl daemon-reload
sudo systemctl enable --now nba-tick.timer
systemctl list-timers nba-tick.timer
journalctl -u nba-tick.service -n 50
```

Pause with `sudo systemctl stop nba-tick.timer`, resume with `sudo systemctl start nba-tick.timer`. The `oneshot` service cannot overlap itself, and the lock file covers manual runs. The mirror of "only while logged on" does not exist here: a server ticks around the clock, which only helps capture. Do not register the tick on two machines.

## 8. Moving to another machine

Short form: pause and unregister on the old machine, export the database and `.env` through a secure channel (never git or chat), restore on the new machine, then register the tick there. The full procedure, with the cutover order, rollback and troubleshooting, is in [`DB_TRANSFER.md`](DB_TRANSFER.md); installation on the new machine is in [`SETUP.md`](SETUP.md). The scheduler examples in section 7 are system-wide; `DB_TRANSFER.md` (step 8) shows user-level variants (a systemd user timer with linger, a macOS launchd agent).

## 9. Backups

In WSL a systemd timer does this daily (`nba-backup.timer` -> `scripts/backup_db_wsl.sh`: export, verify, keep the newest 7 in `~/ArchetypeNBA-backups`); copy that folder to an external drive now and then. The manual procedure below still applies.

The database is the system's memory: odds that were not captured cannot be recovered on a free plan. Take an export every week; it is safe while the tick runs (a consistent snapshot):

```
cd backend
python scripts/db_transfer.py export
python scripts/db_transfer.py verify <path printed by export>.dump
```

`export` writes `<name>.dump` and `<name>.manifest.json` (exact row count of every table, sha256, Alembic revision) to `ArchetypeNBA-backups/`, a sibling folder of the repository; it refuses to write inside the repository, and `*.dump`, `*.manifest.json` and `backups/` are git-ignored. Copy both files to another disk or to private cloud storage. Old exports are never pruned automatically. Measured on 2026-10-26: the 229 MB database exported to a 17.3 MB dump (21 tables, 831,058 rows). Dumps and `.env` files never go in git or in chat. To restore, schedule the export or move machines, see [`DB_TRANSFER.md`](DB_TRANSFER.md) (sections 4 and 7).

## 10. Secrets and logs

| Item | Rule |
|------|------|
| `backend/.env` | Never committed; holds the database URL and API keys |
| Odds API key | The `apiKey` query parameter shows up in HTTP client INFO logs, so the `httpx` logger is set to WARNING; if you add logging, keep it that way and search a log for `apiKey` after any change |
| Database dumps | Never committed |

## 11. Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| A console window flashes and steals focus | The tick is launched with `python.exe` or a hidden PowerShell | Re-register with `register_tick_task.ps1` (it picks `pythonw.exe`); verify with a process watcher |
| `LastTaskResult` is `1` | A step errored | Read the first `[error]` line in `logs\tick.log` ([section 1](#when-a-tick-fails)) |
| No ticks in the log for hours | PC off or asleep; user logged off; task disabled; no network | `Get-ScheduledTask -TaskName NBA-Odds-Tick` (state `Ready`); log in; the task never wakes the PC |
| `missed closing lines: N` | The PC was off or no tick ran near tip-off | Nothing can recover them; keep the PC on at game time |
| Exporting `DATABASE_URL` in the shell has no effect | `config.py` loads `backend/.env` with `override=True`; the file wins | Edit the file, or run from a checkout that has no `.env`; tests and experiments that must not touch the real database need an explicit guard |
| `ModuleNotFoundError: No module named 'psycopg'` (or another missing package) | An old checkout or a stale virtualenv: the code uses the psycopg 3 driver (`postgresql+psycopg://`), which `backend/requirements.txt` has declared since PR #18 | Re-run `pip install -r backend/requirements.txt` in the virtualenv that runs the tick and the scripts |
| `password authentication failed for user "postgres"` | The default URL in `config.py` is used because `backend/.env` is missing or wrong (for example in a worktree) | Create or fix `backend/.env` |
| `no champion registered` or "model_version elo_538 1.1 is not registered" | Fresh database without the Elo champion | `cd backend; python scripts/backfill_elo.py --evaluate --register` |
| `alembic current` is not the head, or new code errors on a missing column | A migration was not applied | Follow [section 4](#4-lockstep-schema-deploy) |
| The season selector shows an empty 2026-27 | A season row for upcoming games exists with no player stats | `/api/v1/seasons` hides it unless it is active; never flip `is_active` casually: it drives the frontend default |
| `Season.id` order looks wrong | `season.id` is not chronological (2023-24 is id 1) | Order by `season_label` |
| Junk teams (`EST`, `WST`, `MAC`) or old abbreviations (`NJN`, `NOH`, `NOK`, `SEA`) | Historical data | Elo folds the old abbreviations onto the current franchise and counts only NBA game types 2, 4, 5, 6 |
| A postponed game costs one `nba_api` call every tick | Unresolved games are retried for up to 14 days | Known ([`ROADMAP.md`](ROADMAP.md)); free, but noisy |
| CLV coverage is low | Books move lines; the PC missed closings (35% of bets had a CLV on 2026-10-26) | Expected; read [`QUANT_MODULE.md`](QUANT_MODULE.md), section 7 |
| `nba_api` is slow or returns nothing | It can be slow or block datacenter IPs; calls use 30 to 45 second timeouts | Run from a residential connection; the next tick retries |
| `model_lab.py --register` or `propose` refuses | Missing `--confirm-database`, or 3 challengers are already active | Pass the database name; retire one first |
| Challenger rows show `challenger_error` or `challenger_unusable` in the record step | A challenger failed to load or predict | The champion is unaffected (it is committed first); read the traceback, then `model_league.py retire <id> --reason "..."` if it is broken |
| Backend serves old code after a pull | The process was not restarted | `stop_services.ps1` then `start_services.ps1` |
| Pages cannot reach the API | Ports differ: scripts use 38921 and 38920; the dev defaults are 8000 and 3000 | Match `NEXT_PUBLIC_API_BASE` to the backend you started |
| A scheduled run wrote UTF-16 logs or exit code 1 despite success | Wrapping Python in PowerShell mangles stderr (seen during the first registration) | The task runs Python directly; do not add a PowerShell wrapper |
| `git` prints LF to CRLF warnings on Windows | `core.autocrlf=true` | Noise |
| Code merged but a tick used old behavior | The tick runs the main checkout, which was not updated | `git pull` in the production checkout (between ticks) |

## Next step

New to the project? [`SETUP.md`](SETUP.md). Understanding what the numbers mean: [`QUANT_MODULE.md`](QUANT_MODULE.md).
