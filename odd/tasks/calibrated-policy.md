# Feature: calibrated-policy

## Objective
Add a fifth paper-staking strategy, `calibrated` (flat 1 unit, same per-bet/daily/per-game caps), that bets only when the model is trusted to the degree live evidence justifies and only inside a band where the model is neither identical to the market (no edge) nor wildly different from it (probably wrong). The four existing strategies (`flat`, `kelly_fractional`, `kelly_shrunk`, `market_edge`) are untouched and remain the v1 control (rule 8: no silent policy changes).

## Problem (measured 2026-11-01 on the real DB)
- The champion Elo has Brier 0.242, far worse than Pinnacle's de-vigged close (0.202).
- Policy v1 bets when `p_model - p_fair >= 2pp` and blends 50/50 linearly. On 93 settled flat bets: mean model probability 0.593, Pinnacle fair at bet time 0.480, realized win rate 0.419, ROI -17.6%.
- Diagnosis: adverse selection. A filter on "model above market" selects the model's largest errors (missing injury/roster information), and a fixed 50% weight on a much worse model keeps most of the error.

## Design decisions
1. **Logit blend** `logit_blend(p_model, p_fair, w) = sigmoid(w*logit(p_model) + (1-w)*logit(p_fair))`, probabilities clipped to [1e-6, 1-1e-6]. The weight of the model `w` is fitted, not assumed.
2. **Fitted weight.** `fit_blend_weight(p_models, p_fairs, outcomes) -> (w_used, w_hat, n)`: `w_hat` = maximum-likelihood `w` on a grid 0.00..`W_MAX`=0.5 step 0.01 (log loss of the outcomes under `logit_blend`). `w_used = 0` when `n < MIN_CALIBRATION_GAMES` (100), else `w_hat * n / (n + CALIBRATION_PRIOR_GAMES)` with prior 200: trust in the model grows only with evidence.
3. **Band rule** `evaluate_calibrated(...)`: reasons `invalid_input`, `no_model_weight` (w <= 0), `disagreement_too_large` (`|p_cond - p_fair| > MAX_DISAGREEMENT` = 6pp), `ev_below_min` (EV with `p_blend = logit_blend(p_cond, p_fair, w)` at the price, `MIN_EV`), else `ok`. No lower edge bound: with w small the blend is a small shift and the EV gate carries the work.
4. **Calibration data (recorder side).** `model_prediction.fair_decimal` is a generated column `1 / model_prob`: it is the MODEL's fair price, not Pinnacle's, so it cannot supply `p_fair`. Instead the Pinnacle (sharp book) two-sided h2h pair captured at or before the prediction's `predicted_at` is de-vigged with the existing helpers (`devig_two_way`). Unit = final game where the current champion recorded an h2h home prediction strictly before tip-off and such a pair exists. Outcome = home win. `w` is computed once per recorder run, for the champion only, and applies to `calibrated` on h2h and spreads. Totals stay `market_edge` only.
5. **Attributability.** Nullable `simulated_bet.blend_weight` Numeric(4,3), set for `calibrated` bets; enum value `calibrated` added to `staking_strategy` (hand-written Alembic migration, `ALTER TYPE ... ADD VALUE` in an autocommit block, same style as `e3f8b1a4c9d2`).
6. **Reporting.** `paper_report.py` shows the new strategy automatically (it iterates `StakingStrategy`) plus one line with `w_used`, `w_hat`, `n`; read-only CLI `scripts/blend_weight.py` prints the same and the distribution of `|p_model - p_fair|`.

## Constraints
- Paper trading only; free tiers; no network and no real DB in tests; seeded numpy.
- Never edit the production checkout; work in the worktree `../ArchetypeNBA-worktrees/calibrated-policy`, branch `feat/calibrated-policy`. No push, no PR, no merge.
- Existing strategies keep exactly their behaviour (including bankrolls, caps, `_STRATEGIES` order for them).
- Conventional Commits, no AI trailers.

## Tasks
- [x] C0 ODD file created before the first source edit.
- [x] C1 Pure functions in `analytics/betting_policy.py` (`logit_blend`, `fit_blend_weight`, `evaluate_calibrated`, constants).
- [x] C2 Model + migration (`blend_weight`, enum value) and SQLite emulation check.
- [x] C3 Calibration data service (`services/blend_calibration.py`, Pinnacle de-vig as of the prediction time) and `market_close` generalization.
- [x] C4 Recorder: compute `w` once per run, `calibrated` strategy for h2h and spreads, summary fields, tick log line, dry-run output.
- [x] C5 `paper_report.py` line + `scripts/blend_weight.py`.
- [x] C6 Tests (policy, calibration data, recorder, report, CLI) and the full suite.
- [x] C7 Docs: `docs/QUANT_MODULE.md` section 6, `docs/DECISIONS.md` D-67, `AGENTS.md`, `docs/OPERATIONS.md` (lockstep migration), frontend labels.

## Acceptance criteria
- `fit_blend_weight` gives `w_hat` about 0 on synthetic data where the model is noise around the market, and clearly positive when the model carries independent signal; `n < 100` gives `w_used = 0`.
- `evaluate_calibrated` returns each reason in its situation.
- Recorder: `calibrated` places no bet when `w = 0`; places one (with `blend_weight` stored) when `w > 0` and the disagreement is inside the cap; the other four strategies behave as before (existing tests pass unchanged except for enumerations of strategies).
- Dry run writes nothing and reports `w_used`, `w_hat`, `n`.
- Full backend suite green.

## Checks
- `cd backend && /home/patricio/proyectos/ArchetypeNBA/.venv/bin/python -m pytest tests -q`
- `python -m alembic heads` shows a single head (the new migration, down_revision `d6f8b0c2e4a7`).

## Deploy note
Lockstep schema deploy (AGENTS.md section 7): the new code writes `simulated_bet.blend_weight` and the new enum value, so pause the tick, merge, pull, `alembic upgrade head`, dry runs, resume.

## Progress
- 2026-11-01 C1-C5 implemented: pure functions; migration `a8c2e4f6b0d1` (down_revision `d6f8b0c2e4a7`, single head); `services/blend_calibration.py`; `market_close.sharp_home_probs_as_of` (closing function delegates to it); recorder, tick line and `record_predictions.py` output; paper report line and `scripts/blend_weight.py`; frontend labels for the new strategy.
- 2026-11-01 C6 tests: `test_betting_policy.py`, `test_blend_calibration.py`, `test_prediction_recorder.py`, `test_paper_report.py`. Design note: `fair_decimal` = `1 / model_prob` (generated column), so p_fair is read from Pinnacle's pair at `predicted_at`.
- 2026-11-01 C7 docs written (QUANT_MODULE section 6, D-67, OPERATIONS lockstep, ARCHITECTURE chain, AGENTS).
- 2026-11-01 C0 done.
