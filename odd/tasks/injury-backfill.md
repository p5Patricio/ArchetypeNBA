# Feature: injury-backfill

## Objective
Implement a polite, resumable, idempotent historical backfill tool (`backend/scripts/backfill_injuries.py` and service helpers in `backend/app/services/injury_report_service.py`) to download, parse, and store official NBA injury report PDFs across historical game dates from `2018-12-17` (when the `ak-static.cms.nba.com` archive begins) through a target end date. Each snapshot is persisted with its true Eastern-to-UTC report timestamp (`report_timestamp`) so pre-game models (such as `elo_injury`) can query strictly pre-tip-off injury reports without train/serve skew or look-ahead leakage.

## Problem
- `elo_injury` (D-64) calibrates $\beta$ on historical `player_game_log` binary absences (an upper bound due to train/serve skew), while live serving uses pre-game injury status probabilities from `injury_report_snapshot`.
- The official NBA PDF archive on `ak-static.cms.nba.com` starts on `2018-12-17` (`docs/RESEARCH_LONG_TERM_EDGE.md` §C.2), using hourly filenames (`Injury-Report_YYYY-MM-DD_HHPM.pdf`) in 2018–2022 and 15-minute filenames (`Injury-Report_YYYY-MM-DD_HH_MMAM|PM.pdf`) in recent seasons.
- Backfilling ~8 seasons of game days (~1,300+ game dates, ~2,600 snapshots) requires strict politeness controls (honest User-Agent, minimum 2 s / default 4 s inter-request delay, hard `--max-requests 300` per run, resumability across chunked runs, and graceful `Ctrl-C` handling) and must reuse the existing download/parse/store pipeline without duplicating parser logic.

## Design decisions
1. **Reuse existing parser and storage pipeline.** Factor `InjuryReportService.store_pdf_bytes` and `InjuryReportService.download_and_store_pdf_url` in `backend/app/services/injury_report_service.py` so both live `fetch_and_store_snapshot` and historical backfill share one code path for `sha256` deduplication, `pypdf` layout text extraction, `parse_injury_report_text`, team-scoped player resolution (`resolve_player_id`), and `InjuryReportSnapshot` / `InjuryEntry` persistence.
2. **Support both URL naming eras and AM/PM edge cases.** Extend `parse_pdf_filename_timestamp` and add `build_injury_pdf_url` + `build_candidate_pdf_urls`:
   - 15-minute era: `https://ak-static.cms.nba.com/referee/injury/Injury-Report_YYYY-MM-DD_HH_MMAM|PM.pdf`
   - 2018–2022 hourly era: `https://ak-static.cms.nba.com/referee/injury/Injury-Report_YYYY-MM-DD_HHAM|PM.pdf`
   - Candidate fallback for a target cutoff time $T$ (ET) steps newest-first in 15-minute increments across the 1-hour window ending at $T$ (`[T, T-15m, T-30m, T-45m]`), including both `HH_00AM|PM.pdf` and `HHAM|PM.pdf` at top-of-hour marks. All candidates are strictly $\le T$ (leak-free). HTTP 403 and 404 responses are treated as missing (advance to next fallback candidate, never invent data).
3. **Game-date discovery and slot planning.** Derive NBA game dates in `[--start, --end]` (default `--start 2018-12-17`, `--end` today ET) from the union of `player_game_log.game_date` (excluding `001` preseason and `003` All-Star game IDs) and non-postponed `game.commence_time` (converted to `America/New_York`). Non-game days are skipped. On each game date, plan at most `--per-day` slots (default 2):
   - Slot 1: latest report at or before `5:00 PM ET` (`17:00`).
   - Slot 2: latest report at or before 60 minutes prior to the earliest tip-off on that date when tip times are known in `game`, else `7:30 PM ET` (`19:30`).
4. **Resumability and idempotency.** Before making any network request for a planned slot, check whether `injury_report_snapshot` already has a snapshot matching any of the slot's candidate URLs or a `report_timestamp` within the slot's 1-hour window `[T-45m, T]`. If present, skip the slot with zero HTTP requests. Downloaded PDFs are also deduplicated by `sha256`.
5. **Polite rate limits and operational safety.**
   - Honest User-Agent from `settings.INJURY_USER_AGENT` (`"ArchetypeNBA-research/1.0 (personal, low frequency)"`), matching `fetch_injuries.py`.
   - Inter-request delay configurable via `--delay` (default `4.0` s, minimum `2.0` s enforced via clamping).
   - Hard `--max-requests` cap (default `300` per run) so a full backfill is executed in polite chunks only after owner approval.
   - `--dry-run` prints planned slots/URLs and makes zero network requests.
   - Progress log line every 25 requests, graceful stop on `KeyboardInterrupt` (`Ctrl-C`), and structured summary (`requested`, `stored`, `missing`, `parse_failures`, `unmatched_player_names`, plus `skipped_existing` and `http_errors`).

## Constraints
- Work strictly inside the `injury-backfill` worktree on branch `feat/injury-backfill`; never touch `/home/patricio/proyectos/ArchetypeNBA`.
- Do NOT run the backfill against the network or any real database.
- Tests must be 100% offline and deterministic (in-memory SQLite, `httpx.MockTransport`, fake clock/sleep).
- Conventional Commits in English with no AI attribution trailer; commit locally, do not push.

## Tasks
- [x] B0 Fill `odd/tasks/injury-backfill.md` before the first source edit.
- [x] B1 Extend `backend/app/config.py` (`INJURY_USER_AGENT`) and `backend/app/services/injury_report_service.py` (dual-era timestamp parser, URL builders, game-date planner, slot resume check, shared store/backfill service).
- [x] B2 Create CLI `backend/scripts/backfill_injuries.py` (`--start`, `--end`, `--per-day`, `--delay`, `--max-requests`, `--dry-run`, progress logging, `Ctrl-C` handling, summary output).
- [x] B3 Add offline unit tests in `backend/tests/test_injury_backfill.py` (both naming eras, AM/PM edge cases, game-date planning from `player_game_log` and `game`, resume/idempotency, `--dry-run` zero-network assertion with fake transport, delay/cap enforcement with fake clock, 403/404/parse/HTTP failure handling, `Ctrl-C`).
- [x] B4 Update documentation (`docs/OPERATIONS.md`, `docs/DECISIONS.md` D-69, `AGENTS.md`).
- [x] B5 Run full pytest suite (`cd backend && /home/patricio/proyectos/ArchetypeNBA/.venv/bin/python -m pytest tests -q`) and commit locally.

## Acceptance criteria
- URL builder and timestamp parser handle both `HH_MMAM|PM.pdf` and `HHAM|PM.pdf` formats and 12 AM / 12 PM edge cases accurately in `America/New_York` -> UTC.
- Planner includes only dates with games in `player_game_log` or `game`, uses `first_tip - 60m` when `game.commence_time` exists and `7:30 PM ET` otherwise, and skips slots already stored in `injury_report_snapshot`.
- `--dry-run` performs zero HTTP calls against the transport.
- Delay < 2 s is clamped to 2 s; default is 4 s; `--max-requests` hard-stops requests at the cap.
- 403/404 falls back to older candidates within the hour and counts as `missing` without inventing data; corrupt PDFs increment `parse_failures` without aborting the run.
- Stored snapshots carry the real filename `report_timestamp` (UTC) rather than fetch wall-clock time.
- Full backend test suite passes offline.

## Checks
- `cd backend && /home/patricio/proyectos/ArchetypeNBA/.venv/bin/python -m pytest tests -q`
- `git status` and `git diff --stat origin/main`

## Progress
- 2026-11-06 B0 Completed ODD plan in `odd/tasks/injury-backfill.md`.
- 2026-11-06 B1–B3 Implemented dual-era URL builder, timestamp parser, game-date planner, resumable backfill service, `backend/scripts/backfill_injuries.py`, and offline test suite `backend/tests/test_injury_backfill.py`.
- 2026-11-06 B4–B5 Documented chunked execution in `docs/OPERATIONS.md`, decision D-69 in `docs/DECISIONS.md`, and `AGENTS.md`; verified full backend test suite.

- 2026-11-06 Orchestrator review: offline suite re-run independently; dry run against the production database plans 2 slots per game date (5:00 PM ET and a 7:30 PM ET default, because historical tip times are not in `player_game_log`).

## Follow-ups
- **Leakage guard for historical features.** Without tip times the 7:30 PM ET slot can postdate early tip-offs, and weekend or holiday matinees can tip before 5:00 PM ET. Any model or backtest that reads backfilled snapshots must join real tip times (for example the `nba_api` schedule endpoint) and use only reports with `report_timestamp` strictly before the game's tip; without a tip time, drop the game rather than guess.
- Run a small pilot (a few dates from each naming era) before the full chunked backfill, and check parse rates per era.
