# Feature: model-learning-loop

## Objective
A closed, auditable loop that proposes candidate models, runs them in shadow next to the paper-trading champion, compares them with proper statistics against outcomes and against Pinnacle's closing line, and promotes (or rolls back) the champion only when evidence passes explicit gates. "Self-improving" without self-deceiving.

## Problem
- The recorder is hard-wired to one model (`elo_538` v1.1). There is no notion of champion/challenger, no shadow predictions, no evaluation history and no promotion rule.
- `team_elo_rating` stores one rating set (no model id), so a second Elo parameterization cannot persist its own state.
- Live data accumulates slowly (~10 games/day, free-tier odds), so an unguarded loop would chase noise.

## Why
The user's goal is a system that improves with time. With ~2,600 held-out games per two seasons, differences of 0.001 log loss are not detectable, so the loop must (a) pre-filter candidates on history with a strict time split, (b) confirm them live in shadow with paired tests, and (c) log every decision.

## Verified context (2026-10-20)
- Pipeline live on main: `NBA-Odds-Tick` task (logon + 15 min) runs opening, closing, results, record. First game finalized and settled; report works. Quota ~487 credits.
- `model_version` has id, name, version, params JSON, brier_oos, trained_at. Only `elo_538` v1.1 (id 1; HOME_ADVANTAGE 60, sigma 14.14, walk-forward Brier 0.2167).
- `model_prediction` stores model_prob per side and `projection` (expected home margin) for h2h/spreads; sigma lives in the model's params.
- 23 seasons of results in `player_game_log` (via `EloRatingService.load_games()`); no free historical odds, so history can be scored against outcomes only; Pinnacle comparison exists only for live games with a closing capture.
- scikit-learn, numpy, pandas are already dependencies.

## Design decisions
1. **Roles.** `model_version.role` in {champion, challenger, retired}; exactly one champion. Only the champion's predictions drive paper bets; challengers record predictions only (no shadow bets, so bankrolls are never mixed). Max 3 active challengers. The demoted champion stays as a challenger (rollback watch).
2. **Per-model Elo state.** `team_elo_rating` gets `model_version_id` (existing 59,282 rows -> model 1), unique key becomes (model_version_id, team_id, season_id, game_id). `EloRatingService` takes the model version/params; defaults keep the current behavior.
3. **Model families** behind a small protocol (`predict(game_context) -> Prediction(p_home, mu, sigma)`), registry keyed by `model_version.name`:
   - `elo_538`: Elo with hyperparameters in params (K, home_advantage, carryover, mean_rating, mov exponent, elo_per_point, sigma).
   - `margin_features`: ridge regression for the home margin plus logistic regression for P(home win) on leak-free features (champion Elo difference incl. home edge, rest days, back-to-back flags, games in last 7 days, rolling margin over the last 10 games, season win% difference). Coefficients, scaler stats and feature names live in `params` (no pickles); inference is numpy only.
4. **Candidate generation (weekly, time-boxed).** (a) Elo random search (seeded, 40 configs) selected on seasons [T-9, T-2] by walk-forward log loss; (b) `margin_features` retrained on seasons <= T-2 for selection and re-fit on all completed seasons for deployment; T is the latest completed season. Historical gate to become a challenger: on held-out seasons [T-1, T] its log loss beats the champion's by >= 0.0005 and its parameters differ materially from existing active models.
5. **Live shadow evaluation.** Unit = final game where champion and challenger both have a prediction recorded before tip-off. Metrics: paired per-game log-loss difference (primary), paired Brier, margin Gaussian NLL (mu from `projection`, sigma from params), and, where a Pinnacle closing pair exists, Brier versus the market. Paired bootstrap (2,000 resamples, fixed seed) for the confidence interval.
6. **Promotion gate (all must hold).** n >= 150 paired games; challenger live >= 14 days; lower bound of the one-sided CI on log-loss improvement > 0 at confidence 1 - 0.05/k (k = active challengers, Bonferroni); margin NLL not significantly worse (lower bound > -0.02 nats); market-Brier gap not worse than the champion's by more than 0.005 when n_market >= 50; >= 30 days since the last promotion. Decision, numbers and seed are stored in `model_evaluation`.
7. **Retirement.** Significantly worse (upper CI < 0) with n >= 100, or age > 90 days with n >= 300 and no pass. Rollback: the demoted champion must pass the same gate against the new champion.
8. **Cadence.** A `learn` tick step after `results`: evaluate (DB only; when there are new final games), propose candidates at most weekly, promote at most once per evaluation pass; time budget 4 minutes; idempotent via `model_evaluation` markers.
9. **Safety.** Reproducible seeds, no feature uses information from the game or later, no promotion on a small sample, all decisions auditable, kill switch (`--dry-run` and a config flag `LEARNING_AUTOPROMOTE`, default on; when off the loop only reports).

## Constraints
- Free tiers only; no extra paid services. Tick task has a 10 minute limit.
- Real DB is native PostgreSQL 18.4; tests run on in-memory SQLite.
- Development happens in a separate worktree (`../ArchetypeNBA-worktrees/learning-loop`) because the scheduled task executes the main checkout; migrations are applied to the real DB at merge time, immediately followed by pulling main.
- Artifacts in English. User authorized PRs and merges to main for this work (2026-10-17).

## TDD
- Mode: off. Source: no project/session TDD configuration. Runner: `python -m pytest -q` from `backend/` (baseline 401).

## Delivery
- Strategy: ask-on-risk; chain strategy stacked-to-main, each PR merged to main before the next starts. Forecast ~5,000 changed lines over 3 PRs (size:exception each).
- RDD: on (default); assess each work-unit commit.

## Tasks
- [ ] L1 Registry and shadow predictions: migration (model_version role/status fields, `model_evaluation`, `team_elo_rating.model_version_id`), model family protocol + registry + Elo family with params, recorder predicts for champion and active challengers (bets only from champion) — route: delegated writer (PR 1, branch feat/model-registry)
- [ ] L2 Feature model and candidate lab: `margin_features` family (training, numpy inference), leak-free feature builder, historical walk-forward lab CLI, Elo random search with time split, challenger registration — route: delegated writer (PR 2)
- [ ] L3 Evaluation, promotion engine and `learn` tick step: paired bootstrap evaluation, gates, promotion/retirement/rollback, audit rows, report section "Model league", flag/kill switch — route: delegated writer (PR 3)
- [ ] L4 Operate: apply migrations in lockstep with each merge, first candidate proposal, verify with a dry run and the report — route: inline

## Acceptance criteria
- Behavior with only the current champion is unchanged (same predictions/bets as before the refactor on the same inputs).
- Challenger predictions are recorded before tip-off, idempotently, and never create bets.
- Historical lab output is reproducible (same seed -> same numbers) and uses only past information for every game.
- Promotion never fires below the sample/time gates; every evaluation writes an auditable row.
- `learn` step is isolated like other tick steps (a failure never blocks `record`) and respects the 4-minute budget.

## Checks
- `cd backend && python -m pytest -q`
- Offline `alembic upgrade head --sql` / `downgrade` render for each migration
- `python scripts/run_tick.py --dry-run`, `python scripts/paper_report.py` against the real DB (read-only)

## Progress
- Branch feat/model-registry created from main (2ee2d41) in a separate worktree.

## Follow-ups (out of scope)
- Totals and props models through the same registry.
- Frontend page for the model league.
- Telegram notification on promotion.
- Closing-quote presence record; shutdown endpoint CSRF hardening; second odds feed.

## Next step
Run L1.
