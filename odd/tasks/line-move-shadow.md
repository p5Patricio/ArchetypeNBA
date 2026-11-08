# Feature: line-move-shadow

## Objective
Turn the D-68 line-move ridge (it predicts Pinnacle's open-to-close move) into an honest, deployable PAPER strategy and measure it live: (1) a leak-safe offline evaluation that bets only at an instant when every input is known, (2) a new model family `line_move` v1 (role `shadow`) whose recorder places flat 1-unit paper bets under a new staking strategy `line_move`, (3) reporting as a clearly labelled live test. Rule 1 (paper only) and rule 8 (new `model_version`, existing strategies untouched) apply.

## Problem (measured 2026-11-07 on 770 Pinnacle paths, Feb-Nov 2026)
- Betting Pinnacle's OPENER where the ridge predicts the move: spreads |pred| >= 0.25 +0.41 pts CLV (CI +0.22..+0.60, n 400); totals >= 0.5 +1.21 (CI +0.66..+1.83, n 83).
- LEAK: the features (Elo, `margin_features`, rolling totals) include each team's previous game, but the opener is typically ~22 h before tip; for 280 of 770 games a team's previous game could have ended after the opener. On the 490 clean games: spreads >= 0.25 +0.32 (CI +0.04..+0.58, n 200); totals >= 0.25 +0.51 (n 179), >= 0.5 +0.96 (n 35). ROI at the opening price: CIs span zero.
- A second, smaller leak: the totals feature shrinks toward the league's season-to-date mean, which includes other teams' games that ended after the opener.

## Design decisions
1. **Bettable instant** per game and market: `ready = max over both teams of (previous game final time) + SAFETY_MARGIN`, previous game final = its tip + `GAME_DURATION` (3 h, same as the results grace) when a tip time is known (`game.commence_time`, OddsPapi `true_start_time`/`start_time`), else the conservative end-of-day rule (previous game's date + 1 day at 07:00 UTC, about 2-3 AM Eastern). `SAFETY_MARGIN` = 30 min. Entry = the first stored Pinnacle main-line pair at or after `max(opener, ready)` and before the tip (rule `first_after`, conservative; `in_force` = the pair in force at that instant is a sensitivity option). No pair in that window = no bet.
2. **Features as of the instant**: an incremental replay fed in order of final time builds `FeatureState` and `TotalsState` from games final by the entry instant only (`features_as_of`); the backtest takes them as per-game overrides, for test AND training rows of the path games. The two teams' chains are identical to the date-based pass by construction; the totals league mean is the difference. The target becomes `close - entry`, the line feature the entry line.
3. **One code path for features**: `historical_backtest.spread_move_features` / `total_move_features` / `schedule_features` are used by the backtest and by live inference; a ridge fit is exportable (`fit_ridge_cv` -> mean/scale/coef/intercept/alpha) and `run_backtest(config.export_season=...)` exports, for that season, exactly what the walk-forward run would use to predict it (margin_features params, both ridges, sigmas).
4. **Model family `line_move` v1, role `shadow`** (not `challenger`: it has no h2h probability, so it must stay out of the league, the promotion gates and `list_active`). Params JSON: both ridges, feature lists, thresholds (spreads 0.25, totals 0.5), margin_features params, Elo/totals params, sigmas, entry rule and training summary. Registered by `scripts/register_line_move.py [--dry-run]` with coefficients refit through the last completed season plus OddsPapi games strictly before the season (entry-based).
5. **Live recorder** `services/line_move_strategy.py`, run by the tick's `record` step after the champion recorder in its own transaction (a failure is rolled back and reported, never touching the champion). For a scheduled game within 20 h, both teams' previous games must be `final` AND present in `player_game_log` (the feature history); otherwise skip (`previous_game_not_final` / `previous_game_not_ingested`). One decision per game and market: at the first eligible tick a prediction is recorded (projection = predicted close-minus-current move, side = predicted direction, line = Pinnacle's current line), and a bet only when |pred| clears the threshold; later ticks skip (`already_decided`). This mirrors the offline one-shot evaluation and gives one bet per game/market at most (stricter than per side). Price: best fresh quote (<= 6 h) at Pinnacle's line across books, never at or after tip. Flat 1 unit under the usual caps on the strategy's own bankroll.
6. **Attribution**: new enum value `line_move`; nullable `simulated_bet.predicted_move` and `simulated_bet.pinnacle_price_at_bet`; `fair_prob_at_bet` = Pinnacle de-vigged probability of the side at bet time; `model_prob` = that plus `Phi(|pred|/sigma) - 0.5` (the probability-scale move), `ev_per_unit` from it.
7. **Existing strategies unchanged**: the champion recorder ignores bets of strategies it does not run (it would otherwise KeyError on a settled `line_move` bet); aggregate report lines (Pinnacle CLV, market breakdown, CLV coverage) exclude `line_move` so their numbers stay what they were; the live test gets its own section (bets, ROI with a bootstrap CI, Pinnacle price CLV with CI on the captured and recovered lines, points CLV against Pinnacle's close, share moved our way) in `paper_report.py` and `/api/v1/paper/summary`.
8. **Migration**: hand-written, revision `c7e9a1b3d5f8`, down_revision `f3c5e7a9b2d4` (the `fix/injury-backfill-v2` branch may add another child of `f3c5e7a9b2d4`: chain one after the other before merging).

## Constraints
- Worktree `ArchetypeNBA-worktrees/line-move-shadow`, branch `feat/line-move-shadow`; commit locally, no push. No network. Production DB read-only (`SET TRANSACTION READ ONLY`).
- Tests offline and deterministic; `cd backend && <venv python> -m pytest tests -q`.
- Existing strategies, blend calibration and promotion gates must not change.

## Tasks
- [ ] L0 ODD file before the first source edit.
- [ ] L1 `oddspapi.main_line_pairs`, `line_movement` readiness/entry/as-of features, backtest overrides and export, refactored move features.
- [ ] L2 `line_movement_report.py` leak-safe section (naive at entry, leaky opener numbers, leak-safe by threshold, b2b split, month split, n < 30 flagged).
- [ ] L3 Model + migration + `line_move_strategy.py` + tick wiring + recorder guard.
- [ ] L4 `scripts/register_line_move.py --dry-run`.
- [ ] L5 Paper report and API section.
- [ ] L6 Tests (leak safety, readiness, uniqueness, tip guard, existing strategies unchanged, report/API).
- [ ] L7 Docs: QUANT_MODULE section, DECISIONS D-71, OPERATIONS, AGENTS.
- [ ] L8 Run the leak-safe evaluation read-only against production; record the headline.

## Acceptance criteria
- A feature built for a bettable instant is unchanged when a game that ended after the instant changes its score.
- No entry is ever before the readiness time or at/after the tip; the strategy never bets while a previous game is not final.
- One `line_move` decision per game and market across ticks; dry runs write nothing.
- The full suite passes; the four v1 strategies and `calibrated` produce the same bets with and without `line_move` bets in the database.

## Checks
- `cd backend && /home/patricio/proyectos/ArchetypeNBA/.venv/bin/python -m pytest tests -q`
- `python -m alembic heads` shows one head (`c7e9a1b3d5f8`).

## Progress
- 2026-11-07 L0 done.

## Next step
L1.
