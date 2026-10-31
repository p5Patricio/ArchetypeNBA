# Decision log

The decisions that shaped the system, in the order the project made them, with the reason, what was rejected and what followed. Every entry is reconstructed from the feature plans in [`odd/`](../odd/README.md) (the project's decision history, written while the work was done) and from [`AGENTS.md`](../AGENTS.md); nothing here is new. Where a plan recorded no alternative, the entry says "Not recorded" instead of guessing. Dates are those of the plan section or the merge (PRs #1 to #12 merged on 2026-10-17, #13 to #17 on 2026-10-20, #18 and #19 on 2026-10-26).

## Quick path

1. Scan the index for the area you care about.
2. Open the entry for the context, the rejected alternatives and the consequences.
3. Follow the source link for the full reasoning and the numbers.

Entries are grouped by area below; the IDs follow the index. To change a decision: add a new entry that supersedes the old one, do not edit history. A betting-policy or model-parameter change is also a new `model_version` row (D-22).

## Index

| ID | Date | Decision | Area |
|----|------|----------|------|
| [D-01](#d-01-free-tiers-only) | 2026-10-06 | Free tiers only | Data |
| [D-02](#d-02-no-scraping-of-sites-whose-terms-forbid-it) | 2026-10-06 | No scraping of sites whose terms forbid it | Data |
| [D-03](#d-03-game-lines-first-props-later) | 2026-10-17 | Game lines first, props later | Scope |
| [D-04](#d-04-pinnacle-is-the-sharp-reference) | 2026-10-06 | Pinnacle is the sharp reference | Data |
| [D-05](#d-05-judge-by-clv-and-brier-against-the-close-not-roi) | 2026-10-17 | Judge by CLV and Brier against the close, not ROI | Method |
| [D-06](#d-06-capture-closing-lines-ourselves) | 2026-10-06 | Capture closing lines ourselves | Data |
| [D-07](#d-07-remove-every-fabricated-or-defaulted-quote) | 2026-10-06 | Remove every fabricated or defaulted quote | Data |
| [D-08](#d-08-de-vig-both-sides-and-treat-pushes-as-refunds) | 2026-10-06 | De-vig both sides, treat pushes as refunds | Method |
| [D-09](#d-09-postgresql-native-schema-sqlite-for-tests) | 2026-10-06 | PostgreSQL-native schema, SQLite for tests | Storage |
| [D-10](#d-10-native-postgresql-not-docker) | 2026-10 | Native PostgreSQL, not Docker | Storage |
| [D-11](#d-11-silence-the-http-client-logger) | 2026-10-06 | Silence the HTTP client logger | Security |
| [D-12](#d-12-explicit-capture-marker-table) | 2026-10-16 | Explicit capture-marker table | Capture |
| [D-13](#d-13-markers-only-after-a-successful-paid-call-props-tracked-apart) | 2026-10-16 | Markers only after a successful paid call, props tracked apart | Capture |
| [D-14](#d-14-one-logon-triggered-15-minute-tick) | 2026-10-17 | One logon-triggered 15-minute tick | Operations |
| [D-15](#d-15-stateless-tick-with-isolated-steps-a-lock-and-an-honest-exit-code) | 2026-10-17 | Stateless tick, isolated steps, lock, honest exit code | Operations |
| [D-16](#d-16-fivethirtyeight-style-elo-as-the-baseline-champion) | 2026-10-17 | 538-style Elo as the baseline champion | Model |
| [D-17](#d-17-elo-home-advantage-60-not-100) | 2026-10-17 | Elo home advantage 60, not 100 | Model |
| [D-18](#d-18-spreads-by-a-continuity-corrected-normal-sigma-from-walk-forward-residuals) | 2026-10-17 | Spreads by a continuity-corrected normal; sigma from walk-forward residuals | Model |
| [D-19](#d-19-which-games-count-for-elo) | 2026-10-17 | Which games count for Elo | Model |
| [D-20](#d-20-v1-markets-are-h2h-and-spreads-only) | 2026-10-17 | v1 markets are h2h and spreads only | Scope |
| [D-21](#d-21-the-betting-policy) | 2026-10-17 | The betting policy | Policy |
| [D-22](#d-22-policy-and-model-changes-are-new-model-versions) | 2026-10-17 | Policy and model changes are new model versions | Policy |
| [D-23](#d-23-policy-deliberately-aggressive-in-the-opening-weeks) | 2026-10-17 | Policy deliberately aggressive in the opening weeks | Policy |
| [D-24](#d-24-two-staking-strategies-with-separate-bankrolls) | 2026-10-17 | Two staking strategies with separate bankrolls | Policy |
| [D-25](#d-25-the-clv-rule) | 2026-10-17 | The CLV rule | Method |
| [D-26](#d-26-results-from-nba_api-into-player_game_log) | 2026-10-17 | Results from `nba_api` into `player_game_log` | Results |
| [D-27](#d-27-the-results-step-uses-the-network-only-when-needed) | 2026-10-17 | The results step uses the network only when needed | Results |
| [D-28](#d-28-season-from-the-tip-off-date-never-flip-is_active) | 2026-10-17 | Season from the tip-off date; never flip `is_active` | Data |
| [D-29](#d-29-champion-and-challengers-only-the-champion-bets) | 2026-10-20 | Champion and challengers; only the champion bets | Learning |
| [D-30](#d-30-per-model-elo-state) | 2026-10-20 | Per-model Elo state | Learning |
| [D-31](#d-31-model-families-behind-a-protocol-parameters-as-json) | 2026-10-20 | Model families behind a protocol, parameters as JSON | Learning |
| [D-32](#d-32-a-weekly-time-boxed-lab-with-a-strict-time-split) | 2026-10-20 | A weekly, time-boxed lab with a strict time split | Learning |
| [D-33](#d-33-live-paired-shadow-evaluation) | 2026-10-20 | Live paired shadow evaluation | Learning |
| [D-34](#d-34-the-promotion-gate) | 2026-10-20 | The promotion gate | Learning |
| [D-35](#d-35-retirement-thresholds-and-the-150-day-age) | 2026-10-20 | Retirement thresholds and the 150-day age | Learning |
| [D-36](#d-36-the-look-budget) | 2026-10-20 | The look budget | Learning |
| [D-37](#d-37-the-previous-champion-is-judged-on-games-since-its-demotion) | 2026-10-20 | The previous champion is judged on games since its demotion | Learning |
| [D-38](#d-38-the-last-elo-model-is-protected) | 2026-10-20 | The last Elo model is protected | Learning |
| [D-39](#d-39-atomic-swap-and-truthful-audit-rows) | 2026-10-20 | Atomic swap and truthful audit rows | Learning |
| [D-40](#d-40-a-challenger-can-never-break-the-champion) | 2026-10-20 | A challenger can never break the champion | Learning |
| [D-41](#d-41-a-kill-switch-and-a-dry-run-for-the-learning-loop) | 2026-10-20 | A kill switch and a dry run for the learning loop | Learning |
| [D-42](#d-42-a-failed-lab-holds-its-cadence-and-the-learn-step-has-a-budget) | 2026-10-20 | A failed lab holds its cadence; the learn step has a budget | Operations |
| [D-43](#d-43-pythonwexe-for-scheduled-work) | 2026-10-20 | `pythonw.exe` for scheduled work | Operations |
| [D-44](#d-44-develop-in-worktrees-deploy-in-lockstep) | 2026-10-20 | Develop in worktrees, deploy in lockstep | Workflow |
| [D-45](#d-45-pull-request-conventions) | 2026-10-17 | Pull request conventions | Workflow |
| [D-46](#d-46-independent-verification-for-money-like-logic) | 2026-10-20 | Independent verification for money-like logic | Workflow |
| [D-47](#d-47-ask-before-automating-downloads-from-the-nba-injury-report) | 2026-10-26 | Ask before automating downloads from the NBA injury report | Data |
| [D-48](#d-48-declare-the-psycopg-3-driver-in-the-dependency-files) | 2026-10-26 | Declare the psycopg 3 driver in the dependency files | Storage |
| [D-49](#d-49-discover-python-portably-when-registering-the-tick) | 2026-10-26 | Discover Python portably when registering the tick | Operations |
| [D-50](#d-50-a-cross-platform-transfer-tool-over-pg_dump-and-pg_restore) | 2026-10-26 | A cross-platform transfer tool over `pg_dump` and `pg_restore` | Operations |
| [D-51](#d-51-snapshot-consistent-export) | 2026-10-26 | Snapshot-consistent export | Operations |
| [D-52](#d-52-a-manifest-with-exact-row-counts-checked-on-both-ends) | 2026-10-26 | A manifest with exact row counts, checked on both ends | Operations |
| [D-53](#d-53-dumps-and-secrets-never-in-git) | 2026-10-26 | Dumps and secrets never in git | Security |
| [D-54](#d-54-one-pc-captures-at-a-time-in-a-fixed-cutover-order) | 2026-10-26 | One PC captures at a time, in a fixed cutover order | Operations |
| [D-55](#d-55-everything-runs-in-wsl2-systemd-timers-replace-task-scheduler) | 2026-10-27 | Everything runs in WSL2; systemd timers replace Task Scheduler | Operations |
| [D-56](#d-56-judge-the-paper-system-by-pinnacle-referenced-clv-per-game-add-two-staking-arms-and-a-report-only-selection-test) | 2026-10-28 | Judge the paper system by Pinnacle-referenced CLV per game | Method |
| [D-57](#d-57-totals-paper-bets-via-model-free-market-benchmark-model-market_pinnacle) | 2026-10-28 | Totals paper bets via model-free market benchmark model | Model |
| [D-58](#d-58-second-odds-feed-sportsgameodds-as-best-price-contributor-only) | 2026-10-28 | Second odds feed (SportsGameOdds) as best-price contributor only | Data |
| [D-59](#d-59-shadow-totals-model-totals_pace-with-evaluation-against-pinnacles-close) | 2026-10-28 | Shadow totals model (`totals_pace`) with evaluation against Pinnacle's close | Model |

## Data and scope

### D-01 Free tiers only
- **Date**: 2026-10-06
- **Decision**: No paid API or service without the user's explicit approval. The Odds API free plan (500 credits per month) is the primary odds feed; `nba_api` is the free results feed.
- **Context**: A personal research project with no revenue; the plan constraint "No paid services. Free tiers only".
- **Alternatives rejected**: Paid odds feeds (one named in the project notes costs about 5,000 USD per month).
- **Consequences**: A credit guard (`--min-remaining 25`), self-captured closing lines (D-06), a careful monthly budget ([`OPERATIONS.md`](OPERATIONS.md), section 2), and a second feed (SportsGameOdds free tier) kept on the roadmap.
- **Source**: [`quant-paper-trading.md`](../odd/tasks/quant-paper-trading.md) (Constraints, T1), [`AGENTS.md`](../AGENTS.md) sections 2 and 6.

### D-02 No scraping of sites whose terms forbid it
- **Date**: 2026-10-06
- **Decision**: Do not scrape ESPN's hidden API or OddsPortal. For anything new, read the terms first and ask the user when they are ambiguous.
- **Context**: ESPN's terms ban automated extraction; OddsPortal has terms of service and Cloudflare protection.
- **Alternatives rejected**: Both sites.
- **Consequences**: Only licensed APIs feed the system. The same rule governs the NBA injury report (D-47).
- **Source**: [`quant-paper-trading.md`](../odd/tasks/quant-paper-trading.md) (T1), [`AGENTS.md`](../AGENTS.md) rule 9.

### D-03 Game lines first, props later
- **Date**: 2026-10-17
- **Decision**: Build the loop on moneyline and spread first.
- **Context**: Game lines are the cheapest data under a 500-credit quota: one call (3 credits) covers every game, while props cost one credit per market per event.
- **Alternatives rejected**: Not recorded beyond the cost comparison.
- **Consequences**: Totals and props models and settlement are not built ([`ROADMAP.md`](ROADMAP.md) item 2).
- **Source**: [`elo-prediction-recorder.md`](../odd/tasks/elo-prediction-recorder.md) (Why), [`season-readiness.md`](../odd/tasks/season-readiness.md).

### D-04 Pinnacle is the sharp reference
- **Date**: 2026-10-06
- **Decision**: Use Pinnacle's de-vigged price as the estimate of the true probability and the benchmark for the model and for CLV.
- **Context**: Pinnacle's close is the best free estimate of the true probability. It is listed only in The Odds API's `eu` region but is reachable through the `bookmakers=` parameter.
- **Alternatives rejected**: Not recorded.
- **Consequences**: The default bookmaker list is Pinnacle plus six US books (at most 10 per call, one region-equivalent). A game without a Pinnacle pair gets predictions but no bet.
- **Source**: [`quant-paper-trading.md`](../odd/tasks/quant-paper-trading.md) (T1), [`elo-prediction-recorder.md`](../odd/tasks/elo-prediction-recorder.md) (Why).

### D-05 Judge by CLV and Brier against the close, not ROI
- **Date**: 2026-10-17
- **Decision**: The success measures are closing-line value and the Brier score against Pinnacle's de-vigged close. ROI is reported but not used to judge.
- **Context**: ROI needs thousands of bets to separate skill from luck; CLV and Brier converge faster.
- **Alternatives rejected**: Judging by ROI.
- **Consequences**: The report is built around CLV coverage and "model skill vs the close"; the known CLV biases are documented in [`QUANT_MODULE.md`](QUANT_MODULE.md), section 7.
- **Source**: [`elo-prediction-recorder.md`](../odd/tasks/elo-prediction-recorder.md) (E2), [`AGENTS.md`](../AGENTS.md) section 6.

### D-06 Capture closing lines ourselves
- **Date**: 2026-10-06
- **Decision**: Closing lines are captured live by the project.
- **Context**: Historical odds are paid-only, and there are no free historical props.
- **Alternatives rejected**: Buying historical data (violates D-01).
- **Consequences**: Closing lines are perishable: when the PC is off they are lost for good (13 of 43 tipped-off games on 2026-10-26). This drove the tick design (D-14) and the missed-closing counter.
- **Source**: [`quant-paper-trading.md`](../odd/tasks/quant-paper-trading.md) (T1), [`AGENTS.md`](../AGENTS.md) section 8.

### D-07 Remove every fabricated or defaulted quote
- **Date**: 2026-10-06
- **Decision**: A missing value stays missing. The service no longer returns hardcoded "consensus" lines, no longer overwrites quotes across bookmakers, and no longer defaults a missing under price to -110. Players without a live line are skipped.
- **Context**: Paper-trading metrics (ROI, CLV) are meaningless if quotes are fabricated or unattributed.
- **Alternatives rejected**: Any fallback that invents data ("a fallback that invents data is a bug").
- **Consequences**: Every quote carries its bookmaker; `under_odds` is optional; `get_slate_props_map` returns an empty map when not live. Violations still present: the injury scraper's fabricated report and the static star baselines ([`ROADMAP.md`](ROADMAP.md) items 1 and 11).
- **Source**: [`quant-paper-trading.md`](../odd/tasks/quant-paper-trading.md) (Problem, T3, T5), [`AGENTS.md`](../AGENTS.md) rule 3.

### D-08 De-vig both sides and treat pushes as refunds
- **Date**: 2026-10-06
- **Decision**: Edges are computed against the de-vigged (proportional) probability of both sides of a market, never against the vigged implied probability of one side. On integer lines a push returns the stake: EV is `p_win * d - 1 + p_push` per unit, with the half-point lines unchanged.
- **Context**: The original props engine computed its edge against the vigged implied probability and evaluated only the over side.
- **Alternatives rejected**: The vigged one-sided edge.
- **Consequences**: `devig_two_way` and per-side EV in `props_engine`; the same push-aware maths in the betting policy and settlement ([`QUANT_MODULE.md`](QUANT_MODULE.md), section 2).
- **Source**: [`quant-paper-trading.md`](../odd/tasks/quant-paper-trading.md) (Problem, T3, T6).

### D-47 Ask before automating downloads from the NBA injury report
- **Date**: 2026-10-26
- **Decision**: No automated download of the official NBA injury report PDFs until the user agrees.
- **Context**: The page footer states NBA.com content may not be duplicated, redistributed or manipulated. Low-frequency personal research use is a gray area.
- **Alternatives rejected**: Scraping without asking.
- **Consequences**: If approved: a few requests per day, an honest User-Agent, no redistribution of the PDFs or derived raw data, and offline test fixtures ([`ROADMAP.md`](ROADMAP.md) item 1).
- **Source**: [`AGENTS.md`](../AGENTS.md) rule 9 and section 10.

## Storage

### D-09 PostgreSQL-native schema, SQLite for tests
- **Date**: 2026-10-06
- **Decision**: The quant tables use native enums, generated columns, `NULLS NOT DISTINCT` unique constraints, a BRIN index and two views, written as hand-made migrations. Unit tests run on in-memory SQLite, with each dialect-specific feature expressed as a variant SQLite ignores.
- **Context**: Target database PostgreSQL 15; offline, fast tests.
- **Alternatives rejected**: Not recorded.
- **Consequences**: PostgreSQL 15 or newer is required; SQLite emulates the unique key in Python during ingestion; the views exist only in the migration (so use Alembic, never `create_all`); a `CHECK closing_price > 0` guards the generated CLV column.
- **Source**: [`quant-paper-trading.md`](../odd/tasks/quant-paper-trading.md) (T2).

### D-10 Native PostgreSQL, not Docker
- **Date**: 2026-10 (undated in the plan)
- **Decision**: The real database is a native PostgreSQL instance on port 5432.
- **Context**: The Docker container in `backend/docker-compose.yml` conflicts with the native instance on the same port.
- **Alternatives rejected**: Docker PostgreSQL.
- **Consequences**: The compose file exists but is unused; a machine with no native PostgreSQL may use it ([`SETUP.md`](SETUP.md)).
- **Source**: [`quant-paper-trading.md`](../odd/tasks/quant-paper-trading.md) (T8), [`AGENTS.md`](../AGENTS.md) sections 6 and 8.

### D-11 Silence the HTTP client logger
- **Date**: 2026-10-06
- **Decision**: The `httpx` logger is set to WARNING.
- **Context**: Its INFO lines print full URLs and The Odds API authenticates through an `apiKey` query parameter, so the key leaked into local logs (which were then redacted).
- **Alternatives rejected**: Not recorded.
- **Consequences**: The tick configures the same level; anyone adding logging must keep it that way.
- **Source**: [`quant-paper-trading.md`](../odd/tasks/quant-paper-trading.md) (T7), [`AGENTS.md`](../AGENTS.md) rule 5.

### D-28 Season from the tip-off date; never flip `is_active`
- **Date**: 2026-10-17
- **Decision**: The recorder and ingestion derive a game's season from its tip-off date, creating an inactive season row when none exists (2026-27). `is_active` is never changed by this code.
- **Context**: `game.season_id` was wrong for rows created before the season existed, which broke the 25% carryover on opening night; `is_active` drives the frontend default.
- **Alternatives rejected**: Not recorded.
- **Consequences**: `/api/v1/seasons` hides seasons without player stats unless they are active, and the financial service ignores empty seasons (PR #10). `Season.id` is not chronological: order by `season_label`.
- **Source**: [`elo-prediction-recorder.md`](../odd/tasks/elo-prediction-recorder.md) (E2, Notes), [`AGENTS.md`](../AGENTS.md) section 8.

## Capture and operations

### D-12 Explicit capture-marker table
- **Date**: 2026-10-16
- **Decision**: A dedicated table `odds_snapshot_capture` records that a game was captured (`opening`, `closing`, `closing_props`).
- **Context**: Inferring "already captured" from `odds_history.captured_at` re-spent credits when prices did not move (a run where no book changed a price inserts 0 rows), and a manual opening run near tip-off suppressed that game's closing capture.
- **Alternatives rejected**: Inference from `odds_history`.
- **Consequences**: The closing and props capture are idempotent and independent; the same markers feed CLV validity and the missed-closing report.
- **Source**: [`season-readiness.md`](../odd/tasks/season-readiness.md) (Problem, S2), [`AGENTS.md`](../AGENTS.md) section 6.

### D-13 Markers only after a successful paid call, props tracked apart
- **Date**: 2026-10-16
- **Decision**: A marker is written only after an HTTP 200 paid call; props are tracked with their own marker so games beyond the first N of a cluster are picked up in later runs.
- **Context**: A failed call must be retried; props events beyond N in a cluster were never captured.
- **Alternatives rejected**: Not recorded.
- **Consequences**: A props-only run costs only props credits. Worst case about 18 credits a day (about 504 a month); the credit floor of 25 protects the quota.
- **Source**: [`season-readiness.md`](../odd/tasks/season-readiness.md) (S2).

### D-14 One logon-triggered 15-minute tick
- **Date**: 2026-10-17
- **Decision**: A single scheduled task `NBA-Odds-Tick` starts at log on and repeats every 15 minutes, replacing the fixed-time tasks `NBA-Odds-Opening` (11:00) and `NBA-Odds-Closing` (every 30 minutes, 10:30 to 23:30). A time trigger was added so the repetition starts immediately and continues between sessions.
- **Context**: The user switches the PC on at variable hours, so fixed-time tasks miss captures; missed tip-offs cannot be backfilled on free tiers.
- **Alternatives rejected**: Fixed-time tasks.
- **Consequences**: The task runs only while the user is logged on and the PC is awake; every run must decide from database markers (D-15).
- **Source**: [`elo-prediction-recorder.md`](../odd/tasks/elo-prediction-recorder.md) (Design decisions, E3), [`season-readiness.md`](../odd/tasks/season-readiness.md) (S3, S4).

### D-15 Stateless tick with isolated steps, a lock and an honest exit code
- **Date**: 2026-10-17
- **Decision**: The tick keeps no state; each step is isolated so one failure never blocks the others (`record` always runs); a lock file prevents overlap; the exit code is 0 unless a step errored; a deliberately skipped step is not an error.
- **Context**: Repeated or missed runs must cost nothing and a failure in capture must not stop prediction recording.
- **Alternatives rejected**: Not recorded.
- **Consequences**: Steps live in an ordered registry (`DEFAULT_STEPS`); a lock older than 20 minutes is replaced; the task limit is 10 minutes.
- **Source**: [`elo-prediction-recorder.md`](../odd/tasks/elo-prediction-recorder.md) (E3, Acceptance criteria).

### D-42 A failed lab holds its cadence, and the learn step has a budget
- **Date**: 2026-10-20
- **Decision**: The `learn` step is limited to 4 minutes; the lab gets a deadline and returns a partial result. A lab that raises an unexpected error writes an `error:` proposal row that holds the weekly cadence for a day.
- **Context**: The task is limited to 10 minutes, and a broken lab would otherwise re-run on every 15-minute tick.
- **Alternatives rejected**: Retrying a failing lab on every tick.
- **Consequences**: A proposal is postponed (no marker) when less than 60 seconds of the budget remain.
- **Source**: [`model-learning-loop.md`](../odd/tasks/model-learning-loop.md) (design decision 8, Acceptance criteria); commit `b3a0ebe` (PR #15).

### D-43 `pythonw.exe` for scheduled work
- **Date**: 2026-10-20
- **Decision**: Scheduled and background Python runs with `pythonw.exe` directly.
- **Context**: A console flash from `python.exe` or from `powershell -WindowStyle Hidden` stole focus and interrupted the user's meetings and games.
- **Alternatives rejected**: A hidden PowerShell wrapper (it hides the window only after creating it). A wrapper also mangled stderr and the exit code during the first registration.
- **Consequences**: No stdout under the scheduler, so `logs/tick.log` is the only log; verify with a process watcher, not by eye.
- **Source**: [`AGENTS.md`](../AGENTS.md) rule 4 (PR #16); [`season-readiness.md`](../odd/tasks/season-readiness.md) (S4).

## Model and policy

### D-16 FiveThirtyEight-style Elo as the baseline champion
- **Date**: 2026-10-17
- **Decision**: The first model is an Elo with K=20, season carryover `0.75*r + 0.25*1505`, a margin-of-victory multiplier and an expected margin of `diff/28`, registered as `elo_538` 1.1.
- **Context**: A baseline measured honestly (Brier, CLV) is the foundation for any later self-improvement.
- **Alternatives rejected**: Not recorded.
- **Consequences**: Walk-forward Brier 0.2167 over the last five completed seasons; Elo is blind to offseason moves and injuries, so the market is better than the baseline ([`QUANT_MODULE.md`](QUANT_MODULE.md), section 13).
- **Source**: [`elo-prediction-recorder.md`](../odd/tasks/elo-prediction-recorder.md) (Design decisions, E1).

### D-17 Elo home advantage 60, not 100
- **Date**: 2026-10-17
- **Decision**: `HOME_ADVANTAGE = 60`, model version 1.1.
- **Context**: At the original 100 the home side was overrated by 1.2 to 1.9 points over 2021-22 to 2025-26; at 60 the bias is about 0.
- **Alternatives rejected**: 100.
- **Consequences**: The value was tuned in-sample on the same seasons, so the reported Brier is slightly optimistic. Sigma 14.14 is the registered value.
- **Source**: [`elo-prediction-recorder.md`](../odd/tasks/elo-prediction-recorder.md) (E1), [`AGENTS.md`](../AGENTS.md) section 6.

### D-18 Spreads by a continuity-corrected normal; sigma from walk-forward residuals
- **Date**: 2026-10-17
- **Decision**: Spread probabilities use a discrete (continuity-corrected) normal so integer lines yield win, push and loss probabilities. The margin sigma is estimated from walk-forward residuals and stored in `model_version.params`.
- **Context**: Integer spread lines push; a continuous normal cannot represent that.
- **Alternatives rejected**: Not recorded.
- **Consequences**: Use the registered sigma (14.14), not the unregistered fallback of 12.
- **Source**: [`elo-prediction-recorder.md`](../odd/tasks/elo-prediction-recorder.md) (Design decisions, E1, Notes).

### D-19 Which games count for Elo
- **Date**: 2026-10-17
- **Decision**: Only NBA game types 2, 4, 5 and 6 (regular season, playoffs, play-in, Cup final); games with a non-NBA team are skipped; historical abbreviations are folded onto the current franchise (NJN to BKN, NOH and NOK to NOP, SEA to OKC); 12 neutral-site games with two away rows are skipped.
- **Context**: Data facts verified against `player_game_log` on 2026-10-17 (the `team` table holds junk rows such as EST and WST).
- **Alternatives rejected**: Not recorded.
- **Consequences**: A team score is the sum of its players' points; one rating line follows a franchise through relocations.
- **Source**: [`elo-prediction-recorder.md`](../odd/tasks/elo-prediction-recorder.md) (Data facts, E1).

### D-20 v1 markets are h2h and spreads only
- **Date**: 2026-10-17
- **Decision**: Model and settle moneyline and spread; totals are not modelled and player props are not settled.
- **Context**: Cheapest data and a clean push-aware maths (D-03).
- **Alternatives rejected**: Not recorded.
- **Consequences**: Totals and props bets, if ever placed, stay pending ([`ROADMAP.md`](ROADMAP.md) item 2).
- **Source**: [`elo-prediction-recorder.md`](../odd/tasks/elo-prediction-recorder.md) (Design decisions, Follow-ups).

### D-21 The betting policy
- **Date**: 2026-10-17
- **Decision**: Blend the model with the fair probability 50/50; bet only if the raw edge over Pinnacle's de-vigged probability is at least 2 percentage points and the EV at the blended probability is at least 2%, at the best price across books at Pinnacle's line; horizon 20 hours, quotes at most 6 hours old, never at or after tip-off; skip a game if a team has an earlier unsettled game.
- **Context**: A model's disagreement with Pinnacle is mostly noise until a CLV record says otherwise, so it is shrunk.
- **Alternatives rejected**: Betting the raw model probability.
- **Consequences**: See [`QUANT_MODULE.md`](QUANT_MODULE.md), section 6, for every constant.
- **Source**: [`elo-prediction-recorder.md`](../odd/tasks/elo-prediction-recorder.md) (Design decisions, E2).

### D-22 Policy and model changes are new model versions
- **Date**: 2026-10-17
- **Decision**: A change to the betting policy or a model parameter is registered as a new `model_version` row.
- **Context**: Every bet must stay attributable to the rules that produced it (rule 8).
- **Alternatives rejected**: Editing the policy in place.
- **Consequences**: The learning loop's challengers and promotions rely on this.
- **Source**: [`elo-prediction-recorder.md`](../odd/tasks/elo-prediction-recorder.md) (E2), [`AGENTS.md`](../AGENTS.md) rule 8.

### D-23 Policy deliberately aggressive in the opening weeks
- **Date**: 2026-10-17
- **Decision**: Keep the v1 policy as the hypothesis even though it bets a lot (14 of 40 priced sides eligible, median raw edge 13.8% on the first dry run); judge it by CLV, not ROI.
- **Context**: Elo cannot see offseason roster changes, so it disagrees with Pinnacle early on; more samples give a faster verdict on whether the baseline has any edge.
- **Alternatives rejected**: Tightening the policy before data exists.
- **Consequences**: A daily 10-unit cap limits flat bets; early P/L is not evidence.
- **Source**: [`elo-prediction-recorder.md`](../odd/tasks/elo-prediction-recorder.md) (E2), [`AGENTS.md`](../AGENTS.md) section 6.

### D-24 Two staking strategies with separate bankrolls
- **Date**: 2026-10-17
- **Decision**: Every eligible bet is recorded twice: flat 1 unit and quarter Kelly, capped at 2% of bankroll per bet, 10% per day and 4% per game; the bankroll of each strategy is 100 plus its settled P/L.
- **Context**: Comparing staking methods on the same bets.
- **Alternatives rejected**: Not recorded.
- **Consequences**: One bet per (strategy, game, market, side), enforced by a unique index on `(prediction_id, strategy)`.
- **Source**: [`elo-prediction-recorder.md`](../odd/tasks/elo-prediction-recorder.md) (Design decisions, E2).

### D-25 The CLV rule
- **Date**: 2026-10-17
- **Decision**: CLV exists only for a game with a `closing` marker, taken from the same sportsbook, market, side and exact line, with the closing capture later than the bet; otherwise it is NULL (with the closing line recorded when the book moved).
- **Context**: A closing price from a stale opening snapshot must never count; a price at another line is not comparable.
- **Alternatives rejected**: Using the latest stored quote as the close.
- **Consequences**: Low coverage (35% of bets on 2026-10-26) and survivorship toward lines that did not move ([`QUANT_MODULE.md`](QUANT_MODULE.md), section 7).
- **Source**: [`elo-prediction-recorder.md`](../odd/tasks/elo-prediction-recorder.md) (Design decisions, E4 design).

### D-26 Results from `nba_api` into `player_game_log`
- **Date**: 2026-10-17
- **Decision**: Reuse the player-level `PlayerGameLogs` endpoint for a date window and keep `player_game_log` as the single source of truth for results (Elo reads it); a provider interface keeps tests offline.
- **Context**: Free, keyless, one call (about 1.2 seconds) per tick.
- **Alternatives rejected**: A second, team-level results path (a `LeagueGameLog` provider was the fallback if per-tick cost became too heavy).
- **Consequences**: A game is matched to a result by team pair and date (US date, plus or minus one day); rows already stored are never corrected if the NBA revises stats later.
- **Source**: [`elo-prediction-recorder.md`](../odd/tasks/elo-prediction-recorder.md) (E4 design, Follow-ups).

### D-27 The results step uses the network only when needed
- **Date**: 2026-10-17
- **Decision**: `nba_api` is called only when a game that tipped off more than 3 hours ago is not final; unresolved games are retried for up to 14 days.
- **Context**: A tick that has nothing to do must cost no network.
- **Alternatives rejected**: Polling on every tick.
- **Consequences**: A postponed game costs one free call per tick for up to 14 days ([`ROADMAP.md`](ROADMAP.md) item 7).
- **Source**: [`elo-prediction-recorder.md`](../odd/tasks/elo-prediction-recorder.md) (E4 design, Follow-ups).

## The learning loop

### D-29 Champion and challengers; only the champion bets
- **Date**: 2026-10-20
- **Decision**: `model_version.role` is champion, challenger or retired, with exactly one champion and at most 3 active challengers. Only the champion's predictions drive paper bets; challengers record predictions only. A demoted champion stays as a challenger.
- **Context**: Bankrolls must never be mixed.
- **Alternatives rejected**: Shadow bets for challengers.
- **Consequences**: Challengers are compared by proper scoring rules rather than P/L; the demoted champion enables a rollback.
- **Source**: [`model-learning-loop.md`](../odd/tasks/model-learning-loop.md) (design decision 1), [`AGENTS.md`](../AGENTS.md) section 6.

### D-30 Per-model Elo state
- **Date**: 2026-10-20
- **Decision**: `team_elo_rating` gets `model_version_id`, and the unique key becomes `(model_version_id, team_id, season_id, game_id)`; the existing rows are assigned to model 1.
- **Context**: A second Elo parameterization cannot persist its own state in a table with one rating set.
- **Alternatives rejected**: Not recorded.
- **Consequences**: A new Elo challenger replays about 25,000 games once, so the lab backfills at registration time to avoid a tick spike; the downgrade of this migration deletes other models' rating rows.
- **Source**: [`model-learning-loop.md`](../odd/tasks/model-learning-loop.md) (design decision 2, L1 notes).

### D-31 Model families behind a protocol; parameters as JSON
- **Date**: 2026-10-20
- **Decision**: Models implement `predict(...) -> Prediction(p_home, mu, sigma)` and are looked up by `model_version.name`. `margin_features` is a ridge regression for the margin plus a logistic regression for the win on leak-free features; coefficients, scaler and feature names live in `params`, with numpy-only inference.
- **Context**: A challenger must be loadable from the database alone.
- **Alternatives rejected**: Pickled models (no pickles).
- **Consequences**: A family unknown to the registry is skipped and counted (`challenger_unusable`); training uses scikit-learn but inference does not.
- **Source**: [`model-learning-loop.md`](../odd/tasks/model-learning-loop.md) (design decision 3, L1 notes).

### D-32 A weekly, time-boxed lab with a strict time split
- **Date**: 2026-10-20
- **Decision**: Candidates are selected on seasons [T-9, T-2] and gated on the hold-out [T-1, T], which no choice has seen; the historical gate is a hold-out log-loss gain of at least 0.0005 and parameters materially different from active models.
- **Context**: With about 2,600 held-out games per two seasons, differences of 0.001 log loss are not detectable, so history is only a pre-filter.
- **Alternatives rejected**: Choosing on the same data that reports the result.
- **Consequences**: The strict statistics belong to the live gate (D-34). The first run found one candidate (+0.0026) and rejected the best Elo search result (-0.0013).
- **Source**: [`model-learning-loop.md`](../odd/tasks/model-learning-loop.md) (Why, design decision 4, L2).

### D-33 Live paired shadow evaluation
- **Date**: 2026-10-20
- **Decision**: The unit of evidence is a final game on which both models recorded a prediction before tip-off. The primary metric is the paired per-game log-loss difference, with Brier, margin NLL and Brier against the market as secondary measures, and a seeded paired bootstrap for intervals.
- **Context**: Live data accumulates slowly (about 10 games a day), so an unguarded loop would chase noise.
- **Alternatives rejected**: Unpaired comparisons.
- **Consequences**: Late predictions are excluded and counted, never repaired.
- **Source**: [`model-learning-loop.md`](../odd/tasks/model-learning-loop.md) (Problem, design decision 5).

### D-34 The promotion gate
- **Date**: 2026-10-20
- **Decision**: Promote only if all hold: at least 150 paired games, at least 14 days live, the lower bound of the one-sided log-loss gain above 0 at confidence `1 - 0.05/(k*12)`, the margin-NLL gain bound above -0.02, the market Brier gap within 0.005 when at least 50 games have a market close, and at least 30 days since the last promotion.
- **Context**: Bonferroni over the number of challengers and over the look budget (D-36).
- **Alternatives rejected**: Not recorded.
- **Consequences**: Decision, numbers and seed are stored in `model_evaluation`; thresholds are overridable through `LEARNING_*` settings.
- **Source**: [`model-learning-loop.md`](../odd/tasks/model-learning-loop.md) (design decision 6).

### D-35 Retirement thresholds and the 150-day age
- **Date**: 2026-10-20
- **Decision**: Retire a challenger that is significantly worse (upper bound below 0) with at least 100 paired games, or that is older than 150 days with at least 300 paired games and no pass.
- **Context**: With this little signal a short deadline retires almost every candidate before the data can speak.
- **Alternatives rejected**: A 90-day age.
- **Consequences**: Most candidates are expected to end retired ([`QUANT_MODULE.md`](QUANT_MODULE.md), section 13).
- **Source**: [`model-learning-loop.md`](../odd/tasks/model-learning-loop.md) (design decision 7).

### D-36 The look budget
- **Date**: 2026-10-20
- **Decision**: Only decision-grade looks may promote, roll back or retire: at most one per challenger every 7 days and at most 12 per challenger-champion pairing, each with 5,000 bootstrap resamples at confidence `1 - 0.05/(k*12)`. Every other evaluation is a `monitor:` row.
- **Context**: An independent statistical attack showed that re-testing at every batch of games promoted equal-skill models about 20% of the time (daily looks 17.7%, weekly looks 15%, a single look 4%).
- **Alternatives rejected**: Re-testing a challenger at every new batch of games.
- **Consequences**: Measured with the real code, false promotion falls to about 1% and false retirement to about 5% for one challenger; detecting small gains usually will not reach significance.
- **Source**: [`model-learning-loop.md`](../odd/tasks/model-learning-loop.md) (design decision 7, look budget); commit `5c28133` (PR #15).

### D-37 The previous champion is judged on games since its demotion
- **Date**: 2026-10-20
- **Decision**: The model a promotion replaced is evaluated only on games since its demotion, and its days live and age count from the demotion.
- **Context**: The games that dethroned it are the very evidence that made it lose: counting them would retire it the next day and the rollback watch could never work.
- **Alternatives rejected**: Counting all paired games.
- **Consequences**: A rollback needs the same gate on fresh games.
- **Source**: [`model-learning-loop.md`](../odd/tasks/model-learning-loop.md) (design decision 7); commit `720f6d5` (PR #15).

### D-38 The last Elo model is protected
- **Date**: 2026-10-20
- **Decision**: The current Elo reference and the last active Elo model are never retired automatically; a manual retirement needs `--force`.
- **Context**: Rating updates and the lab baseline always need an Elo model. A verifier found that retiring the last one stalled the system.
- **Alternatives rejected**: Allowing retirement.
- **Consequences**: A protected retirement is recorded as `keep` with the reason.
- **Source**: [`model-learning-loop.md`](../odd/tasks/model-learning-loop.md) (design decision 7); commit `3811579` (PR #15); [`AGENTS.md`](../AGENTS.md) section 7.

### D-39 Atomic swap and truthful audit rows
- **Date**: 2026-10-20
- **Decision**: A promotion is one transaction holding the audit row and the role change (demote the old champion, then promote the new one). At most one promotion per pass. A failed swap rolls everything back and writes one `keep` row saying roles are unchanged; no row ever claims a promotion that did not happen.
- **Context**: The single-champion unique index allows one champion at a time, and the audit trail has to stay truthful when a swap fails (a fix made in PR #15).
- **Alternatives rejected**: Separate commits for the role change and the audit row.
- **Consequences**: When one challenger wins, the others are judged against the new champion next time.
- **Source**: [`model-learning-loop.md`](../odd/tasks/model-learning-loop.md) (Next step); commit `3811579` (PR #15).

### D-40 A challenger can never break the champion
- **Date**: 2026-10-20
- **Decision**: The champion is processed and committed first; each challenger runs in its own transaction. Import, prediction or database errors in a challenger are rolled back, logged and counted (`challenger_unusable`, `challenger_error`).
- **Context**: A verifier found challenger failures aborting the champion.
- **Alternatives rejected**: Processing all models in one transaction.
- **Consequences**: A broken experiment costs only itself.
- **Source**: [`model-learning-loop.md`](../odd/tasks/model-learning-loop.md) (L2); commit `c4d75fd` (PR #14).

### D-41 A kill switch and a dry run for the learning loop
- **Date**: 2026-10-20
- **Decision**: `LEARNING_AUTOPROMOTE` (default on) and `--dry-run` make the loop report instead of act. With the switch off, actionable decisions are recorded as `dry_run` and nothing changes.
- **Context**: Safety: reproducible seeds, no promotion on a small sample, all decisions auditable.
- **Alternatives rejected**: Not recorded.
- **Consequences**: Manual `promote` and `retire` remain available as audited overrides that never break the invariants.
- **Source**: [`model-learning-loop.md`](../odd/tasks/model-learning-loop.md) (design decision 9), [`AGENTS.md`](../AGENTS.md) section 5.

## Workflow

### D-44 Develop in worktrees, deploy in lockstep
- **Date**: 2026-10-20
- **Decision**: Development happens in a separate `git worktree`; a schema change is deployed with the tick paused: back up, disable the task, merge, pull, `alembic upgrade head`, dry runs, re-enable, one real tick.
- **Context**: The scheduled task executes the main checkout; new code cannot read an un-migrated schema and old code fails in its Elo write path after the migration.
- **Alternatives rejected**: Developing in the main checkout.
- **Consequences**: `backend/.env` lives only in the main checkout, so a worktree cannot reach the real database by accident (check `app.__file__`). An equivalence script once ran old code against the real database; no rows were written.
- **Source**: [`model-learning-loop.md`](../odd/tasks/model-learning-loop.md) (Constraints, L1, L1 notes), [`AGENTS.md`](../AGENTS.md) section 7.

### D-45 Pull request conventions
- **Date**: 2026-10-17
- **Decision**: Branch from `origin/main`; Conventional Commits; one cohesive pull request per work unit with a Chain Context section; pull requests over 400 changed lines are marked `size:exception` with the reason; merge commits, not squash; each pull request is merged before the next starts.
- **Context**: Stacked history must stay clean; the user gave a standing authorization to open pull requests and merge for this work (re-confirm each session).
- **Alternatives rejected**: Squash merges. CI was never configured, so `pytest` is run by hand and said so in the pull request.
- **Consequences**: Nineteen pull requests merged by 2026-10-26 ([`odd/README.md`](../odd/README.md)).
- **Source**: [`AGENTS.md`](../AGENTS.md) section 7; [`quant-paper-trading.md`](../odd/tasks/quant-paper-trading.md) (Delivery, T9).

### D-46 Independent verification for money-like logic
- **Date**: 2026-10-20
- **Decision**: Work is done by bounded writers and checked by a separate read-only verifier that tries to break the claims, for anything touching money-like logic, promotion or production scheduling.
- **Context**: The verifier found real defects several times: a season-selection regression, challenger failures aborting the champion, repeated-looks inflation, the last-Elo-model stall.
- **Alternatives rejected**: Writer self-verification only.
- **Consequences**: Each of those defects led to a fix recorded above (D-36, D-38, D-40).
- **Source**: [`AGENTS.md`](../AGENTS.md) section 7; [`model-learning-loop.md`](../odd/tasks/model-learning-loop.md).

## Portability and machine transfer

Added after the first version of this log: decisions of PR #18 (portable install) and PR #19 (database transfer tool), both merged on 2026-10-26.

### D-48 Declare the psycopg 3 driver in the dependency files
- **Date**: 2026-10-26
- **Decision**: `backend/requirements.txt` and `backend/pyproject.toml` list `psycopg[binary]>=3.1` instead of `psycopg2-binary`.
- **Context**: The code connects with `postgresql+psycopg://` (`backend/app/deps.py`, `backend/alembic/env.py`), which is the psycopg 3 driver, so a clean install that followed the requirements could not connect. It was found while checking this documentation against the code; the first version of the docs worked around it with an extra `pip install` step.
- **Alternatives rejected**: Documenting the extra install step (removed once the files were fixed). Changing the code back to psycopg 2 is not recorded as considered.
- **Consequences**: A clean virtual environment installs and passes the suite (verified in PR #18). An old checkout or a stale virtual environment fails with `No module named 'psycopg'`: re-run `pip install -r backend/requirements.txt`.
- **Source**: [`AGENTS.md`](../AGENTS.md) section 8 (Dependencies); commit `a81ecdf` (PR #18).

### D-49 Discover Python portably when registering the tick
- **Date**: 2026-10-26
- **Decision**: `scripts/register_tick_task.ps1` picks the interpreter in this order: `-PythonExe`, `backend/.venv`, the path inside `scripts/run_pipeline.bat` only if it exists on this machine, then the first `python.exe` on `PATH` (the empty Microsoft Store alias in `WindowsApps` is ignored). It stops with an error when none is found, and still swaps `python.exe` for `pythonw.exe` (D-43).
- **Context**: The script used to read the old PC's Python path out of `run_pipeline.bat`, or fall back to a bare `python`, which breaks on a new PC and can flash a console window.
- **Alternatives rejected**: The silent fallback to a bare `python`.
- **Consequences**: A new PC with `backend/.venv` needs no flag. `scripts/run_backend.bat` and `scripts/run_pipeline.bat` still hardcode the old path and need editing by hand.
- **Source**: `scripts/register_tick_task.ps1`; [`AGENTS.md`](../AGENTS.md) section 8; commit `a81ecdf` (PR #18).

### D-50 A cross-platform transfer tool over `pg_dump` and `pg_restore`
- **Date**: 2026-10-26
- **Decision**: A Python CLI (`backend/scripts/db_transfer.py`, logic in `backend/app/services/db_transfer.py`) wraps `pg_dump -Fc` and `pg_restore` with `export`, `verify`, `import` and `manifest` commands. It finds the PostgreSQL tools on `PATH`, through `--pg-bin` or in the usual install folders, and picks one whose major version is at least the server's.
- **Context**: The next agent will work on a different PC, which may not be Windows. The database holds irreplaceable data (odds captured every few minutes since 2026-10-06; closing lines cannot be backfilled) and there was no tool, no manifest and no `.env.example`.
- **Alternatives rejected**: Not recorded.
- **Consequences**: The logic is unit-testable with a fake process runner (124 new tests, 757 in total). A restore needs a server of the same major version as the source or newer.
- **Source**: [`db-transfer.md`](../odd/tasks/db-transfer.md) (design decisions 1 and 5, D1); [`DB_TRANSFER.md`](DB_TRANSFER.md).

### D-51 Snapshot-consistent export
- **Date**: 2026-10-26
- **Decision**: `export` takes one consistent snapshot of the whole database (`pg_export_snapshot` with `pg_dump --snapshot`), so the exact row counts and the dump come from the same instant. Files are written as `.part` and renamed when complete, and the default folder is outside the repository.
- **Context**: The tick writes to the database every 15 minutes; counts and dump must agree for the restore check to mean anything.
- **Alternatives rejected**: Not recorded.
- **Consequences**: An export is safe while the tick runs (smoke-tested while 88,000 rows were being inserted), but only a paused tick guarantees that the dump holds everything captured so far, hence the pause in the cutover.
- **Source**: [`db-transfer.md`](../odd/tasks/db-transfer.md) (design decision 2, D1); [`DB_TRANSFER.md`](DB_TRANSFER.md) step 1.

### D-52 A manifest with exact row counts, checked on both ends
- **Date**: 2026-10-26
- **Decision**: Each export writes `<name>.manifest.json` with the exact row count of every table, the Alembic revision (in the database and in the code), the server and `pg_dump` versions, the database time zone, the size, the sha256 and the git commit. `verify` checks the sha256 and that `pg_restore` can read the archive. `import` verifies first, requires an empty target (or `--replace --confirm-database NAME`), restores in a single transaction (all or nothing, `--exit-on-error`), runs `ANALYZE`, then compares the exact count of every table and the Alembic revision, exiting non-zero on any mismatch.
- **Context**: A restore that silently loses rows would lose data nobody can recapture.
- **Alternatives rejected**: Not recorded.
- **Consequences**: Validated on 2026-10-26 against the live database: 21 tables, 831,058 rows, a 17.3 MB dump (from 229 MB); the restored scratch copy matched every table, and `alembic current`, `paper_report.py`, `model_league.py status` and `run_tick.py --dry-run` reproduced the live results.
- **Source**: [`db-transfer.md`](../odd/tasks/db-transfer.md) (design decisions 2 to 4, D1, D3); [`DB_TRANSFER.md`](DB_TRANSFER.md).

### D-53 Dumps and secrets never in git
- **Date**: 2026-10-26
- **Decision**: Dumps and manifests travel by USB, private cloud storage or `scp`, never through git: `.gitignore` blocks `*.dump`, `*.manifest.json` and `backups/`, and `export` refuses to write inside the working tree. The database password travels only in the subprocess environment (`PGPASSWORD`), never in arguments, logs or the manifest. `backend/.env` travels separately through a secure channel.
- **Context**: The dump holds odds-provider data and private paper-trading records, and is large.
- **Alternatives rejected**: Committing dumps (size, odds-provider terms).
- **Consequences**: Machine-level environment variables that feed `Settings` (on the original PC, `GEMINI_API_KEY` and `TELEGRAM_BOT_TOKEN`) are not in the dump or necessarily in `.env`; the runbook tells the reader to list their names, never their values, and recreate them.
- **Source**: [`db-transfer.md`](../odd/tasks/db-transfer.md) (design decisions 6 and 7, Notes); [`AGENTS.md`](../AGENTS.md) rule 5.

### D-54 One PC captures at a time, in a fixed cutover order
- **Date**: 2026-10-26
- **Decision**: Moving machines follows one order: pause the tick on the old PC, take the final export, verify it, copy both files and check the hash, restore on the new PC, set `backend/.env`, register the tick there, and unregister it on the old PC only after a healthy tick on the new one.
- **Context**: Two PCs running the tick would spend the same Odds API key quota and write diverging databases that cannot be merged.
- **Alternatives rejected**: Running both PCs in parallel during the move.
- **Consequences**: There is a gap in which nothing is captured; closing lines of games that tip off in it are lost for good, so the cutover is done in the morning, before the first tip-off. The old database stays untouched for a few days as a fallback.
- **Source**: [`db-transfer.md`](../odd/tasks/db-transfer.md) (design decision 8); [`DB_TRANSFER.md`](DB_TRANSFER.md) sections 2, 4 and 5.

### D-55 Everything runs in WSL2; systemd timers replace Task Scheduler
- **Date**: 2026-10-27
- **Decision**: The project moved from native Windows to WSL2 Ubuntu 24.04: native PostgreSQL 18 on port 5433, the tick as a systemd user timer (every 15 min, `Persistent=true`, linger on), a daily backup timer (`scripts/backup_db_wsl.sh`, 7 kept), the web services started by `scripts/start_services_wsl.sh`, and a Windows Startup stub (`NBAAnalyticsWSL.vbs`) that keeps the distro alive and opens the browser.
- **Context**: The owner wanted the whole project in WSL. WSL does not start by itself at boot, so one Windows-side trigger is unavoidable; WSL uses mirrored networking, so Windows and WSL share `localhost` ports.
- **Alternatives rejected**: Docker Postgres (rejected earlier, see section 6 of `AGENTS.md`); keeping the Windows tick; PostgreSQL on 5432 (a Windows server may hold that port under mirrored networking).
- **Consequences**: The cutover followed D-54: tick paused, final export, verified restore (all 21 tables matched), WSL tick registered, Windows task removed; the gap was about five minutes, at night. The tick only runs while the distro is alive. The shutdown endpoint became cross-platform. A bare `pytest` hangs in this network mode, so the documented command is `python -m pytest tests -q`.
- **Source**: [`WSL.md`](WSL.md); [`DB_TRANSFER.md`](DB_TRANSFER.md).

### D-56 Judge the paper system by Pinnacle-referenced CLV per game; add two staking arms and a report-only selection test
- **Date**: 2026-10-28
- **Decision**: The evidence of skill is the mean log-odds CLV against Pinnacle's de-vigged close with one observation per game (flat and Kelly bet the same selections), reported with its standard error and the sample still needed; same-book CLV stays as a labelled optimistic figure. Two strategies are added next to the existing ones: `kelly_shrunk` (stake multiplier scaled by edge^2 / (edge^2 + sd^2), sd an estimate of the model's probability error) and `market_edge` (no model: bet when the best price beats Pinnacle's fair probability by the minimum EV). The candidate lab records Reality Check, SPA and DM-HLN p-values but only gates on them when `LAB_MULTITEST_GATE` is on.
- **Context**: A research pass (`RESEARCH_BETTING_IMPROVEMENTS.md`, claims checked against registries, primary pages and our own data) found that the same-book CLV (+3.7%) was an artefact: against Pinnacle it was +0.34% (t 0.27, 23 games), and a +1% edge needs about 220 independent bets.
- **Alternatives rejected**: Judging by ROI (needs about 15,000 bets for +2%); replacing the fixed quarter-Kelly outright (rule 8: a new strategy keeps the old bankroll comparable); a hard multiple-testing gate by default (a silent policy change).
- **Consequences**: New enum values need the lockstep deploy; the two arms are hypotheses and carry no weight until their CLV against Pinnacle is positive with t above 2.
- **Source**: [`RESEARCH_BETTING_IMPROVEMENTS.md`](RESEARCH_BETTING_IMPROVEMENTS.md); [`betting-improvements.md`](../odd/tasks/betting-improvements.md).

### D-57 Totals paper bets via model-free market benchmark model (`market_pinnacle`)
- **Date**: 2026-10-28
- **Decision**: Totals (over/under) paper bets are evaluated and placed strictly by the model-free `market_edge` strategy (comparing best sportsbook odds against Pinnacle's de-vigged fair over/under at the exact same total line). The champion forecasting model and model-driven strategies (`flat`, `kelly_fractional`, `kelly_shrunk`) never bet totals. To satisfy the `simulated_bet.prediction_id` NOT NULL foreign key while upholding AGENTS.md rule 8 ("every bet must stay attributable") and preventing artificial inflation of champion prediction counts, totals predictions are attached to a dedicated model-free benchmark model (`name='market_pinnacle'`, `version='1'`, `params={"family": "market"}`, `role='benchmark'`, `notes="Pinnacle's de-vigged probability, not a forecasting model"`). The role `benchmark` is added to `MODEL_ROLES` in `app/models.py` and guarded by Alembic migration `a2c4e6f8b1d3`. All model league components, promotion logic, evaluation audits, and active forecasting model reports strictly ignore benchmark rows.
- **Context**: In the initial draft of WP-T, totals predictions were attached to the champion's `model_version_id` to avoid a schema migration. That design was rejected because it violated AGENTS.md rule 8 by attributing to the champion predictions it never made, distorted the champion's prediction counts, and broke model attribution. The correct architecture introduces a distinct `benchmark` role and `market_pinnacle` row so totals predictions truthfully represent Pinnacle's fair probabilities.
- **Alternatives rejected**:
  1. Attaching totals predictions to the champion's `model_version_id` (rejected: violates AGENTS.md rule 8; falsifies champion attribution; inflates champion prediction tallies).
  2. Making `simulated_bet.prediction_id` nullable (rejected: loses the audit trail of what probability justified the bet).
  3. Forecasting model for totals: market audit demonstrated closing totals error sd ~17.7 points across 39 games and no verified evidence of statistical edge over Pinnacle's close.
- **Consequences**: Hand-written Alembic migration `a2c4e6f8b1d3` updates `ck_model_version_role` to include `'benchmark'`. The model league and promotion gates remain 100% untouched and pure forecasting models (h2h/spreads). The champion's prediction counts remain strictly attributable to games it predicted.
- **Source**: WP-T2; [`QUANT_MODULE.md`](QUANT_MODULE.md); [`DECISIONS.md`](DECISIONS.md); migration `a2c4e6f8b1d3`.

### D-58 Second odds feed (SportsGameOdds) as best-price contributor only
- **Date**: 2026-10-28 (updated 2026-10-31 after first live response probe)
- **Decision**: Integrate SportsGameOdds as a second odds provider (free Amateur tier: 2,500 objects/month, 10 requests/minute, 9 US books, no Pinnacle) behind a generic `OddsProvider` protocol (`services/odds_providers/base.py`). The feed is completely disabled until `SPORTSGAMEODDS_API_KEY` is provided. It NEVER creates games (events match existing `Game` rows by team names/abbreviations and commence time within a 6-hour tolerance; unmatched events are logged and skipped), and because it lacks a sharp bookmaker, it NEVER generates paper bets or fair probability references on its own. Its quotes are stored as ordinary `odds_history` rows to serve solely as best-price execution candidates and market cross-checks. A conservative quota guard checks `/account/usage` and tracks monthly objects consumed in `logs/sportsgameodds_usage.json`, stopping at `SPORTSGAMEODDS_MIN_REMAINING_OBJECTS` (default 100). A probe CLI `scripts/sgo_probe.py` allows inspecting live API responses safely without scheduling.
- **Live Response Probe (2026-10-31)**:
  - The parser was exercised against a live response on 2026-10-31 via `scripts/sgo_probe.py` (`GET /events?leagueID=NBA&oddsAvailable=true&limit=2`).
  - Findings: Confirmed 9 US books (FanDuel, DraftKings, BetMGM, Caesars, ESPN BET, Bovada, PointsBet, Unibet, William Hill) and **no Pinnacle**. The live response contained a top-level string field `notice` ("Response is missing N bookmaker odds. Upgrade your API key to access all data from this query.") indicating plan limits, which is logged once per call at INFO without dumping the payload.
  - Filter bug fix: Each event's `odds` map contained 846–1056 entries with team totals, quarter/half totals, eo, ml3way, and player props. The initial parser accepted any `statEntityID` for `betTypeID: ou`, causing team totals and player props to pollute game totals quotes. Fixed so that `ou` game totals require `statEntityID == 'all'`, and `ml`/`sp` require `statEntityID in ('home', 'away')` with consistent `sideID`.
  - Tick status: Ingestion into the scheduled tick remains **NOT** wired; the feed is only probed with `scripts/sgo_probe.py`.
- **Context**: The Odds API 500 credit/month quota provides 1 props event per closing run; a second free feed adds redundancy and best-price line shopping across books like Caesars and ESPN BET that are not in our primary feed call.
- **Alternatives rejected**: Using SportsGameOdds for paper-trading fair value (rejected: lacks a sharp book like Pinnacle); creating `Game` entities from secondary feeds (rejected: avoids duplicating games or conflicting schedules); polling without quota guards.
- **Consequences**: No database schema change needed. When enabled, more bookmakers are tracked in `sportsbook` and `odds_history`. The system remains offline and untouched during ticks until the owner configures a valid key.
- **Source**: [`ROADMAP.md`](ROADMAP.md) item 8; `app/services/odds_providers/sportsgameodds.py`; WP-S4.

### D-59 Shadow totals model (totals_pace) with evaluation against Pinnacle's close
- **Date**: 2026-10-28
- **Decision**: Introduce a pure statistical totals forecasting model (`totals_pace` v1, role `'shadow'`) implemented in `app/analytics/totals_model.py`. The model estimates expected total $\mu$ as the pace/efficiency average of each team's rolling combined points (scored + allowed over last N=10 games, shrunk toward the season league mean with prior weight 5.0) and residual standard deviation $\sigma$ from the same rolling procedure over past games only (default 17.7 points). Binary probability of over is computed as $p_{\text{over}}(\text{line}) = 1 - \Phi((\text{line} - \mu) / \sigma)$, ignoring push mass on half lines. The model runs in shadow mode only: the recorder idempotently creates `totals_pace` v1 and stores predictions for every game that has fresh totals quotes at Pinnacle's line, but NEVER generates paper bets of any kind. An evaluation service function and reporting sections in `scripts/market_audit.py` and `scripts/paper_report.py` measure $n$, Brier score, log loss, paired differences with bootstrap 95% intervals against Pinnacle's de-vigged closing line, and model mean total error with standard deviation (displaying "insufficient data" when $n < 30$). All model league components, promotion logic, and active forecasting model reports strictly ignore shadow models.
- **Context**: Closing totals error has standard deviation ~17.7 points and public box-score models offer no proven edge over Pinnacle's closing lines. The shadow arm implements closed-loop measurement to test whether a simple model can approach the market before any model-driven betting policy is considered.
- **Alternatives rejected**:
  1. Paper betting totals with the totals model or champion (rejected: closing error sd ~17.7 points indicates no verified edge; betting would risk paper bankroll on unproven forecasts).
  2. Registering totals model as a challenger in the model league (rejected: model league is strictly for head-to-head game outcome forecasting models competing for champion status; totals are an independent market).
- **Consequences**: Hand-written Alembic migration `b3d5f7a9c1e4` updates `ck_model_version_role` to include `'shadow'`. The recorder stores totals predictions for `totals_pace` alongside `market_pinnacle`. The model league and promotion gates remain isolated.
- **Source**: WP-S1; [`QUANT_MODULE.md`](QUANT_MODULE.md); [`DECISIONS.md`](DECISIONS.md); migration `b3d5f7a9c1e4`.

### D-60 Persist player-prop quotes and evaluate props shadow model (props_nb) against book close
- **Date**: 2026-10-28
- **Decision**: Persist closing player-prop quotes in `odds_history` for requested markets (`player_points`, `player_rebounds`, `player_assists`, `player_pra`) with truthful `quotes_seen` / `quotes_inserted` capture tracking. Map player names to database players using diacritic and standard suffix stripping (`Jr.`, `Sr.`, `II`, `III`, `IV`, `V`), restricted to candidate players from the two teams of the game; ambiguous or unmatched names are skipped and counted. Register shadow model `props_nb` v1 with role `'shadow'` (`model_registry.py`). Record shadow predictions for quoted lines using negative-binomial machinery (`analytics/props_engine.py`); players lacking baselines are skipped without fabrication. Zero paper bets are created. Evaluate settled games against the SAME book's de-vigged closing over/under pair (`devig_two_way`) at or before tip-off; derive actual stats from `player_game_log`; classify as over/under/push, or `VOID` when player did not play (0 minutes or no log). Report $n$, Brier score, log loss, paired bootstrap 95% intervals, void count, and unmatched name count in `market_audit.py`, `paper_report.py`, and `GET /api/v1/paper/summary` (with $n < 30$ guard). Shadow model rows remain completely isolated from the model league, promotion, learn, and champion attribution.
- **Context**: 40 closing props captures spent 40 credits and saw 12,325 quotes but inserted 0 due to missing name resolution and game scoping. Credits bought no empirical evidence. Props paper bets are deliberately deferred because there is no universal sharp reference for props and the sample is tiny; the shadow evaluation loop measures calibration before any betting is entertained.
- **Alternatives rejected**:
  1. Paper betting player props (rejected: soft books and no sharp closing benchmark; risk of false edge on tiny samples). Revisit only when shadow evaluation reaches $n \ge 200$.
  2. Fabricating missing player baseline data or consensus odds (rejected: strict Rule 3 violation; uncalibrated or missing players are skipped and counted).
- **Consequences**: `odds_history` captures high-fidelity closing player props quotes. Truthful quote metrics on capture markers. Clean, settlement-free evaluation of negative-binomial props calibration against bookmakers.
- **Source**: WP-S2; [`QUANT_MODULE.md`](QUANT_MODULE.md); [`DECISIONS.md`](DECISIONS.md); [`ROADMAP.md`](ROADMAP.md).

### D-61 Qualitative Gemini layer model upgrade to gemini-3.8-flash with gemini-3.6-flash fallback
- **Date**: 2026-10-31
- **Decision**: Upgrade default `GEMINI_MODEL` from `gemini-3.6-flash` to `gemini-3.8-flash`. Introduce `GEMINI_FALLBACK_MODEL` defaulting to `gemini-3.6-flash`. When calling the Gemini API, attempt the primary model; on HTTP 404 (model id unknown or retired) or HTTP 429 (quota/rate limit), retry exactly once with `GEMINI_FALLBACK_MODEL`. Never retry more than once. Log the model that answered successfully at INFO level without exposing credentials. Include the resolved model id (`model_used`) in `SlateAnalysisResult` so the props UI and daily runner report reflect actual execution provenance. Preserve the deterministic heuristic fallback when both models fail or credentials are unset. Grounding with Google Search is deliberately not requested (not supported on the free tier API).
- **Context**: Verified on 2026-10-31: `gemini-3.8-flash` is a GA (stable) model in the Gemini API model list, free of charge on the free tier, offering 1,048,576 input and 65,536 output tokens with structured JSON output. Because the model allocates thinking tokens during reasoning, `maxOutputTokens` is generously allocated (8,192). `gemini-3.6-flash` remains fully functional without a shutdown date and serves as an ideal resilient fallback.
- **Alternatives rejected**:
  1. Dynamic aliases like `gemini-flash-latest` (rejected: aliases hot-swap underlying weights without notice, breaking repeatability and auditability).
  2. Google Search grounding (rejected: unavailable on the free tier API for these models; would trigger API rejection).
  3. Indefinite model cycling or unbounded retries (rejected: limits latency and preserves quota; strictly at most one fallback retry).
- **Consequences**: No database schema change. Zero regression in props workflow. Offline tests verify primary success, fallback upon 404/429, heuristic fallback on total exhaustion, and zero key leakage in logging streams.
- **Source**: WP-G; `backend/app/config.py`; `backend/app/services/gemini_analyzer.py`; `docs/OPERATIONS.md`.

### D-62 Official NBA injury report automated download, storage and pre-game lineup snapshots
- **Date**: 2026-10-31
- **Decision**: Authorize automated download of the official NBA injury report PDFs for personal research under strict operational limits: game days only, at most 3 times per day (`INJURY_MAX_DOWNLOADS_PER_DAY=3`), honest User-Agent `"ArchetypeNBA-research/1.0 (personal, low frequency)"`, guarded by `INJURY_PDF_ENABLED` (default `false` in code, enabled in `.env`). Store reports idempotently in `injury_report_snapshot` (unique by sha256) with detailed player rows in `injury_entry` (player_id mapped with `normalize_player_key`, team-scoped when possible; unresolved remain null and counted). Capture pre-game starters and inactives as `lineup_snapshot` rows via `scripts/log_lineups.py`. The props pipeline (`services/injury_scraper.py`) queries the latest snapshot (< 36 hours old, else returns `available=False` with reason `'stale'`) to feed real items to Gemini without data fabrication. Read API `GET /api/v1/injuries/latest` exposes the latest snapshot grouped by team.
- **Context**: Statuses are published by 5:00 PM Eastern the day before and updated every 15 minutes on game days, so a weekly look would be stale. Three downloads (first after 09:00 local, second after 14:00, third 60–120 min before first tip-off, never two closer than 60 minutes) capture morning shootaround, afternoon updates, and pre-tip status changes while keeping request frequency negligible.
- **Alternatives rejected**:
  1. Polling every 15 minutes (rejected: unnecessary load and risk of IP restriction; 3 daily checks on game days capture all material status updates).
  2. Scraping third-party sites like ESPN or RotoWire (rejected: terms of service violations; official NBA reports are the primary source).
  3. Fabricating fallback injuries (rejected: strict Rule 3 violation).
- **Consequences**: Hand-written Alembic migration `c5e7a9b1d3f6` adds `injury_report_snapshot`, `injury_entry`, and `lineup_snapshot`. Background timer `nba-injuries.timer` executes `scripts/fetch_injuries.py` every 30 minutes.
- **Source**: WP-I; [`ROADMAP.md`](ROADMAP.md) item 1; [`OPERATIONS.md`](OPERATIONS.md); migration `c5e7a9b1d3f6`.

## Next step

Planned work and the reasons behind it: [`ROADMAP.md`](ROADMAP.md).
