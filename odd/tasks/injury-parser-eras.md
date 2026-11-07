# injury-parser-eras

## Objective

Make the historical NBA injury report pipeline (D-62, D-69) accurate and efficient for a full
`2018-12-17..today` backfill: an era-aware parser that extracts team, player, status, reason and
game time correctly in every PDF layout; exact URL discovery from the official season index pages
instead of guessed file names; a tip-time helper so models only use reports published strictly
before a game's tip; and season-scoped player resolution.

## Problem

- Pilot (2026-11-06): the 2024-01-15 report parsed 133 entries with 0 unresolved players, but the
  2019-01-15 05PM report stored 91 entries with ALL 91 unresolved: the older layout puts team,
  player, reason category and detail in a different column order, and the parser mis-split them
  (`player_name_raw='Minnesota Covington, Robert Injury/Illness Right Knee Bone Bruise'`).
- Each stored report cost ~5 requests because candidate file names are guessed.
- `elo_injury` selects snapshots with `report_timestamp <= game_time` (not strict) and nothing
  turns `game_time_et` ('07:00 (ET)') into a real tip time; weekend/holiday matinees tip before the
  5 PM report.
- `resolve_player_id` scopes by team across ALL seasons, so a name can collide across eras.

## Design decisions

1. Detect the layout from the column header; unknown layouts are parse failures (rule 3), never
   guessed. Layouts found (24 official PDFs, 2026-11-06): `category_columns` (2018-19 and the start
   of 2019-20: Category | Reason | Current Status | Previous Status, top-down, wrapped team names,
   parsed by column position), `status_reason_upright` (2019-20 .. 2022-23 regular season) and
   `status_reason_inverted` (2023 playoffs onward: pypdf emits each page bottom-up, header only on
   page 1, multi-line reasons straddle their row).
2. Discover exact PDF URLs once per season from `official.nba.com/nba-injury-report-YYYY-YY-season/`
   and pick the latest listed report per slot. Finding: past-season URLs serve the CURRENT season page
   (canonical 2026-27, today's reports only), so history uses guessed names of the date's naming era:
   hourly `_05PM.pdf` through 2025-12-21 (binary search with 5 probes), quarter-hour `_05_00PM.pdf`
   from 2025-12-22; at most 3 guesses per slot.
2b. Hourly files hold the HH:30 report (title `Injury Report: 01/15/19 05:30 PM` in a `_05PM` file):
   `report_timestamp` comes from the PDF title, else file name + 30 min for hourly names.
2c. Slots: the report labelled 5:00 PM, and the latest report PUBLISHED at or before first tip - 60 min,
   re-planned at run time from the game times printed in the stored 5 PM report (no historical tip
   times in the DB). In the hourly era a 7 PM first tip resolves to the same `_05PM` file: no request.
3. Game times in the report are 12-hour clock without AM/PM; NBA tips are between noon and
   midnight ET, so `HH:MM (ET)` maps to PM (12:xx stays noon).
4. Player resolution: team roster of the game date's season (`player_game_log` season of that date),
   then any team that season, then the team in any season, then global; a name ambiguous within a
   scope is never resolved by a broader scope.

## Constraints

- Worktree `injury-parser-eras` only (branch `fix/injury-parser-eras`); production DB read-only.
- At most 40 network requests in total for layout study (>= 4 s apart, honest User-Agent); PDFs stay
  in `~/ArchetypeNBA-data/raw/injury_pdfs/` and are never committed; tests use small text fixtures.
- Tests offline and deterministic.

## Tasks

- [x] E0 Fill this ODD file before the first source edit.
- [x] E1 Download one PDF per season (2018-19..2025-26 + playoffs) and the season index pages; map layouts
      (33 requests: 2 index pages, 31 PDFs/probes; files in `~/ArchetypeNBA-data/raw/injury_pdfs/`, manifest.json).
- [x] E2 Era-aware parser + per-era text fixtures (`backend/tests/fixtures/injury_layouts/`) + tests.
- [x] E3 Index-page URL discovery + slot planning from real lists + tests (fixture HTML).
- [x] E4 Tip-time helper (`parse_game_tipoff_et`, `injury_entry_tipoff_utc`, `latest_snapshot_before_tipoff`)
      + strict `<` pre-tip selection in `elo_injury` + tests.
- [x] E5 Season-scoped player resolution + tests; resolution rate per sample 96.8-100%.
- [x] E6 Docs: OPERATIONS chunked run (request count), DECISIONS D-69 consequences, AGENTS.md gotcha.
- [x] E7 Full suite (1071 passed, 4 skipped); `backfill_injuries.py --dry-run` on the full window against the read-only DB.

## Acceptance criteria

- Every sampled era parses with correct team/player/status/reason/game time; unknown layouts are counted
  as parse failures.
- Dry run plans one request per slot when the season index is available.
- Snapshot selection for a game uses only `report_timestamp < tip`.
- Full backend suite passes offline.

## Checks

- `cd backend && /home/patricio/proyectos/ArchetypeNBA/.venv/bin/python -m pytest tests -q`
- `git diff --stat origin/main`

## Progress

- 2026-11-06 E0 plan written.
- 2026-11-06 E1 layouts mapped; naming switch located between 2025-12-21 (403 for `_05_00PM`) and 2025-12-22.
- 2026-11-06 E2-E5 implemented; resolution per sampled report (read-only production DB): 2019-01-15 100%,
  2019-05-15 100%, 2019-10-25 96.8%, 2020-01-15 98.3%, 2020-08-10 100%, 2021-02-15 98.9%, 2021-05-25 100%,
  2022-01-17 99.1%, 2022-05-20 100%, 2023-01-16/03-01/04-05/05-17 100%, 2024-03-15 100%, 2024-12-25 97.4%,
  2025-01-15/04-25/11-15 100%, 2025-12-22 98.5%, 2025-12-30 98.0%, 2026-01-15 99.3%, 2026-05-20 100%.
  Unresolved names are players with no game log or a renamed player (Kanter/Freedom, Nene Hilario).
- 2026-11-06 E7 dry run (full window, read-only DB): 1,612 game dates, 3,222 slots, ~1,789..3,231 requests.

## Follow-ups

- Delete and re-fetch the two pilot snapshots before the full run (2024-01-15 `_05PM` stored at 17:00 ET; the
  report is from 17:30) - needs a production write, owner's call.
- Pilot one 300-request chunk per naming era and measure 403 rates for the pre-tip guesses (hourly files are
  sparse in early seasons) before running the rest.
- Game times carried across merged cells: a game whose time cell is blank inherits the previous game's time
  (the PDF merges equal adjacent cells); a TBD time would inherit wrongly. Rare; check `game_time_et` against
  a schedule source when one is added.
