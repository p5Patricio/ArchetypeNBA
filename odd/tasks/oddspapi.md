# oddspapi

## Objective

Use the OddsPapi free tier (the only free source of **timestamped** Pinnacle price paths the owner has found) to
(1) recover the Pinnacle closing lines the local tick missed while the PC was off, and (2) accumulate Pinnacle
open-to-close price paths of finished NBA games, so the backtest finding that opening-to-closing movement is
predictable (D-68, `docs/QUANT_MODULE.md` section 14) can be tested live with real prices and timestamps. The owner
spends no money.

## Problem

- The tick only sees closing lines while the PC is on: 13 of 43 tipped-off games had no closing capture as of
  2026-10-26, so Brier vs Pinnacle's close and Pinnacle CLV lose those games for good (QUANT_MODULE section 7).
- The D-68 backtest used archives without timestamps or prices; it cannot separate "the open is beatable" from "the
  open is posted before the news" and cannot price a bet at the open. A Pinnacle path with `createdAt` per quote can.
- Vendor claim for the free tier: ~250 requests/month, 5 s cooldown on historical odds, at most 3 bookmakers per
  call, history since January 2026. These numbers are verified by a capped live probe before any design depends on
  them.

## Decisions

- D1 Provenance like SportsGameOdds (D-63): OddsPapi quotes go to `odds_history` under dedicated sportsbook keys
  `op_<slug>` (`op_pinnacle`, `op_draftkings`, `op_fanduel`), never under The Odds API keys. `op_pinnacle` is
  **not** flagged `is_sharp`, so no existing sharp-book lookup (recorder, blend calibration, model evaluation,
  same-book CLV) changes silently; recovered closes are used only through explicit new code paths.
- D2 Quote time: `book_last_update` = `captured_at` = the row's `createdAt` (the moment OddsPapi recorded that
  price). `odds_history`'s unique key includes `book_last_update`, so re-ingesting a path is idempotent.
- D3 Request accounting in a small dedicated table `oddspapi_request` (every HTTP call, its endpoint, status, the
  quota fields when known), because fixture listings have no game and `odds_snapshot_capture.game_id` is NOT NULL.
  The monthly budget (`ODDSPAPI_MONTHLY_BUDGET`, default 200) counts the rows of the current UTC month that the
  vendor bills; the budget is checked before every call, so it holds across runs and machines sharing the DB.
- D4 Markers (`odds_snapshot_capture`): `oddspapi_path` (unique per game: its path was fetched and stored) and
  `closing_oddspapi` (unique per game: the game had no `closing` marker and the path yields Pinnacle's last pre-tip
  quotes). One hand-written migration (down_revision `e9b1d3f5a7c2`) adds the table and the two kinds.
- D5 Missed-close metrics: `market_close` gains an opt-in path that uses `op_pinnacle` quotes for games with a
  `closing_oddspapi` marker and no `closing` marker. The paper report keeps its captured-close numbers unchanged and
  prints the recovered ones next to them, labelled. Same-book CLV (`fill_clv`) and the promotion gate inputs
  (`model_evaluation`) are untouched.
- D6 Planner priorities: (1) final games without a `closing` marker, (2) final 2026-27 games without a path, newest
  first, (3) Jan-Jun 2026 games, only with leftover budget. Fixture listings count toward the budget.
- D7 Tick step `oddspapi`: once per machine-local day, disabled unless `ODDSPAPI_ENABLED=true` and a key exists,
  isolated like the other steps, with a small per-run request cap.

## Constraints

- Worktree `../ArchetypeNBA-worktrees/oddspapi`, branch `feat/oddspapi` from `origin/main` bdc52f6; Alembic head
  before this work `e9b1d3f5a7c2`.
- Live exploration: at most 20 requests this session, >= 6 s apart, logged in
  `~/ArchetypeNBA-data/raw/oddspapi/probe_log.txt`; raw responses stay there (outside git); tests use small sanitized
  fixtures only.
- The API key is a query parameter (`apiKey`): never printed, never logged in a URL (httpx INFO stays silenced; our
  own logs mask it).
- Production database read-only during development; the owner migrates and deploys after review.
- Conventional Commits, English, no AI trailers; commit locally, no push.

## Tasks

- T1 Live probe (<= 20 requests): NBA sport/tournament ids, fixture listing, market ids and line encoding, bookmaker
  slugs, quota headers, what history returns for a finished 2026-27 game and a Jan-Jun 2026 game.
- T2 Settings, model + migration (`oddspapi_request`, two marker kinds).
- T3 Client `services/oddspapi_client.py`: key masking, timeouts, per-endpoint cooldown, ETag cache, budget guard,
  request ledger.
- T4 Parsing and fixture mapping (`services/oddspapi.py`): team mapping, tip-time tolerance, unmatched counted.
- T5 Storage of `op_` paths and the `oddspapi_path` / `closing_oddspapi` markers.
- T6 Missed-close recovery in `market_close`, `clv_report`, `paper_report` (opt-in, labelled).
- T7 Planner, tick step `oddspapi`, CLI `scripts/oddspapi_backfill.py` (`--dry-run`, `--max-requests`, report).
- T8 Read-only analysis CLI `scripts/line_movement_report.py`.
- T9 Tests (client, mapping, storage idempotency, recovery, planner, dry-run zero network).
- T10 Docs: QUANT_MODULE, DECISIONS (D-70), OPERATIONS, AGENTS.md.

## Acceptance criteria

- The full offline suite passes; no test touches the network.
- The monthly budget can never be exceeded by any sequence of runs (tested with a fake transport).
- The key never appears in logs, exceptions or stored rows (tested).
- Re-running a backfill inserts nothing new and spends no request for games that already have a path.
- Existing CLV and Brier numbers are unchanged for games with a `closing` marker.

## Progress

- (filled as tasks complete)

## Follow-ups

- (filled at the end)

## Next step

T1, then T2.
