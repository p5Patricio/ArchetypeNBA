# Roadmap

What to build next and why, in priority order. Each item states the reason, how to know it is done, what can go wrong and the first concrete step. Item 1 is the next task for any agent picking the project up. Sizes (S, M, L) are rough judgments, not estimates from the plans. State as of 2026-10-26; the rules in [`AGENTS.md`](../AGENTS.md) (paper trading only, free tiers only, no fabricated data, ask before outward-facing actions) apply to every item.

## Quick path

1. Take item 1 unless the user says otherwise.
2. Items 5, 7 and 9 are small and independent; they are good warm-ups or parallel work.
3. Before starting anything, create `odd/tasks/<feature>.md` ([`odd/README.md`](../odd/README.md)) and work in a worktree ([`OPERATIONS.md`](OPERATIONS.md), section 4).

## Backlog at a glance

| # | Item | Size | Why now |
|---|------|------|---------|
| 1 | Injuries and lineups as a model signal | L | The one thing the baseline cannot see and the market can; also removes fabricated data |
| 2 | Totals and props models, with settlement | L | The data is already captured and paid for |
| 3 | Frontend model-league page | M | The league is invisible outside a terminal |
| 4 | Promotion notifications | S | A champion change should not go unnoticed |
| 5 | Shutdown endpoint CSRF and origin hardening | S | An unauthenticated endpoint can stop the services |
| 6 | Closing-quote presence record | M | Stale closes bias CLV |
| 7 | Postponed-game polling | S | Wasted calls and noise for up to 14 days |
| 8 | Second odds feed | M | Redundancy and more props; no sharp book |
| 9 | CI that runs the test suite | S | No automated check exists |
| 10 | Legacy cleanup | M | Dead code and confusing duplicates |
| 11 | Fix `props_engine.load_baselines_from_db` | S | It reads a SQLite file that does not exist |

Small fixes found while writing these docs are listed at the end ([hygiene](#hygiene-fixes)).

## 1. Injuries and lineups as a model signal

**Why.** Elo does not know who is playing. Injury status is the most important public information the market prices and the model ignores, and the likeliest source of real skill gains: the model-league arithmetic ([`QUANT_MODULE.md`](QUANT_MODULE.md), section 13) says more hyperparameter search cannot be detected in months. It also fixes a rule violation: today the injury code invents data.

**What was verified (2026-10-26).**

| Fact | Status |
|------|--------|
| `backend/app/services/injury_scraper.py` targets `https://official.nba.com/nba-injury-report-2024-25-season/` (a stale season URL) and parses a 6-column HTML table with a regex | Confirmed in the code on 2026-10-26 |
| The real page is a list of links to PDFs, so the regex never matches and `fetch_injury_report()` always returns `_get_fallback_sample_report()`: **invented injuries** (named players with invented statuses) that feed the Gemini layer in `props.py` and `daily_runner.py` | Fallback and call sites confirmed in the code; the page layout is the previous agent's finding |
| The official report is published as PDFs at `https://ak-static.cms.nba.com/referee/injury/Injury-Report_YYYY-MM-DD_HH_MMAM\|PM.pdf` (Eastern time), roughly every 15 minutes; the page is `https://official.nba.com/nba-injury-report-2026-27-season/`. Teams must submit statuses by 5 pm local the day before and update on game day. 2025-26 PDFs are reachable at the same path; how far back it goes is unknown | Previous agent's finding; **not re-verified here** (no network access in this task) |
| The page footer says NBA.com content may not be duplicated, redistributed or manipulated | Previous agent's finding. Low-frequency personal research use is a gray area |
| The scraper sends a browser-like `User-Agent`, not an honest one | Confirmed in the code |
| Lineups and starters | Unverified. Candidate: `nba_api` live or box-score endpoints (starting five appear shortly before tip-off); expect a short window before the tick's 30-minute closing window |

**Cautions the implementer must handle.**

1. **Train/serve skew.** History can be rebuilt from `player_game_log` (who played, minutes), which is post-game knowledge; at serving time only the pre-game status (Out, Doubtful, Questionable, Probable) exists. Train on features that exist at prediction time, such as an availability probability by status or a star-minutes-lost proxy, and verify with historical PDFs if obtainable.
2. **Leakage.** Every feature must be computable strictly before tip-off; use the same builder for training and prediction (the `FeatureState` pattern in `analytics/features.py`).
3. **Evaluation.** Run `scripts/model_lab.py` for the historical gate, then let the model run in shadow; promotion is decided by the `learn` step, not by hand.
4. **Tests stay offline.** Store a few real PDFs or text fixtures; never fetch in tests.
5. **Feature names are checked at load time.** `MarginFeaturesModel` raises if a stored model's `feature_names` differ from the code's `FEATURE_NAMES`. Adding features in place would make the existing challenger unloadable (`challenger_unusable`). The request to "register the new feature set as a new `margin_features` version" needs a code change first: version the feature set (for example a new family name or a feature-set registry) so the 12-feature model keeps loading. Found while documenting; confirm the design before coding.

**Acceptance criteria.**

- [ ] The user has answered the terms question (below) in writing.
- [ ] `injury_scraper` never returns invented data; an unavailable report is reported as unavailable, and a test proves no fallback sample exists.
- [ ] A parser turns a stored real report into structured rows, tested on offline fixtures.
- [ ] One feature builder serves training and serving; the leak test (perturbing the future leaves earlier features bit-identical) covers the new features.
- [ ] The new feature set is a distinct model version that does not break the existing one, passes the historical gate in `model_lab.py`, and runs in shadow. Promotion is left to the learning loop.
- [ ] [`QUANT_MODULE.md`](QUANT_MODULE.md) lists the new features; a decision entry is added to [`DECISIONS.md`](DECISIONS.md).

**Risks.** Terms of use; the PDF layout may change; historical PDFs may not exist far back; the mapping from status to availability has to be estimated, not assumed; timing against the 30-minute closing window; added requests must stay rare.

**First step.** Ask the user, one question: may the project download the NBA injury report PDFs automatically (a few requests a day, honest User-Agent, no redistribution of the PDFs or of derived raw data)? While waiting, do the part that needs no network: delete the fabricated fallback and make the props pipeline cope with "no report".

## 2. Totals and props models, with settlement

**Why.** The 3-credit game-lines call already captures totals for every game, and one player-props event per closing run is already stored. Nothing models or settles them, so that spend produces no evidence.

**Acceptance criteria.**

- [ ] Totals: a model registered through the same registry (the family protocol is currently `Prediction(p_home, mu, sigma)` for margins and needs a total-points form), recorded as shadow predictions with the same pre-tip-off guarantees.
- [ ] `settlement.grade_bet` handles `totals` (over and under, with pushes on integer lines); CLV works for it; the paper report shows it.
- [ ] Props: grading from `player_game_log` box scores, with `void` for players who did not play, after the name-matching rules are reviewed.
- [ ] Betting policy thresholds re-derived for the new markets and registered as a new `model_version` (rule 8).
- [ ] Offline tests; no extra credits beyond the guard.

**Risks.** Props samples are tiny at one event per tick; name matching (diacritics, suffixes); voids and minutes; the aggressive policy could over-bet a market with no evidence yet.

**First step.** Totals only: extend `grade_bet` and the report with tests, then a pace and scoring model scored on history by the lab.

## 3. Frontend model-league page

**Why.** The champion, challengers and gate progress are only readable through `scripts/model_league.py status`.

**Acceptance criteria.**

- [ ] A read-only endpoint over `league_report.build_league` (no write endpoint, no promote button).
- [ ] A page showing champion, challengers, paired `n` against 150, the gains with intervals, the gate in words and the promotion history.
- [ ] Types in `frontend/src/lib/api.ts`; `npx tsc --noEmit` clean; an endpoint test.

**Risks.** `build_league` runs a bootstrap per challenger, so cache the result for a few minutes; do not let a page trigger writes. Item 5 should land first or together, since it adds a second unauthenticated surface.

**First step.** Add `GET /api/v1/league` returning `build_league` as JSON with a short cache.

## 4. Promotion notifications

**Why.** A promotion, rollback or retirement changes which model bets. The user should hear about it without opening a terminal.

**Acceptance criteria.**

- [ ] A message on promote, rollback, retire and on a registered challenger, sent once per audit row.
- [ ] A failure to notify never fails the tick.
- [ ] Opt-in: it only runs when `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are set.
- [ ] Offline tests with a fake sender.

**Risks.** Duplicate messages across ticks (key them by the audit row id); leaking numbers to a chat; the existing `TelegramService` is shaped for props.

**First step.** In `learn_step`, after a committed role change, call a notifier with the `PassEntry` returned by the evaluation pass.

## 5. Shutdown endpoint CSRF and origin hardening

**Why.** `POST /api/v1/system/shutdown` stops both services and takes no parameters and no credentials. A request needs no CORS permission to be sent, only to be read (derived from the handler's signature), so another page open in the browser could stop the platform. It also relies on Windows-only `subprocess.CREATE_NO_WINDOW` and PowerShell.

**Acceptance criteria.**

- [ ] The handler rejects requests whose `Origin` or `Referer` is not in `CORS_ORIGINS`, and checks the `Host` header (DNS rebinding).
- [ ] The UI button keeps working; tests cover allowed and blocked origins.
- [ ] The backend stays bound to `127.0.0.1`.

**Risks.** Breaking the production port setup (38920 and 38921); some browsers omit `Origin` on same-origin GET but not on POST.

**First step.** Add an origin and host dependency to the router and its tests.

## 6. Closing-quote presence record

**Why.** The feed stores a row only when a book's own update stamp changes. A book that dropped a market looks "unchanged", so a stale quote can pass as the close and produce a false 0 CLV.

**Acceptance criteria.**

- [ ] Each capture records which (game, book, market, side) were present in the payload.
- [ ] CLV ignores or flags a closing quote that was absent at the closing capture; the report shows how many.
- [ ] A migration deployed in lockstep ([`OPERATIONS.md`](OPERATIONS.md), section 4); tests.

**Risks.** Table growth (small: tens of rows per game per capture); touching the capture path that spends credits.

**First step.** Design the presence table keyed by the capture marker and write it inside `_store_game_lines`.

## 7. Postponed-game polling

**Why.** A postponed game stays `scheduled` and costs one free `nba_api` call per tick for up to 14 days; it also muddies the stale-ratings guard.

**Acceptance criteria.**

- [ ] After the grace window and a bounded number of empty lookups, the game becomes `postponed` (the schema already allows it) and is no longer chased.
- [ ] A rescheduled game is picked up again by odds ingestion; `count_missed_closing` already excludes postponed games.
- [ ] Tests for the transition and for a game that is merely late.

**Risks.** Marking a late game as postponed.

**First step.** Add an attempt counter or an age rule in `results_sync` and test it.

## 8. Second odds feed

**Why.** Redundancy if The Odds API fails or the quota runs out, and more props coverage. The candidate found in 2026-10 is SportsGameOdds (free "Amateur" tier, about 2,500 events a month, props, 9 US books, **no Pinnacle**).

**Acceptance criteria.**

- [ ] A provider interface; the second feed writes its own `sportsbook` rows and has its own quota guard.
- [ ] The sharp reference stays Pinnacle: a feed without a sharp book never creates bets alone.
- [ ] Idempotent ingestion; offline tests from recorded fixtures.
- [ ] Terms and free-tier limits read and recorded first (the figures above date from the original research and may have changed).

**Risks.** Terms; duplicate games across feeds; accounting for two quotas.

**First step.** Re-read the provider's current terms and free-tier limits, then ask the user before integrating.

## 9. CI that runs the test suite

**Why.** There is no CI; every pull request relies on someone running `pytest` by hand and saying so. The suite is offline and deterministic (633 tests, about 2 minutes), so it fits a hosted runner.

**Acceptance criteria.**

- [ ] A GitHub Actions workflow on pull requests and pushes to `main`: Python 3.12, install `backend/requirements.txt`, `cd backend && python -m pytest -q`.
- [ ] Optionally `npx tsc --noEmit` in `frontend/`.
- [ ] Decide the runner: on Linux the four PowerShell tests skip; on `windows-latest` all 633 run.

**Risks.** Dependency drift (the requirements pin only lower bounds); minutes.

**First step.** Add `.github/workflows/tests.yml` on a branch and open a pull request.

## 10. Legacy cleanup

**Why.** The repository still carries the pre-PostgreSQL prototype: root `api.py`, `nba_data_processor.py`, `nba_player_analyzer.py`, `nba_player_data.py` and tracked `.xlsx` files, copies of the same modules in `backend/`, the Excel ETL (`backend/app/etl/pipeline.py`) and `seed_database.py`. A cleanup was proposed and not executed.

**Do not delete blindly (verified 2026-10-26).**

| Piece | Still used by |
|-------|---------------|
| `nba_player_analyzer` (and through it `nba_data_processor`) | `backend/app/services/report.py` (PDF scouting reports) and the root `api.py` |
| `app/etl/pipeline.py` | `app/services/data_update.py` and `backend/scripts/seed_database.py` |

**Acceptance criteria.**

- [ ] An inventory of importers (the table above, completed with a code search).
- [ ] `report.py` no longer imports a root-level module (move what it needs into `app/`).
- [ ] Removal in small pull requests, tests green after each; `README.md` updated.

**Risks.** The PDF report and the data-update endpoint break silently.

**First step.** Search for every importer and write the inventory into the plan file.

## 11. Fix `props_engine.load_baselines_from_db`

**Why.** It opens a SQLite file named `nba_platform.db` that does not exist (the platform database is PostgreSQL), logs a warning and falls back to **hardcoded star baselines**: static numbers standing in for data, against rule 3. Its season weights are keyed by `season.id` (3, 2, 1), but ids are not chronological.

**Acceptance criteria.**

- [ ] Baselines come from the application database through the existing repositories, weighted by season label recency.
- [ ] No static fallback: with no data, the endpoint says so.
- [ ] A test on in-memory SQLite.

**Risks.** The props UI changes behavior (fewer players) once the fabricated baselines go.

**First step.** Write the failing test against an in-memory database, then replace the SQLite access.

## Hygiene fixes

Small items found while documenting (2026-10-26). Each is a few lines.

| Item | Detail | Where |
|------|--------|-------|
| On-demand props spend credits outside the guard | `POST /props/run-analysis` and `GET /props/today?refresh=true` call The Odds API for up to 2 events x 3 markets (6 credits) plus Gemini | `backend/app/api/v1/props.py`, `backend/app/services/odds_api_service.py` |
| Props cache has no freshness check | The on-disk slate cache is served whatever its date | `backend/app/api/v1/props.py` |
| Hardcoded interpreter path | `run_backend.bat` and `run_pipeline.bat` embed the old PC's Windows Python path (the tick registration no longer depends on it, see below) | `scripts/` |
| Dumps are not git-ignored yet | `*.dump` and `*.manifest.json` are not in `.gitignore` on this branch (the database-transfer work adds them: pending merge) | `.gitignore` |
| Unused setting | `ETL_BATCH_SIZE` is defined and never read | `backend/app/config.py` |
| Production API address | The frontend inlines `NEXT_PUBLIC_API_BASE` at build time (default port 8000), the scripts use 38921, and no repository file sets it | `frontend/src/lib/api.ts` |
| README test count | It said 61 tests; now updated, but any number goes stale, so prefer a command over a count | `README.md` |

### Done since this list was written

| Item | Outcome |
|------|---------|
| Missing driver in the dependency list | PR #18: `backend/requirements.txt` and `backend/pyproject.toml` declare `psycopg[binary]>=3.1`; a clean virtualenv installs and passes the suite |
| Tick registration needed a hardcoded interpreter | PR #18: `register_tick_task.ps1` discovers Python (`-PythonExe`, `backend/.venv`, the `run_pipeline.bat` path only if it exists, then `PATH` ignoring the WindowsApps stub) and stops with a clear error otherwise |

## Next step

Start item 1 with the question to the user above.
