"""
Simulation of the look budget: equal-skill models, 8 games a day, an evaluation EVERY day for 90 days.

The pre-fix engine re-tested the same challenger at confidence 1 - 0.05/k at every new batch of games, which inflates
the family-wise false-promotion (and false-retirement) rate far above the nominal 5%: measured with these very
protocols, daily looks promoted equal models about 17% of the time. With the look budget only one evaluation a week
(at most 12) may act, each at confidence 1 - 0.05 / (k * 12), and the rates must stay under 6% per challenger.

``simulate_protocol`` is also what produced the numbers quoted in odd/tasks/model-learning-loop.md (run it with more
trials and ``decision_resamples=5000`` for the full-strength figures).
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from app.services import model_evaluation as ev
from tests.test_model_evaluation import paired_data, simulate

pytestmark = pytest.mark.simulation

START = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
GAMES_PER_DAY = 8
DAYS = 90
ACTIONS = (ev.DECISION_PROMOTE, ev.DECISION_ROLLBACK, ev.DECISION_RETIRE)


@dataclass
class Tally:
    trials: int = 0
    promoted: int = 0
    retired: int = 0
    first_promotion_day: float = float("nan")
    monitor_actions: int = 0  # an action on a day that was not a decision-grade look (must stay 0)

    @property
    def promotion_rate(self) -> float:
        return self.promoted / max(1, self.trials)

    @property
    def retirement_rate(self) -> float:
        return self.retired / max(1, self.trials)


def run_trial(arrays, k, config, *, budget=True):
    """One challenger over DAYS daily evaluations; returns (decision, day, monitor_action_seen)."""
    looks_taken, last_look_at = 0, None
    monitor_action = False
    for day in range(1, DAYS + 1):
        n = day * GAMES_PER_DAY
        now = START + timedelta(days=day)
        data = paired_data(*(array[:n] for array in arrays))
        if budget:
            look = ev.plan_look(config, looks_taken=looks_taken, last_look_at=last_look_at, now=now, n_games=n)
        else:  # the pre-fix behavior: every evaluation may act, at confidence 1 - alpha / k
            look = ev.LookPlan(True, 1, 1, False)
        result = ev.evaluate_paired(
            data, now=now, days_live=float(day), age_days=float(day), days_since_promotion=None, k=k, config=config, look=look
        )
        if look.decision_grade:
            looks_taken, last_look_at = looks_taken + 1, now
        elif result.decision in ACTIONS:
            monitor_action = True
        if result.decision in ACTIONS:
            return result.decision, day, monitor_action
    return None, DAYS, monitor_action


def simulate_protocol(k, trials, *, decision_resamples=1000, seed0=1000, challenger_noise=5.0, budget=True):
    config = ev.EvaluationConfig(resamples=100, decision_resamples=decision_resamples)
    tally = Tally()
    days = []
    for trial in range(trials):
        arrays = simulate(DAYS * GAMES_PER_DAY, seed0 + trial, 5.0, challenger_noise)
        decision, day, monitor_action = run_trial(arrays, k, config, budget=budget)
        tally.trials += 1
        tally.monitor_actions += monitor_action
        if decision in (ev.DECISION_PROMOTE, ev.DECISION_ROLLBACK):
            tally.promoted += 1
            days.append(day)
        elif decision == ev.DECISION_RETIRE:
            tally.retired += 1
    if days:
        tally.first_promotion_day = float(np.mean(days))
    return tally


@pytest.mark.parametrize("k", [1, 3])
def test_equal_models_evaluated_daily_stay_under_six_percent_false_promotion_and_retirement(k):
    tally = simulate_protocol(k, trials=60)

    assert tally.monitor_actions == 0  # a monitoring evaluation never acts
    assert tally.promotion_rate < 0.06, f"false promotions {tally.promotion_rate:.1%} with k={k}"
    assert tally.retirement_rate < 0.06, f"spurious retirements {tally.retirement_rate:.1%} with k={k}"


def test_without_the_look_budget_the_same_daily_protocol_inflates_the_error_rate():
    """The control: acting at every daily evaluation (the pre-fix behavior) is what the budget exists to prevent."""
    tally = simulate_protocol(1, trials=40, decision_resamples=300, budget=False)

    assert tally.promotion_rate + tally.retirement_rate > 0.10


def test_a_clearly_better_challenger_is_still_promoted_within_the_budget():
    config = ev.EvaluationConfig(resamples=100, decision_resamples=1000)
    promoted_on = []
    for seed in range(5):
        arrays = simulate(DAYS * GAMES_PER_DAY, 40 + seed, 7.0, 1.0)  # a large true gain
        decision, day, _ = run_trial(arrays, 3, config)
        assert decision == ev.DECISION_PROMOTE, f"seed {seed}: {decision}"
        promoted_on.append(day)
    # inside the 12 weekly looks, and typically at the second or third one: the first is at 100 games (day 13, still
    # inside the 14-day live gate) and the following ones a week apart
    assert max(promoted_on) <= 13 + 7 * 11
    assert sorted(promoted_on)[len(promoted_on) // 2] <= 13 + 7 * 3
