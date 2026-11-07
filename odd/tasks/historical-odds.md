# historical-odds

## Objective

Build the historical-data foundation of the quant side: import ~16-19 seasons of free historical NBA game lines
(open/close spreads and totals, close moneylines, final scores) and backtest, walk-forward and read-only, whether any
model signal beats the market close and, above all, whether a model can predict **opening-to-closing line movement**
(betting the open on the side the close moves toward = positive CLV, the documented and bettable mechanism).

## Problem

- Live evidence is tiny and negative: the Elo champion's Brier is ~0.234 against Pinnacle's close at ~0.202, and the
  fitted logit blend (D-67) gives the model weight 0. At ~8 games a day, live data needs years to resolve a small edge
  (`docs/QUANT_MODULE.md` section 13).
- Free archives (SBRO 2007-08..2022-23, Kaggle CC0 compilation 2007-08..2025-26) already hold ~19,000+ games with a
  market line, which turns the multi-season power problem into a one-off backtest (`docs/RESEARCH_LONG_TERM_EDGE.md`
  C.1, E1-E2). Gandar et al. (1998) show the close improves on the open: the edge, if any, lives at the open.

## Decisions

- D1 Raw downloads stay outside git in `~/ArchetypeNBA-data/raw/<source>/` with a `manifest.json` (URL, retrieval
  date, sha256). Untrusted: parsed only with `python -I`, never executed.
- D2 Sources: Kaggle `cviaxmiwnptr/nba-betting-data-october-2007-to-june-2024` (`nba_2008-2026.csv`, CC0 per the
  uploader; anonymous public download worked, no token needed) and the SBRO archive. SBRO no longer serves `.xlsx`
  files: each season is an HTML page with the same 13-column table (Date, Rot, VH, Team, 1st..4th, Final, Open,
  Close, ML, 2H). The importer parses those HTML tables (stdlib `html.parser`, no new dependency). SBRO's `/terms/`
  says content may not be "used or reproduced" without written consent: downloaded once (16 pages, 5 s apart) for
  private research on the owner's approval of 2026-11-06, never redistributed, never committed. Flagged for the
  owner.
- D3 One table `historical_game_line`, unique `(source, game_date, home_team_id, away_team_id)`; both sources are
  stored side by side; merging (prefer SBRO up to 2022-23 when both agree) happens at read time, disagreements are
  counted. Teams map to canonical current franchise ids (Elo's `FRANCHISE_ALIASES`).
- D4 SBRO open/close cells hold the spread on the favourite's row and the total on the other row: values >= 60 are
  totals, smaller are spreads, `pk` is a 0 spread, `NL`/empty/unparseable (`.5+03`, `197.5u10`) are missing (rule 3:
  never guessed). A pair with two spreads or two totals in a column is ambiguous and that column stays missing.
- D5 Backtest is read-only: games come from `player_game_log` (read-only session) and lines are parsed straight from
  the raw files in memory, so it needs no write to production and no migration.
- D6 Market baseline: proportional de-vig of the close moneyline; spread-implied `Phi(-close_spread / sigma)` when no
  moneyline exists, sigma = std of past seasons' (margin + close spread) (walk-forward).
- D7 Opening-line value: model line `-mu` vs the open; bet the side the model prefers when `|mu + open| >= thr`;
  CLV in points = `side * (open - close)` (home side +1); probability CLV via the normal margin model; realized ATS at
  the open priced at an **assumed -110** (no price in the data). Naive baselines: always home, always the open
  favourite, always the open underdog, and a seeded coin flip.
- D8 The market-offset model is an L2 logistic regression (numpy Newton, deterministic) with `logit(p_market)` as a
  free feature plus standardized model features, fitted on past seasons only; an offset variant (market coefficient
  fixed at 1) is reported too. A direct line-move model (ridge of `close - open` on model-vs-open gaps and schedule
  features, past seasons only) is the most direct test of "predicting the move".
- D9 Availability from `player_game_log` (who actually played) is post-game knowledge: when enabled it is labelled an
  UPPER BOUND (train/serve skew), never a deployable signal.

## Constraints

- Worktree `../ArchetypeNBA-worktrees/historical-odds`, branch `feat/historical-odds` from `origin/main` 9e5335a;
  Alembic head before this work `a8c2e4f6b0d1`.
- Production database: read-only. No writes, no migration there; the owner applies the migration and runs the import
  after review.
- Tests offline, deterministic, SQLite, small hand-made fixtures only (`tests/fixtures/historical/`).
- Conventional Commits, English, no AI trailers; commit locally, no push/PR/merge.

## Tasks

- [x] T1 Acquire data: Kaggle CSV (anonymous), 16 SBRO season pages; manifests with sha256.
- [x] T2 Migration `historical_game_line` (down_revision `a8c2e4f6b0d1`) + `HistoricalGameLine` model.
- [x] T3 Pure parsers (`app/analytics/historical_lines.py`): SBRO pairs, pk/NL, open/close disambiguation, date year
      inference, team names; Kaggle rows; de-vig and CLV maths.
- [x] T4 Service + CLI `scripts/import_historical_lines.py`: team-id mapping, `--dry-run`, idempotent upsert, links to
      `game.id`, reconciliation report (rows per season, unmatched teams, score disagreements vs `player_game_log`,
      cross-source duplicates/disagreements).
- [x] T5 Backtest service + CLI `scripts/historical_backtest.py`: walk-forward by season, market baseline, Elo,
      margin_features, blend, market-offset, line-move model, metrics (Brier, log loss, gap, calibration, DM-HLN),
      opening-line value by threshold and season, naive baselines, seeded bootstrap CIs; report to stdout and
      `~/ArchetypeNBA-data/reports/`.
- [x] T6 Tests: parser edge cases, team mapping, idempotency, leak-freeness (perturbing a future season leaves earlier
      predictions identical), CLV computation.
- [x] T7 Docs: `docs/QUANT_MODULE.md` (historical data + backtest), `docs/DECISIONS.md` (D-68), `AGENTS.md` (head,
      data location), `docs/OPERATIONS.md` (how to run).
- [x] T8 Run: importer `--dry-run` on the downloaded files, backtest on the real data (read-only); record the numbers.

## Acceptance criteria

- Full suite passes with `python -m pytest tests -q`; new tests cover every parser edge case named above.
- `import_historical_lines.py --dry-run` against the raw files prints the reconciliation report and writes nothing.
- The backtest prints per-model Brier gap to the close with CIs and the opening-line-value table by threshold, with
  naive baselines, and saves a copy under `~/ArchetypeNBA-data/reports/`.
- A null result is reported as such.

## Checks

- `cd backend && python -m pytest tests -q`
- `python scripts/import_historical_lines.py --dry-run --sbro-dir ~/ArchetypeNBA-data/raw/sbro --kaggle-csv ...`
- `python scripts/historical_backtest.py --sbro-dir ... --kaggle-csv ...` (DATABASE_URL exported, read-only)

## Progress

- 2026-11-06 Plan written. Data acquired (T1): Kaggle zip (sha256 c144d660...) -> `nba_2008-2026.csv` 24,440 rows
  (moneylines only through Jan 2023; 2023-24..2025-26 have spread/total only, no open); SBRO 16 pages, 39,644 team
  rows (19,822 games incl. 181 neutral-site pairs), 2022-23 stops at 2023-01-16.

- 2026-11-06 T2-T4: migration `e9b1d3f5a7c2` + model (written by a delegated agent from an exact spec, reviewed), parsers,
  importer. Dry run against production (read-only transaction): 44,262 rows (SBRO 19,822, Kaggle 24,440), no unknown
  teams; SBRO 19,822/19,822 matched to `player_game_log` (12 one day off their source date, matched only with an
  identical score, e.g. Christmas games listed on 24 December), Kaggle 24,428 matched (12 unmatched are neutral-site
  Cup/international games Elo skips); final-score disagreements 12 SBRO / 15 Kaggle (counted, kept); Kaggle's single
  line equals SBRO's close on 19,805 of 19,810 shared games (so it is the close), moneylines on 19,798. 20 ambiguous
  SBRO open/close columns, 1 unparseable cell, 2 implausible totals (e.g. 1955.5) set to missing in the backtest.
- 2026-11-06 T5-T8: backtest run (seed 42, 1,000 resamples, availability upper bound on). Report:
  `~/ArchetypeNBA-data/reports/historical_backtest_20261106_191942.md`. Headline in `docs/QUANT_MODULE.md` section 14
  and D-68: no model beats the close; line moves are predictable (+0.91 points CLV, 65% toward) but from the open line
  and schedule/form features, not the ratings, and not profitable at an assumed -110. Tests: 26 new (delegated to a
  Gemini Flash agent from a precise spec, audited; the leak test was strengthened to fail if the walk-forward models
  predict nothing), full suite 1046 passed, 4 skipped.

## Follow-ups

- The opening line and the "close" here are not Pinnacle's: calibrate the gap with the 2026-27 overlap games.
- Timestamped multi-book history (E3) remains the scarce asset for news-timing tests.

## Next step

Owner review: SBRO terms question (D-68), then apply migration `e9b1d3f5a7c2` and run the import. Modelling: test the
move regression live against Pinnacle's own open-to-close (the tick already stores openings), and split the
back-to-back effect by whether the open predates the previous game (needs timestamped odds).
