# injury-backfill-v2

## Objective

Fix two problems found in the first real historical injury report backfill (2026-11-07, D-69):
(1) the parser rejects the November-December 2019 transition layouts, and (2) every run re-plans
and re-requests slots that already failed or were missing, wasting ~100+ CDN requests per chunk.

## Problem

- Real run log (`~/ArchetypeNBA-data/reports/injury_backfill_20261107.log`): 160 parse failures
  that are 32 unique `_05PM` files re-requested in each of 5 chunks, all 2019-11-15..2019-12-17,
  with headers unknown to `detect_layout`:
  - `Reason | Current Status | Previous Status` (2019-11-15..19, 5 files, 25 failures),
  - `Current Status | Reason | Previous Status` (2019-11-20..12-16, 26 files, 130 failures),
  - `Current Status | Reason | Previous Status | Previous Reason` (2019-12-17, 1 file, 5 failures).
  2019-11-14 (nine-column `category_columns`) and 2019-12-18 (seven-column) parse today.
- `plan_backfill_slots` only skips slots stored in `injury_report_snapshot`; a slot that failed
  to parse or whose guessed names all returned 403/404 is planned again on every run.

## Design decisions

1. Transition layouts are parsed by column position under the header (like `category_columns`):
   each known header is an explicit tuple of column labels; previous status / previous reason
   cells are read into their own columns and dropped, never merged into status or reason. Only
   the three header sequences seen in the archive are accepted; any other header still raises
   `InjuryReportLayoutError` (rule 3). The generic positional parser is shared with the
   nine-column layout.
2. Slot outcome ledger: new table `injury_backfill_slot` (one row per `(game_date, slot kind)`,
   upserted on each attempt) with outcome `stored | missing | parse_failed | http_error`, the URL
   tried (stored/parse-failed file, or the last guessed name), `layout_header` on parse failure,
   `error`, `attempts`, `first_attempted_at`, `last_attempted_at`. One hand-written migration,
   down_revision `f3c5e7a9b2d4`.
3. Planner: skip slots whose ledger outcome is `missing` or `parse_failed` (and, as before,
   `stored` or present in `injury_report_snapshot`); `http_error` slots are retried
   automatically. `--retry-failed` re-plans `parse_failed` slots (fresh download, re-parse),
   `--retry-missing` re-plans `missing` ones, `--reparse-failed-only` plans ONLY `parse_failed`
   slots (after a parser fix). Pre-tip slot kinds stay keyed by kind, not cutoff, so a re-planned
   pre-tip cutoff still maps to the same ledger row.
4. Summary prints cumulative coverage per season from the ledger (stored / missing / failed /
   remaining), where remaining = game-date slots of that season without a terminal outcome.
5. The ledger starts empty in production: the first post-deploy run re-attempts old failures
   once; the 32 Nov-Dec 2019 files then parse with the new layouts.

## Constraints

- Worktree `injury-backfill-v2` only (branch `fix/injury-backfill-v2` from origin/main 1c3e0b9).
- Production DB read-only; at most 15 polite requests (>= 4 s apart, `settings.INJURY_USER_AGENT`)
  to download sample PDFs into `~/ArchetypeNBA-data/raw/injury_pdfs/` (untrusted, read with
  `python -I`); only small extracted-text fixtures are committed.
- Tests offline and deterministic; Conventional Commits, no attribution trailers, no push.

## Tasks

- [x] V0 Fill this ODD file before the first source edit.
- [x] V1 Download samples of the three transition headers; extract text; build fixtures.
- [x] V2 Era-aware positional parser for the three transition layouts + tests; resolution rate per
      sampled PDF against the read-only DB.
- [x] V3 Ledger model + Alembic migration + recording in `backfill_injury_reports`.
- [x] V4 Planner skip rules + `--retry-failed`, `--retry-missing`, `--reparse-failed-only` + per-season
      coverage summary + tests.
- [x] V5 Docs (D-69 consequences, OPERATIONS, AGENTS.md gotcha), full suite, full-window dry run.

## Acceptance criteria

- The sampled Nov-Dec 2019 PDFs parse with correct team / player / status / reason / game time;
  previous status / reason never appear in `status` or `reason`; unknown headers still raise.
- A resumed run makes zero requests for slots with outcome `missing` or `parse_failed` unless the
  matching retry flag is given; `http_error` slots are re-planned.
- Summary shows per-season stored / missing / failed / remaining from the ledger.
- Full backend suite passes offline.

## Checks

- `cd backend && /home/patricio/proyectos/ArchetypeNBA/.venv/bin/python -m pytest tests -q`
- `git diff --stat origin/main`

## Progress

- 2026-11-07 V0 plan written.
- 2026-11-07 V1 6 of 15 allowed requests (4.5 s apart, `INJURY_USER_AGENT`): `_05PM` files of 2019-11-15,
  11-19, 11-20, 12-06, 12-16, 12-17 in `~/ArchetypeNBA-data/raw/injury_pdfs/transition_2019/` (manifest.json).
  Findings: columns move from page to page (positions re-read per page header); pypdf sometimes joins a reason
  and its status with ONE space (`...; Strain Out`), so cells are assigned word by word to the rightmost column
  starting at or before the word (2-character tolerance; existing nine-column fixtures and all 24 earlier
  sample PDFs parse identically). Four excerpt fixtures in `backend/tests/fixtures/injury_layouts/`.
- 2026-11-07 V2 layouts `reason_status_previous`, `status_reason_previous`, `status_reason_previous_reason`;
  every player line of the six PDFs becomes a row (132 / 123 / 110 / 136 / 112 / 107 rows), no previous
  status or reason leaks into status/reason. Season-scoped resolution on the read-only DB: 2019-11-15 98.5%,
  11-19 98.4%, 11-20 97.3%, 12-06 98.5%, 12-16 96.4%, 12-17 98.1% (unresolved: Nene Hilario, Cameron
  Reynolds, Charles Brown Jr., Nicolas Claxton: no game log or a different name in the DB).
  `InjuryReportLayoutError.header` carries the unknown header.
- 2026-11-07 V3-V4 ledger `injury_backfill_slot` (migration `a4d6f8b0c3e5`), planner `plan_backfill`
  (`plan_backfill_slots` kept as wrapper), `record_slot_outcome`; a slot whose candidate already failed to
  parse in the same run records `parse_failed` (not `missing`). Offline end-to-end with the six real PDFs:
  run 1 = 7 requests, 6 stored, 12 ledger rows `stored`; run 2 = 0 requests.
- 2026-11-07 V5 docs; full-window dry run (read-only DB, empty ledger as after the deploy): 1,612 game dates,
  625 slots already stored, 2,416 planned, ~1,407..2,425 requests (5..9 chunks of 300).

## Follow-ups

- After the deploy, the first chunks re-attempt the old misses once; check `Slots skipped (ledger)` grows and
  the per-season coverage after each chunk.
- Unresolved names (Claxton, Brown Jr.) are a resolver alias problem, not a parser one.

## Next step

Owner: lockstep deploy of `a4d6f8b0c3e5`, then resume the chunked backfill.
