# Feature: elo-prediction-recorder

## Objective
Before the 2026-27 opener (2026-10-20): a baseline Elo model for game lines, a recorder that persists every prediction and paper bet at decision time, and a capture routine that starts when the user's PC starts (no fixed hours). Then the back half of the loop: results, settlement and CLV.

## Problem
- `team_elo_rating` is empty; no model exists for game lines. Predictions not saved before tip-off cannot be reconstructed later.
- Capture runs on fixed Windows task times, but the user turns the PC on at variable hours most days.
- Without results sync, ratings and bankroll cannot update after day 1.

## Why
Game lines are the cheapest data under the free quota (3 credits per slate call) and Pinnacle's de-vigged close is the benchmark. A baseline that is measured honestly (Brier, CLV) is the foundation for any later self-improvement.

## Data facts (verified 2026-10-17)
- `player_game_log`: 23 seasons (2003-04 .. 2025-26), 31,646 game_ids with two teams each (5 with one team: skip). Team score = sum of `pts` per (game_id, team_id). Home/away from `matchup` ('LAC vs. OKC' = home, 'OKC @ LAC' = away).
- NBA game_id 3rd character = type: 1 preseason (exclude), 2 regular, 3 all-star (exclude), 4 playoffs, 5 play-in, 6 NBA Cup final.
- Franchise continuity: NJN→BKN, NOH/NOK→NOP, SEA→OKC (verify any other abbreviations). `team` has junk non-NBA rows (EST, WST, MAC, NZB, ...): skip games with a non-NBA team.
- 46 upcoming `game` rows (all status scheduled) resolve to the 30 current teams; their season_id is wrongly 2025-26 (no 2026-27 season row exists).

## Scope
- E1 Elo engine (538 style), idempotent backfill into `team_elo_rating`, walk-forward evaluation, `model_version` registration.
- E2 Prediction recorder + paper betting policy (flat and quarter-Kelly) writing `model_prediction` / `simulated_bet`.
- E3 One auto tick (capture + recorder) run by a Windows task at log on, repeating every 15 min while the user is logged on.
- E4 Results sync (nba_api LeagueGameLog, free), incremental Elo update, bet settlement, CLV fill.

## Design decisions
- Elo: K=20, home advantage 100, initial 1500, season carryover r = 0.75*r + 0.25*1505, MOV multiplier ((|MOV|+3)^0.8)/(7.5+0.006*elo_diff_winner), expected margin = elo_diff/28, win prob 1/(1+10^(-diff/400)). Sigma of margin estimated from walk-forward residuals and stored in model_version.params.
- Spread probabilities use a discrete (continuity-corrected) normal so integer lines yield p_win, p_push, p_loss.
- v1 markets: h2h and spreads. Totals not modeled.
- Betting policy: blend p' = 0.5*p_model + 0.5*p_fair (Pinnacle de-vigged at the same line); bet only if (p_model - p_fair) >= 2pp for that side AND EV computed with p' at the best available price >= 2%; best price across books; one bet per (strategy, game, market, side); horizon 20 h; quote age <= 6 h; never after tip-off; skip a game if either team has an earlier non-final game (stale ratings). Flat 1u and quarter Kelly capped 2% bankroll per bet, 10% daily, 4% per game; bankroll = 100 + settled P/L per strategy.
- CLV is valid only for games with a `closing` capture marker (a closing price from a stale opening snapshot must never count). Same-line only in v1.
- Logon task: one task `NBA-Odds-Tick` (XML-registered, LogonTrigger + repetition 15 min indefinite, MultipleInstances IgnoreNew, StartWhenAvailable, runs only while the user is logged on). Missed tip-offs cannot be backfilled on free tiers.

## Constraints
- Free tiers only (Odds API 500 credits/month, 494 left). nba_api is free.
- Real DB: native PostgreSQL 18.4 (config.py loads backend/.env with override=True). Tests: in-memory SQLite.
- Artifacts in English; PowerShell console text in Spanish like the other scripts.
- User authorized (2026-10-17) PRs and merges to main for this work.

## TDD
- Mode: off. Source: no project/session TDD configuration. Runner: `python -m pytest -q` from `backend/`.

## Delivery
- Strategy: ask-on-risk; chain strategy stacked-to-main. Each slice is merged to main as soon as it is verified (user authorization), then the next branch starts from updated main. Forecast ~2,500 changed lines across 4 PRs (size:exception each).
- RDD: on (default); assess each work-unit commit.

## Tasks
- [x] E1 Elo engine, backfill, evaluation, model_version — route: delegated writer (PR A, branch feat/elo-baseline-model). Commits 090cf39 (engine), 0a017cd (service + CLI) plus parent follow-up: HOME_ADVANTAGE 100→60 (walk-forward bias of 1.2-1.9 points on 2021-22..2025-26 at 100, ~0 at 60; tuned in-sample), model_version elo_538 v1.1, class renamed `EloRatingService` (legacy `app.services.elo.EloService` untouched). Real backfill run: 29,641 games, 59,282 rating rows, 30 teams, 0 upcoming games without ratings. Walk-forward last 5 completed seasons: Brier 0.2167, sigma 14.14 (use the registered sigma, not 12). 12 neutral-site games (NBA Cup/international, both rows '@') skipped. Checks: pytest 229 passed.
- [x] E2 Prediction recorder + betting policy + unique (prediction_id, strategy) — route: delegated writer (PR B). Commits c4a850e (season resolution/creation + hide empty seasons in /api/v1/seasons), e087f4b (betting_policy.py + migration c4e8a1d63f27), 5389b92 (PredictionRecorder + record_predictions.py CLI). Applied to the real DB: migration c4e8a1d63f27, 46 games re-pointed to the new 2026-27 season (inactive; frontend default unchanged). Checks: pytest 284 passed; offline alembic up/down render. Real-data dry run on cached Oct-17 quotes: 14 of 40 priced sides eligible (35%), median raw edge 13.8% = Elo (blind to offseason roster changes) disagreeing with Pinnacle; daily 10u cap limits flat bets. Decision: keep the policy as the v1 hypothesis (more samples = faster verdict on whether the baseline has any edge vs the close); judge it by CLV, not ROI. A policy change must be registered as a new model_version so bets stay attributable.
- [x] E3 Auto tick + logon task replacing NBA-Odds-Opening/Closing — route: delegated writer (PR C). Commits 397fdf5 (`tick.py` + `run_tick.py`: steps opening/closing/record isolated, lock file, rotating `logs/tick.log`, missed-closing report), f676740 (`register_tick_task.ps1`: task `NBA-Odds-Tick` XML with LogonTrigger; legacy tasks removed; old register script deleted), parent follow-up: added a TimeTrigger so the 15-min repetition starts immediately and continues between sessions. Checks: pytest 317 passed; `-WhatIf` XML validated. Registration against Windows still to be done in E5.
- [ ] E4 Results sync, incremental Elo, settlement, CLV — route: delegated writer (PR D)
- [ ] E5 Operate: run backfill on the real DB, apply migrations, register the logon task, verify — route: inline

## Acceptance criteria
- Walk-forward Brier of Elo win probability reported per season, last 5 seasons ~0.20-0.22 (sanity: better than coin flip 0.25).
- All 30 current teams have ratings; every one of the 46 upcoming games gets an h2h prediction.
- Recorder is idempotent; never writes a bet at or after tip-off; two strategies per eligible bet; documented skip reasons.
- Tick: one task, logon-triggered, no overlapping runs, exit code reflects failures.

## Checks
- `cd backend && python -m pytest -q` (baseline 168)
- `alembic upgrade head` on the real DB after each migration

## Progress
- Branch feat/elo-baseline-model created from main after PRs #1-#7 merged (main ec12e49).

## Follow-ups (out of scope)
- Totals model; props model recorded through the same tables.
- Shutdown endpoint CSRF hardening (separate spawned task).
- Champion/challenger retraining with promotion gates.
- SportsGameOdds second feed.
- Excel legacy cleanup.

## Notes for E2/E4 (resolved in E2: recorder derives the season from the tip-off date and applies carryover)
- `EloRatingService.current_ratings(for_season_id=...)` applies the 25% regression once when a team's latest game is in an earlier season; `game.season_id` is wrong for 2026-27 (no season row), so the recorder must create/resolve the 2026-27 season and pass it explicitly. Opening-night ratings must include the carryover.
- Sigma comes from the registered model_version (14.14).
- Season ids are not chronological (2023-24 is id 1): order by season_label.

## Next step
Merge PR C, register the task (E5), then E4 (results sync, settlement, CLV).
