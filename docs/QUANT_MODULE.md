# Quant module: methodology

The statistics and rules behind the paper-trading system, written for a reader who knows probability and model evaluation but has not seen this repository. Every constant below was read from the code on 2026-10-26; the file that owns it is named so you can check it. Nothing here places a real bet: the system never handles money, by design (rule 1 in [`AGENTS.md`](../AGENTS.md)).

## Quick path

1. The loop in one table: [section 1](#1-the-loop-in-one-table).
2. The maths of a bet: sections [2](#2-odds-mechanics), [3](#3-elo-the-champion), [4](#4-spread-probabilities), [6](#6-betting-policy).
3. How a model earns the champion's seat: sections [8](#8-evaluation-protocol) and [9](#9-promotion-retirement-and-rollback).
4. Reading the output: [section 12](#12-how-to-read-the-reports).
5. What not to over-read: [section 13](#13-limits-and-honest-expectations).

## 1. The loop in one table

| Stage | What happens | The number that matters | Owner |
|-------|--------------|-------------------------|-------|
| Capture | Quotes from 7 bookmakers, Pinnacle as the sharp reference | 500 credits per month on the free plan | `odds_snapshot.py` |
| Predict | Every active model publishes probabilities before tip-off | Predictions are never recomputed after the fact | `prediction_recorder.py` |
| Bet | Only the champion bets, only with an edge over the de-vigged Pinnacle price | Edge of at least 2 percentage points and EV of at least 2% | `betting_policy.py` |
| Settle | Win, loss or push from the final score | Push is a refund | `settlement.py` |
| Measure | Closing-line value and Brier against Pinnacle's close | Both converge faster than ROI | `paper_report.py` |
| Compare | Challengers are scored on the same games as the champion | Paired log loss | `model_evaluation.py` |
| Decide | Promote, retire or roll back only when the evidence passes the gate | At most one decision-grade look a week | `model_promotion.py` |

Why judge by CLV and Brier rather than ROI: ROI needs thousands of bets before it separates skill from luck; the closing price is a much lower-variance target (decision recorded in [`DECISIONS.md`](DECISIONS.md), D-05).

## 2. Odds mechanics

| Concept | Definition | Code |
|---------|-----------|------|
| American to decimal | `+a` becomes `1 + a/100`; `-a` becomes `1 + 100/a`. The helper rounds to 3 decimals; the generated column `odds_history.price_decimal` keeps 4 | `props_engine.american_to_decimal` |
| Implied probability | `1 / d` | `props_engine.decimal_to_implied_prob` |
| De-vig (two-way market) | Proportional: `p_i = (1/d_i) / (1/d_1 + 1/d_2)`; the two fair probabilities sum to 1 | `props_engine.devig_two_way` |
| Push | Integer spread lines can land exactly on the line: the stake is returned | `elo.spread_probabilities` |
| Conditional win probability | `p_cond = p_win / (p_win + p_loss)`: win probability given no push. This is what a de-vigged two-way price estimates | `betting_policy.evaluate_candidate` |
| Expected value per unit staked | `EV = (1 - p_push) * (p_cond * d - 1)`, equal to `p_win * (d - 1) - p_loss` | `betting_policy.bet_ev` |
| Kelly fraction | `f* = (b * p_win - p_lose) / b`, with `b = d - 1`, `p_win = p_cond * (1 - p_push)`, `p_lose = (1 - p_cond) * (1 - p_push)`, floored at 0 | `betting_policy.kelly_fraction` |

Two remarks derived while writing this document (not stated in the code comments):

- Proportional de-vig is the simplest method and assumes the margin is spread proportionally across the sides. It is known to understate the true probability of long shots relative to favourites; Pinnacle's margin is small, so the effect is small, but it is a modelling choice and not the only one (power and Shin methods exist).
- With pushes, the exact growth-optimal fraction is `(b * p_win - p_lose) / (b * (1 - p_push))`. The code omits the `(1 - p_push)` divisor, so it is slightly conservative on integer lines. Under quarter Kelly and a 2% per-bet cap the difference does not matter in practice.

## 3. Elo: the champion

`analytics/elo.py` is a FiveThirtyEight-style Elo. The champion is registered as `model_version` `elo_538` 1.1.

| Item | Definition or value |
|------|---------------------|
| Rating gap | `diff = R_home + HOME_ADVANTAGE - R_away` |
| Win probability | `p_home = 1 / (1 + 10^(-diff / 400))` |
| Update | `delta = K * mov * (S_home - p_home)`; the home team gains `delta`, the away team loses it (zero-sum) |
| `K` | 20 |
| Margin-of-victory multiplier `mov` | `(|margin| + 3)^0.8 / (7.5 + 0.006 * diff_winner)`, where `diff_winner` is the winner's rating minus the loser's, home edge included. Exponent 0.8 |
| New team | Starts at 1500 |
| New season | On a team's first counted game of a season: `R = 0.75 * R + 0.25 * 1505` |
| Expected home margin | `diff / 28` points (28 Elo points per point) |
| Margin sigma | 14.14 points, from walk-forward residuals of the last five completed seasons; stored in `model_version.params`. Use the registered value, not the unregistered fallback of 12 |
| Games counted | NBA game types 2 (regular season), 4 (playoffs), 5 (play-in), 6 (Cup final). Preseason (1) and all-star (3) are excluded, as are non-NBA teams and 12 neutral-site games with two "away" rows |
| Franchise continuity | NJN to BKN, NOH and NOK to NOP, SEA to OKC |

### Why the home advantage is 60, not 100

FiveThirtyEight used 100 Elo points (3.6 points of margin). Walk-forward residuals over the last five completed seasons (2021-22 to 2025-26) showed the home side overrated by 1.2 to 1.9 points at 100 and about 0 at 60 (2.1 points). The value was tuned in-sample on those same five seasons, so the reported Brier of 0.2167 is slightly optimistic. Source: [`odd/tasks/elo-prediction-recorder.md`](../odd/tasks/elo-prediction-recorder.md).

## 4. Spread probabilities

The home margin `M` is an integer. It is approximated by a normal `N(mu, sigma)` with a continuity correction, so integer lines produce a push probability.

For a home spread line `L`, the home side covers when `M + L > 0`. Let `t = -L`:

| Line type | Home wins | Push | Home loses |
|-----------|-----------|------|------------|
| Half-point (for example -4.5, so `t = 4.5`) | `1 - Phi((floor(t) + 0.5 - mu) / sigma)` | 0 | `Phi((floor(t) + 0.5 - mu) / sigma)` |
| Integer (for example -5, so `t = 5`) | `1 - Phi((t + 0.5 - mu) / sigma)` | `Phi((t + 0.5 - mu) / sigma) - Phi((t - 0.5 - mu) / sigma)` | `Phi((t - 0.5 - mu) / sigma)` |

`mu` is the model's expected home margin (stored in `model_prediction.projection`) and `sigma` its registered margin standard deviation. The away side is the mirror image. Implementation: `elo.spread_probabilities`.

## 5. `margin_features`: the challenger family

`services/margin_features_model.py` with features from `analytics/features.py`. Two heads on the same 12 features: a **ridge regression** for the home margin (gives `mu`) and a **logistic regression** for `P(home win)` (gives `p_home`). Consequence: the h2h probability comes from the logistic head and the spread probabilities from `mu` and `sigma`, so the two markets are not forced to agree.

### The 12 features (all known strictly before tip-off)

| # | Name | Definition |
|---|------|-----------|
| 1 | `elo_edge` | Rating gap including the home edge, from an internal Elo replay with the default parameters (independent of any registry model and its database rows) |
| 2 | `rest_home` | Days since the home team's previous game, capped at 7 (7 when it has none) |
| 3 | `rest_away` | Same for the away team |
| 4 | `b2b_home` | 1 when the home team's previous game was the day before, else 0 |
| 5 | `b2b_away` | Same for the away team |
| 6 | `games7_home` | Games the home team played in the 7 days before the game |
| 7 | `games7_away` | Same for the away team |
| 8 | `margin10_home` | Sum of the home team's point differentials over its last up to 10 games, divided by `(n + 5)` (shrunk toward 0) |
| 9 | `margin10_away` | Same for the away team |
| 10 | `winpct_home` | Season-to-date win rate shrunk toward 0.5: `(wins + 5) / (games + 10)` |
| 11 | `winpct_away` | Same for the away team |
| 12 | `season_progress` | Mean of the two teams' games played this season, divided by 82 |

### Why it is leak-free

One `FeatureState` class serves training and serving. A single chronological pass takes a game's vector **before** adding that game to the history. At prediction time the state is built from the completed games and, if a team already has a game on or after the date, restricted to games strictly before that date. Tip-off times are shifted back 6 hours to land on the US calendar date `player_game_log` uses. The independent leak check (perturbing the future leaves earlier features bit-identical; scrambling the hold-out leaves selection untouched) is recorded in `odd/tasks/model-learning-loop.md` (L2).

### Training

| Step | Detail |
|------|--------|
| Scaling | Standardize with the training mean and standard deviation |
| Ridge | Closed form, unpenalized intercept; penalty from `0.1, 1, 10, 30, 100, 300, 1000, 3000, 10000`, chosen by squared error |
| Logistic | `C` from `0.0003, 0.001, 0.003, 0.01, 0.03, 0.1, 0.3, 1.0`, chosen by log loss |
| Selection | Expanding-window time-series CV over the last 5 training seasons: each is predicted by all seasons before it. Without folds the defaults apply (ridge 300, `C` 0.1) |
| Sigma | Standard deviation of the out-of-fold ridge residuals |
| Deployment | The deployed version is refit on every completed season (the first season of the data is a burn-in and dropped) |
| Storage | `model_version.params` as JSON: feature names, scaler, coefficients, intercepts, penalties, sigma, `trained_through`, seeds. No pickles. Inference is numpy-only |

## 6. Betting policy

`analytics/betting_policy.py`, applied by `prediction_recorder.py`. Changing any value is a **new `model_version`** so every bet stays attributable (rule 8).

### Eligibility

| Rule | Value |
|------|-------|
| Reference | Pinnacle's two-sided pair at one line, de-vigged: `p_fair`. No pair, no bet |
| Raw edge | `p_cond - p_fair >= 0.02` (2 percentage points), same side |
| Blended probability | `p' = 0.5 * p_cond + 0.5 * p_fair` (`ALPHA = 0.5`) |
| EV | Computed with `p'` at the **best price across the 7 books quoted at Pinnacle's line**: `EV >= 0.02` (2%). Ties go to the alphabetically first book |
| Horizon | Games tipping off within 20 hours |
| Quote freshness | The game's newest capture (an odds row or a capture marker) at most 6 hours old |
| Never | At or after tip-off |
| Stale ratings guard | A game is skipped while either team has an earlier game that is not settled |
| Uniqueness | One bet per (strategy, game, market, side) across all runs |
| Markets | h2h and spreads. Totals and props are not modelled or settled |

### Staking

| Strategy | Stake | Caps |
|----------|-------|------|
| `flat` | 1 unit | Per bet 2% of bankroll, daily 10%, per game 4% |
| `kelly_fractional` | `bankroll * f* * 0.25` (quarter Kelly), with `f*` computed from `p'` | Same caps |
| `kelly_shrunk` | `bankroll * f* * multiplier`, where `multiplier = 0.5 * shrink_factor(edge, noise_sd)` | Same caps |
| `market_edge` | 1 unit (flat) when `EV(p_fair, price) >= 0.02`, ignoring model edge | Same caps |

#### Kelly shrinkage (Baker & McHale 2013)
Fixed quarter-Kelly assumes parameter certainty, but in sports betting model estimation error dominates the uncertainty. The `kelly_shrunk` strategy applies the shrinkage factor:
$$k = \frac{\text{edge}^2}{\text{edge}^2 + \sigma_{\text{noise}}^2} \in [0, 1]$$
where:
* $\text{edge} = p_{\text{blend}} - \frac{1}{\text{price}}$ is the edge of the blended win probability over the break-even probability.
* $\sigma_{\text{noise}} = 0.05$ (`MODEL_PROB_NOISE_SD`): an **estimate** of the standard error of the model's win probability, to be calibrated from the model league rather than treated as a known constant.
* Multiplier: $\text{multiplier} = 0.5 \times k$ (`KELLY_MULTIPLIER_SHRUNK_BASE = 0.5`). When edge is large compared to noise, the multiplier approaches half-Kelly; when edge is small or noisy, the stake shrinks smoothly towards zero.

#### Market-edge benchmark arm
`market_edge` serves as an un-modeled benchmark arm:
* Eligibility: takes a price whenever Pinnacle's sharp de-vigged fair probability gives an expected value $\text{EV} = p_{\text{fair}} \times \text{price} - 1 \ge 0.02$ (`MIN_EV`), completely independent of what the model predicts.
* Purpose: separates "the model has skill" from "line shopping the soft book against Pinnacle's fair quote pays".
* Staking: flat 1 unit, subject to the same bankroll, per-bet (2%), daily (10%), and per-game (4%) exposure caps.

Both `kelly_shrunk` and `market_edge` are research hypotheses to be judged by **CLV against Pinnacle's closing line**, not by raw paper ROI (which requires tens of thousands of bets to separate signal from luck).

Other constants: starting bankroll 100 units per strategy; a stake under 0.05 units is not placed; the bankroll is **100 plus settled P/L** (pending stakes are not subtracted); "daily" means the machine-local calendar day.

### Why the policy is deliberately aggressive in the first weeks

Elo cannot see offseason roster moves, so early on it disagrees with Pinnacle a lot (median raw edge 13.8% on the first dry run, 14 of 40 priced sides eligible). The policy was kept as the v1 hypothesis because more bets give a faster verdict on whether the baseline has any edge; it is judged by CLV, not ROI. Source: `odd/tasks/elo-prediction-recorder.md` (E2).

## 7. Settlement, CLV and their biases

### Definitions

| Item | Definition |
|------|-----------|
| Grading, h2h | Bet side against the winner |
| Grading, spreads | `line_taken` is the line of the bet's own side. Bet margin is `home - away` for a home bet and `away - home` for an away bet; `margin + line_taken > 0` wins, `== 0` pushes, `< 0` loses |
| Profit | Win: `stake * (price - 1)`; loss: `-stake`; push: 0 |
| Closing price | The **same sportsbook's** latest quote of the **same market, side and exact line** at or before tip-off, taken from a `closing` capture that is **later than the bet** |
| CLV | `clv_pct = price_taken / closing_price - 1` (decimal prices; a database generated column). Positive means the bet beat the close |
| Line moved | If the book closed at another line, `closing_price` stays NULL (a price at a different line is not comparable); only `closing_line` is stored |
| Brier vs the market | Brier of the champion's h2h home probability against Brier of Pinnacle's de-vigged closing home probability, on the same final games |

### Known biases

| Bias | Why it happens | Effect on the numbers |
|------|----------------|----------------------|
| Coverage | CLV needs a `closing` marker. Games are captured only when the PC is on and a tick runs inside the 30-minute window; 13 of 43 tipped-off games had no closing capture (2026-10-26). It cannot be backfilled on a free plan | Fewer bets carry a CLV; the sample is whatever the PC witnessed |
| Stale close | The feed stores a row only when a book's own update stamp changes. A book that withdrew a market looks "unchanged", so an old quote can pass as the close | CLV can be 0 when the truth is "no longer offered" |
| Survivorship | Bets whose book moved the line have no comparable close and drop out | The average CLV is computed over lines that did not move; 35% of bets had a CLV (2026-10-26) |
| Near-close, not the close | The tick captures the first time a game is inside the 30-minute window, typically 15 to 30 minutes before tip-off, so the last minutes (and late news) are missed | The "close" is slightly earlier than the true close |
| Same-book CLV | CLV is measured against the book where the best price was found, which is often a soft book, not against Pinnacle | A soft book's close is a weaker benchmark; the Pinnacle-based test is the Brier comparison |
| Best-price optimism | The bet takes the best price over 7 books at the instant of the run; a human may not get it | Paper results are an upper bound on what is executable |

## 8. Evaluation protocol

Implemented in `services/model_evaluation.py`.

**Unit of evidence.** A final game for which both the champion and the challenger recorded an h2h home prediction strictly **before** tip-off. A prediction recorded at or after tip-off is excluded and counted (`n_late_excluded`); it could have seen the game, and the recorder is idempotent, so an early prediction that is missing is never repaired. Games only one model predicted are counted as `n_unpaired`.

**Per-game scores** (probabilities clipped to `[1e-6, 1 - 1e-6]`):

| Metric | Definition | Role |
|--------|-----------|------|
| Log loss | `-(y ln p + (1 - y) ln(1 - p))` | Primary |
| Brier | `(p - y)^2` | Secondary |
| Margin NLL | Gaussian negative log-likelihood of the actual margin, with `mu` from `projection` and the model's own sigma | Secondary |
| Market Brier gap | Brier of each model against the de-vigged Pinnacle close, on games that have a closing pair | Guard |

Every "gain" is **champion minus challenger**, so **positive means the challenger is better**.

**Uncertainty.** A seeded paired percentile bootstrap over games (seed 42). One set of resample indices serves every metric, which preserves the pairing. 2,000 resamples for monitoring rows, 5,000 for decision-grade looks. The report shows a plain two-sided 95% interval; decisions use one-sided bounds.

**Multiplicity.** The one-sided error per bound is `alpha / (k * 12)` with `alpha = 0.05`, `k` the number of active challengers and 12 the look budget below (Bonferroni over challengers and looks). That is a confidence of 99.58% for `k = 1` and 99.86% for `k = 3`.

**Look budget.** Re-testing the same challenger at every new batch of games inflates the false-promotion rate. So only **decision-grade looks** may promote, roll back or retire:

| Rule | Value |
|------|-------|
| Spacing | At most one look per challenger every 7 days |
| Budget | At most 12 looks per challenger-champion pairing; a new champion restarts the count |
| Minimum sample | 100 paired games (the smaller of the promotion and retirement gates) |
| Resamples | 5,000 |
| Everything else | A **monitoring row**: same numbers, decision `keep` or `insufficient_data` only, reason prefixed `monitor:` |

A look counts as spent only when the engine could have acted on it, that is, when `LEARNING_AUTOPROMOTE` is on. A cooldown block still spends the look.

## 9. Promotion, retirement and rollback

Decision order in `evaluate_paired` (first match wins). Every constant can be overridden through the `LEARNING_*` settings where noted ([`ARCHITECTURE.md`](ARCHITECTURE.md), section 7).

| # | Decision | Condition |
|---|----------|-----------|
| 1 | `retire` (significantly worse) | `n >= 100`, mean log-loss gain `< 0` and the one-sided **upper** bound `< 0`. Evaluated before the sample gate on purpose, otherwise the 100-game rule would be unreachable |
| 2 | `insufficient_data` | `n < 150` paired games (`LEARNING_MIN_GAMES`) or fewer than 14 days live (`LEARNING_MIN_DAYS_LIVE`) |
| 3 | `retire` (age) | Older than 150 days (`LEARNING_MAX_AGE_DAYS`) with `n >= 300` and the statistical gate not met. When the look budget is spent, this applies on any evaluation, whether or not the gate would pass now |
| 4 | `promote` | All of: lower bound of the log-loss gain `> 0`; lower bound of the margin-NLL gain `> -0.02` nats; when at least 50 games have a market close, the challenger's Brier minus the champion's on those games is at most `0.005`; at least 30 days since the champion's `promoted_at` (`LEARNING_COOLDOWN_DAYS`) |
| 5 | `keep` | Otherwise. If everything but the cooldown passes, the reason says so |

Details that matter:

| Topic | Rule |
|-------|------|
| Age and days live | Counted from the challenger's first recorded h2h home prediction; for the previous champion, from its demotion |
| Rollback | The previous champion (the model the current champion replaced, `parent_id`) is judged on games **since its demotion** only, with the same gate; success is labelled `rollback`. Otherwise the games that dethroned it would retire it a day later |
| One promotion per pass | If several challengers qualify, the one with the largest lower bound wins and goes first; the champion changes, so the pass ends and the others get a `keep` row saying they will be judged against the new champion |
| Atomic swap | The audit row and the role change are one transaction: demote the old champion, promote the new one (`promoted_at`, `parent_id`, `notes`). A failed swap rolls back and writes one `keep` row saying roles are unchanged |
| Protected models | The current Elo reference and the last active Elo model are never retired automatically (`keep`, "last Elo model is protected"); manual retirement needs `--force`. The rating updates and the lab baseline need an Elo model |
| Kill switch | `LEARNING_AUTOPROMOTE=false`: decisions are recorded as `dry_run`, nothing changes, proposed candidates are reported but not registered |
| Slots | At most 3 active challengers (`LEARNING_MAX_CHALLENGERS`) |
| Manual override | `model_league.py promote` and `retire` skip the statistical gate, never the invariants (one champion, atomic swap), and always write an audit row whose reason starts with `manual:`. Promote respects the 30-day cooldown unless `--force` |
| Audit row cadence | A challenger gets a row only when it has paired games it was not evaluated on and none was written the same local day |

## 10. The candidate lab

`services/model_lab.py`, run weekly by the `learn` step or by hand (`scripts/model_lab.py`).

| Item | Value |
|------|-------|
| Time split | `T` = latest completed season (a season is completed when it has at least 80% of the median game count). **Selection** on seasons `[T-9, T-2]` (the first season of the data is a burn-in). **Hold-out** on `[T-1, T]` (2 seasons), never used to choose anything |
| Elo search | 40 seeded random configurations (the tick uses the ISO year and week as the seed, so a new search runs each week and is reproducible from the audit row). Ranges: `K` 10 to 30, home advantage 30 to 110, carryover 0.6 to 0.9, margin exponent 0.6 to 1.0. Ranked by pooled walk-forward log loss on the selection window |
| `margin_features` | Walk-forward on the selection window; one fit through `T-2` for the hold-out; deployment fit on every completed season |
| Baseline | The champion's Elo parameters; if the champion is not an Elo model, the best active Elo model (lowest `brier_oos`), and the report says so |
| Sigma | Estimated walk-forward from the five seasons before each game's season, the same rule for champion and candidates |
| Historical gate | Hold-out log-loss gain `>= 0.0005` and parameters materially different from every active model (K by 1.0, home advantage by 4.0, carryover by 0.02, margin exponent by 0.02; a different family always differs). This gate is a point estimate; the strict statistics are in the live evaluation |
| Registration | Inserts gate-passing candidates as challengers with `parent_id` = champion, version `lab-<date of last training game>-<6-char hash>`, and backfills the ratings of Elo candidates. Refused when 3 challengers are active or, on a non-SQLite database, without `--confirm-database <name>`. The scheduled tick supplies that confirmation itself |
| Time budget | The learn step allows 4 minutes in total; the lab stops gracefully and the report is marked partial |

First real run (2026-10-20, seed 42, 29,642 games): on the 2,631 hold-out games (2024-25 and 2025-26) the champion scored log loss 0.6071, the best Elo from the search 0.6084 (gain -0.0013, rejected) and `margin_features` 0.6045 (gain +0.0026, 95% interval -0.0009 to +0.0063, passes the historical gate). It was registered as the first challenger.

### Multiple-comparison control on the selection window

Evaluating ~40 Elo configurations inflates the apparent outperformance on the selection window (data snooping / selection bias). `analytics/multiple_testing.py` implements three statistical controls:

| Statistic | Method | Definition & Purpose |
|-----------|--------|----------------------|
| `selection_pvalue_rc` | White's Reality Check (White 2000) | Paired bootstrap testing whether the maximum gain across evaluated candidates exceeds what chance produces under the null ($E[d_k] \le 0$). Conservative when inferior models are included. |
| `selection_pvalue_spa` | Hansen's SPA (Hansen 2005) | Studentized statistic ($t_k = \bar{d}_k / \text{se}(\bar{d}_k)$) that recenters only non-clearly-inferior candidates ($t_k \ge -\sqrt{2 \ln(\ln N)}$), avoiding the power loss of Reality Check. |
| `selection_pvalue_dm_hln` | Diebold-Mariano with HLN correction (1997) | Paired forecast test comparing the selected candidate directly with the champion, using the Harvey-Leybourne-Newbold small-sample correction and a Student-t reference ($h=1$). |

By default, these metrics are **report-only** (recorded in `LabReport` and persisted in `model_version.params` / `notes`, with registration behavior unchanged, obeying rule 8). When `LAB_MULTITEST_GATE=true` in `backend/app/config.py` (or `--multitest-gate`), a candidate must additionally achieve `selection_pvalue_spa < 0.20` on the selection window to pass the gate and register as a challenger.

## 11. Simulated error rates

The look budget was designed after an independent statistical attack on the first version. With **equal-skill** models and 8 games a day:

| Protocol | False promotion | False retirement | Source |
|----------|-----------------|------------------|--------|
| One look at day 20 | 4% | - | `odd/tasks/model-learning-loop.md`, look budget note |
| Weekly looks over days 21 to 91 | 15% | - | same |
| Daily looks, no budget | 17.7% | inflated the same way | same |
| Real code, daily evaluations, **with** the budget, `k = 1` (300 trials, 90 days) | 1.0% | 5.3% | same |
| Real code, same protocol, `k = 3` | 0.7% | 1.7% | same |
| Same protocol **without** the budget | about 21% | about 19% | same |

`tests/test_look_budget_simulation.py` (marker `simulation`) reproduces the protocol (60 trials each for `k = 1` and `k = 3`) and asserts that both rates stay under 6%; a control without the budget must exceed 10% combined, and a clearly better challenger must still be promoted within the 12 looks.

These are error rates under the null. They say nothing about power, which is the weak point (next section).

## 12. How to read the reports

### `python scripts/paper_report.py`

Read-only; takes no flags. Sections in order:

| Section | How to read it |
|---------|----------------|
| Strategy performance | One line per strategy. `win rate` = won / (won + lost). `P/L` in units. `ROI` = P/L over the stake of settled bets (pushes included). `avg CLV` and `beat close` are computed only over bets that have a CLV. With fewer than a few hundred bets, treat all of it as noise |
| CLV coverage | "X of Y bets on tipped-off games have a CLV": the share of bets with a comparable close. "closed at another line": bets dropped by the line-move rule. "Closing captures missed": tipped-off games with no `closing` marker, lost for good. A high missed count means the PC was off |
| Model skill of the champion | Brier of the champion against Brier of Pinnacle's de-vigged close on the **same** games. Lower is better. `difference` negative means the model beat the market. Needs a closing marker, a prediction and a two-sided Pinnacle close on a final game |
| Active models | The champion and each challenger with the number of predictions recorded and the final games they cover. Only the champion bets |
| Model league | See below |
| Bankroll | 100 units plus settled P/L per strategy |

### `python scripts/model_league.py status`

First a registry table: `id`, model, `role`, `parent` (the model it was derived from), `preds` (h2h home predictions recorded), `final` (those on final games), last evaluation. Then the same "Model league" section as the report:

| Line | Meaning |
|------|---------|
| `champion ...: N predictions (M on final games), predicting for D days` | How long the champion has been scored live |
| `challenger X: D days live, paired n=a/150` | Paired games so far against the 150 needed |
| `log loss  champion c | challenger x | gain g (95% CI lo .. hi)` | Positive gain means the challenger is better. The interval is the plain two-sided 95% one, wider than the decision bound |
| `margin NLL  gain ...` | The margin likelihood gain; must not be significantly negative |
| `vs market  Brier gap ...` | Each model's Brier minus the market's; the guard applies from 50 games |
| `gate  ...` | The promotion gate in words: `needs N more games`, `needs N more days`, `gate not passed: ...`, `cooldown until DATE`, `gate passed` |
| `looks  ...` | `decision-grade look k of 12 is due` or `monitoring only: ` plus why (not enough games, next look date, budget spent) |
| `last audit  ...; live verdict: ...` | What the engine last wrote and what it would decide right now |
| Promotion and retirement history | Role changes, newest first, manual ones prefixed `manual:` |
| `last candidate proposal DATE: summary` | When the lab last ran and what it found |

Audit `decision` values: `insufficient_data`, `keep`, `promote`, `retire`, `rollback`, `proposal` (a lab run; also the cadence marker), `dry_run` (an action suppressed by the kill switch).

## 13. Limits and honest expectations

| Fact (date) | What it means |
|-------------|---------------|
| Brier 0.2495 for the model against 0.2013 for Pinnacle's close on 30 games (2026-10-26) | The market is better than the baseline, as expected for an Elo with no injury or roster information. Walk-forward history gives Elo a Brier of 0.2167 against a coin flip at 0.25, but that history has no market to compare with (no free historical odds) |
| 56 flat bets, P/L -5.28 u, ROI -11.4% (2026-10-26) | A tiny sample. A unit bet at even odds has a standard deviation near 1 unit, so the standard error of ROI after `N` bets is about `1/sqrt(N)`: resolving a 2% edge at two standard errors takes on the order of 10,000 bets (derived estimate) |
| Average CLV +3.5% flat and +4.8% Kelly over 18 and 12 bets with a comparable close | Noise: tiny sample, 35% coverage, survivorship toward lines that did not move |
| `margin_features` at 41 of 150 paired games, log-loss gain +0.005, interval -0.017 to +0.030 | The interval spans zero by a wide margin |

**Power is the real constraint.** From that 41-game interval, the standard deviation of the per-game log-loss difference is about 0.077 (derived; the estimate is itself noisy). At the corrected confidence of 99.58%, the smallest gain a challenger can prove with `n` paired games is roughly `2.64 * 0.077 / sqrt(n)`:

| Paired games | About | Smallest provable gain (nats per game) |
|--------------|-------|----------------------------------------|
| 300 | The retirement sample, about 5 weeks in season | 0.012 |
| 1,200 | About 150 days at 8 games a day | 0.006 |
| 6,100 | About five seasons | 0.0026 |

The lab's one candidate so far had a historical gain of +0.0026. By this estimate it would need about five seasons of live data to reach the promotion gate. Most candidates will therefore end retired by the age rule. That is the intended conservatism: a promotion needs evidence, and a model whose edge cannot be seen in five months is not worth the risk of a swap. Real progress needs new **signal** (injuries and lineups, totals and props models, better priors), not more hyperparameter search ([`ROADMAP.md`](ROADMAP.md)).

Other limits to keep in mind:

| Limit | Detail |
|-------|--------|
| Paper trading is optimistic | Best price across 7 books, no limits, no slippage, no account restrictions |
| One reference | Pinnacle only; a second sharp source is on the roadmap |
| Elo blind spots | Offseason moves, injuries, rest beyond the schedule |
| In-sample parameter | The home advantage of 60 was tuned on the same seasons used to report its Brier |
| Time zone | "Today" for the opening capture and the daily stake cap is the machine's local day |

## Where each constant lives

| Constants | File |
|-----------|------|
| Elo (`K`, home advantage, carryover, margin exponent, Elo per point) | `backend/app/analytics/elo.py` |
| Betting thresholds, stake caps, bankroll | `backend/app/analytics/betting_policy.py` |
| Horizon 20 h, quote age 6 h, stale-game window | `backend/app/services/prediction_recorder.py` |
| Promotion, retirement, look budget, market guard | `backend/app/services/model_evaluation.py` (overridable via `LEARNING_*` in `backend/app/config.py`) |
| Lab split, search ranges, historical gate, material differences | `backend/app/services/model_lab.py` |
| Features and their shrinkage constants | `backend/app/analytics/features.py` |
| Ridge and logistic grids | `backend/app/services/margin_features_model.py` |
| Credit floor 25, props markets, window 45 min (manual CLI) | `backend/app/services/odds_snapshot.py` |
| Tick window 30 min, props events 1, lock age 20 min, learn budget 240 s | `backend/app/services/tick.py` |
| Result grace 3 h, lookback 14 days | `backend/app/services/results_sync.py` |

## Next step

Operating all of this day to day: [`OPERATIONS.md`](OPERATIONS.md). Why each choice was made: [`DECISIONS.md`](DECISIONS.md).
