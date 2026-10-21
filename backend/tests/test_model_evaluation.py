"""Paired live evaluation: collection rules, metrics, the bootstrap and the decision rules."""
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import numpy as np
import pytest

from app.models import (
    CAPTURE_CLOSING,
    BetSide,
    Game,
    MarketType,
    ModelPrediction,
    ModelVersion,
    OddsHistory,
    OddsSnapshotCapture,
    Season,
    Sportsbook,
    Team,
)
from app.services import model_evaluation as ev

NOW = datetime(2026, 12, 1, 18, 0, tzinfo=timezone.utc)
SIGMA = 12.0
LONG_AGO = NOW - timedelta(days=400)


# ------------------------------------------------------------------------------------ synthetic evidence

def _p_from_mu(mu):
    return 1.0 / (1.0 + np.exp(-np.asarray(mu) / 6.6))


def simulate(n, seed, champion_noise, challenger_noise, challenger_bias=0.0):
    """
    A league of ``n`` games with a known expected margin ``m``; each model sees ``m`` through its own noise
    (smaller = better). Returns arrays (win, margin, mu_champion, mu_challenger).
    """
    rng = np.random.default_rng(seed)
    m = rng.normal(2.0, 6.0, n)
    margin = m + rng.normal(0.0, SIGMA, n)
    win = (margin > 0).astype(float)
    mu_champion = m + rng.normal(0.0, champion_noise, n)
    mu_challenger = m + challenger_bias + rng.normal(0.0, challenger_noise, n)
    return win, margin, mu_champion, mu_challenger


def paired_data(win, margin, mu_champion, mu_challenger, market_p=None, first_prediction_at=None):
    n = len(win)
    return ev.PairedData(
        champion_id=1,
        challenger_id=2,
        game_ids=np.arange(n, dtype=np.int64),
        win=np.asarray(win, dtype=float),
        margin=np.asarray(margin, dtype=float),
        p_champion=_p_from_mu(mu_champion),
        p_challenger=_p_from_mu(mu_challenger),
        mu_champion=np.asarray(mu_champion, dtype=float),
        mu_challenger=np.asarray(mu_challenger, dtype=float),
        sigma_champion=SIGMA,
        sigma_challenger=SIGMA,
        market_p=np.full(n, np.nan) if market_p is None else np.asarray(market_p, dtype=float),
        first_prediction_at=first_prediction_at,
    )


def judge(data, *, k=1, days_live=40.0, age_days=40.0, days_since_promotion=None, resamples=600, previous_champion=False, **config):
    return ev.evaluate_paired(
        data,
        now=NOW,
        days_live=days_live,
        age_days=age_days,
        days_since_promotion=days_since_promotion,
        k=k,
        config=ev.EvaluationConfig(resamples=resamples, **config),
        previous_champion=previous_champion,
    )


# ------------------------------------------------------------------------------------------ database world

class League:
    """Two models and final games with their predictions, written to the (in-memory) database."""

    def __init__(self, session):
        self.session = session
        self.season = Season(season_label="2026-27", is_active=True)
        self.teams = [Team(abbreviation=a, full_name=a, city=a, conference="E", division="A") for a in ("AAA", "BBB")]
        self.pinnacle = Sportsbook(key="pinnacle", name="Pinnacle", region="eu", is_sharp=True)
        session.add_all([self.season, *self.teams, self.pinnacle])
        self.champion = ModelVersion(
            name="elo_538", version="1.1", role="champion", params={"sigma": SIGMA}, promoted_at=LONG_AGO
        )
        self.challenger = ModelVersion(name="elo_538", version="lab-x", role="challenger", params={"sigma": SIGMA})
        session.add_all([self.champion, self.challenger])
        session.commit()
        self.games = []

    def game(self, hours_before_now, home_score=110, away_score=100, status="final"):
        game = Game(
            provider_event_id=f"evt-{len(self.games)}",
            season_id=self.season.id,
            home_team_id=self.teams[0].id,
            away_team_id=self.teams[1].id,
            commence_time=NOW - timedelta(hours=hours_before_now),
            status=status,
            home_score=home_score if status == "final" else None,
            away_score=away_score if status == "final" else None,
        )
        self.session.add(game)
        self.session.commit()
        self.games.append(game)
        return game

    def predict(self, model, game, p, mu, at=None, market=MarketType.h2h, side=BetSide.home, line=None):
        at = at or game.commence_time - timedelta(hours=3)
        row = ModelPrediction(
            model_version_id=model.id,
            game_id=game.id,
            market=market,
            side=side,
            line=None if line is None else Decimal(str(line)),
            model_prob=Decimal(f"{min(max(float(p), 1e-4), 1 - 1e-4):.5f}"),
            projection=Decimal(f"{float(mu):.2f}"),
            predicted_at=at,
        )
        self.session.add(row)
        self.session.commit()
        return row

    def populate(self, win, margin, mu_champion, mu_challenger, days):
        """Games spread evenly over the last ``days`` days, both models predicting each 3 hours before tip-off."""
        n = len(win)
        for i in range(n):
            points = int(round(margin[i])) or (1 if win[i] else -1)
            game = self.game(
                (n - i) * days * 24.0 / n + 3.0, home_score=100 + max(points, 0), away_score=100 + max(-points, 0)
            )
            self.predict(self.champion, game, _p_from_mu(mu_champion[i]), mu_champion[i])
            self.predict(self.challenger, game, _p_from_mu(mu_challenger[i]), mu_challenger[i])


@pytest.fixture
def league(db_session):
    return League(db_session)


def _evaluate(league, config=None):
    return ev.evaluate_challenger(
        league.session, league.challenger, league.champion, NOW, config or ev.EvaluationConfig(resamples=600, n_challengers=1)
    )


# --------------------------------------------------------------------------------------------- collection

def test_collection_pairs_games_and_excludes_late_unpaired_and_other_markets(league):
    champion, challenger = league.champion, league.challenger
    on_time = league.game(30)
    league.predict(champion, on_time, 0.60, 4.0)
    league.predict(challenger, on_time, 0.70, 6.0)
    # the challenger only predicted after tip-off: excluded and counted
    late = league.game(20)
    league.predict(champion, late, 0.55, 2.0)
    league.predict(challenger, late, 0.99, 25.0, at=late.commence_time + timedelta(minutes=1))
    # recorded exactly at tip-off is already too late
    at_tip = league.game(15)
    league.predict(champion, at_tip, 0.55, 2.0)
    league.predict(challenger, at_tip, 0.99, 25.0, at=at_tip.commence_time)
    # only the champion predicted: unpaired
    unpaired = league.game(10)
    league.predict(champion, unpaired, 0.55, 2.0)
    # not final yet and a spreads prediction: neither is evidence
    pending = league.game(5, status="scheduled")
    league.predict(champion, pending, 0.55, 2.0)
    league.predict(challenger, pending, 0.55, 2.0)
    league.predict(champion, on_time, 0.5, 4.0, market=MarketType.spreads, side=BetSide.home, line=-3.5)

    data = ev.collect_paired_games(league.session, champion.id, challenger.id)

    assert data.n == 1 and data.game_ids.tolist() == [on_time.id]
    assert data.p_champion.tolist() == [0.6] and data.p_challenger.tolist() == [0.7]
    assert data.mu_champion.tolist() == [4.0] and data.mu_challenger.tolist() == [6.0]
    assert data.win.tolist() == [1.0] and data.margin.tolist() == [10.0]
    assert (data.n_late_excluded, data.n_unpaired) == (2, 1)
    assert data.sigma_champion == data.sigma_challenger == SIGMA
    assert data.first_prediction_at is not None and data.n_market == 0


def test_a_duplicate_recorded_after_tip_off_cannot_change_the_evidence(league):
    game = league.game(30)
    league.predict(league.champion, game, 0.60, 4.0)
    league.predict(league.challenger, game, 0.70, 6.0)
    before = ev.collect_paired_games(league.session, league.champion.id, league.challenger.id)
    # SQLite does not enforce the NULL-aware unique key, so a second row for the same target can exist there
    league.predict(league.challenger, game, 0.01, -30.0, at=game.commence_time + timedelta(hours=1))
    after = ev.collect_paired_games(league.session, league.champion.id, league.challenger.id)
    assert before.p_challenger.tolist() == after.p_challenger.tolist() == [0.7]
    assert after.n_late_excluded == 0


def test_market_probability_needs_a_closing_marker_and_a_two_sided_sharp_pair_before_tip_off(league):
    with_close, late_quote, no_marker = league.game(30), league.game(20), league.game(10)
    for game in (with_close, late_quote, no_marker):
        league.predict(league.champion, game, 0.6, 4.0)
        league.predict(league.challenger, game, 0.6, 4.0)

    def quote(game, side, price, at):
        league.session.add(
            OddsHistory(
                game_id=game.id, sportsbook_id=league.pinnacle.id, market=MarketType.h2h, side=side,
                price_american=price, book_last_update=at, captured_at=at,
            )
        )

    for game, at in ((with_close, with_close.commence_time - timedelta(minutes=10)),
                     (late_quote, late_quote.commence_time + timedelta(minutes=10)),
                     (no_marker, no_marker.commence_time - timedelta(minutes=10))):
        quote(game, BetSide.home, -150, at)
        quote(game, BetSide.away, 130, at)
    for game in (with_close, late_quote):
        league.session.add(OddsSnapshotCapture(game_id=game.id, kind=CAPTURE_CLOSING, captured_at=game.commence_time))
    league.session.commit()

    data = ev.collect_paired_games(league.session, league.champion.id, league.challenger.id)

    by_game = dict(zip(data.game_ids.tolist(), data.market_p.tolist()))
    assert by_game[with_close.id] == pytest.approx((1 / 1.6667) / (1 / 1.6667 + 1 / 2.3), abs=1e-3)
    assert np.isnan(by_game[late_quote.id]) and np.isnan(by_game[no_marker.id])
    assert data.n_market == 1


def test_a_model_cannot_be_paired_with_itself(league):
    with pytest.raises(ValueError):
        ev.collect_paired_games(league.session, league.champion.id, league.champion.id)


# --------------------------------------------------------------------------------------------- metrics

def test_the_metrics_match_a_hand_computation():
    data = paired_data([1, 0], [8, -4], [6.0, 2.0], [10.0, -3.0])
    result = judge(data, resamples=200)

    p_c, p_h = _p_from_mu([6.0, 2.0]), _p_from_mu([10.0, -3.0])
    expected_c = -(np.log(p_c[0]) + np.log(1 - p_c[1])) / 2
    expected_h = -(np.log(p_h[0]) + np.log(1 - p_h[1])) / 2
    assert result.champion.log_loss == pytest.approx(expected_c)
    assert result.challenger.log_loss == pytest.approx(expected_h)
    assert result.log_loss_gain.mean == pytest.approx(expected_c - expected_h)  # positive = challenger better
    assert result.champion.brier == pytest.approx(((p_c[0] - 1) ** 2 + p_c[1] ** 2) / 2)
    nll = lambda mu, margin: 0.5 * np.log(2 * np.pi * SIGMA**2) + (margin - mu) ** 2 / (2 * SIGMA**2)
    assert result.champion.margin_nll == pytest.approx((nll(6, 8) + nll(2, -4)) / 2)
    assert result.margin_nll_gain.mean == pytest.approx((nll(6, 8) + nll(2, -4)) / 2 - (nll(10, 8) + nll(-3, -4)) / 2)


def test_probabilities_are_clipped_so_a_certain_wrong_prediction_is_finite():
    data = paired_data([1.0], [5.0], [5.0], [5.0])
    data.p_challenger = np.array([0.0])
    result = judge(data, resamples=50)
    assert result.challenger.log_loss == pytest.approx(-np.log(1e-6))
    assert np.isfinite(result.log_loss_gain.mean)


def test_market_comparison_reports_each_models_gap_to_the_market():
    win, margin, mu_c, mu_h = simulate(200, 5, 6.0, 6.0)
    market = np.where(np.arange(200) < 80, 0.5, np.nan)
    result = judge(paired_data(win, margin, mu_c, mu_h, market_p=market))

    assert result.n_market_games == 80 and result.market.n == 80
    rows = ~np.isnan(market)
    assert result.market.brier_market == pytest.approx(((0.5 - win[rows]) ** 2).mean())
    assert result.market.gap_champion == pytest.approx(result.market.brier_champion - result.market.brier_market)
    assert result.market.gap_difference == pytest.approx(result.market.gap_challenger - result.market.gap_champion)


def test_the_bootstrap_interval_agrees_with_the_analytic_one():
    win, margin, mu_c, mu_h = simulate(600, 11, 6.0, 3.0)
    result = judge(paired_data(win, margin, mu_c, mu_h), resamples=2000)

    gains = ev.log_loss_each(_p_from_mu(mu_c), win) - ev.log_loss_each(_p_from_mu(mu_h), win)
    half = 1.96 * gains.std(ddof=1) / np.sqrt(len(gains))
    assert result.log_loss_gain.mean == pytest.approx(gains.mean())
    assert result.log_loss_gain.ci_low == pytest.approx(gains.mean() - half, abs=0.15 * half)
    assert result.log_loss_gain.ci_high == pytest.approx(gains.mean() + half, abs=0.15 * half)
    assert result.log_loss_gain.ci_low < result.log_loss_gain.bound_low < result.log_loss_gain.mean  # one-sided 95% > two-sided 95%


def test_the_result_is_deterministic_for_a_seed_and_changes_with_it():
    data = paired_data(*simulate(300, 2, 6.0, 4.0))
    first, second = judge(data, seed=7), judge(data, seed=7)
    assert first.to_metrics() == second.to_metrics()
    other = judge(data, seed=8)
    assert other.log_loss_gain.mean == first.log_loss_gain.mean
    assert other.log_loss_gain.bound_low != first.log_loss_gain.bound_low


def test_the_metrics_payload_is_json_safe_and_carries_the_seed_thresholds_and_k():
    result = judge(paired_data(*simulate(200, 3, 6.0, 4.0)), k=3)
    payload = result.to_metrics()
    assert json.loads(json.dumps(payload)) == payload
    assert payload["seed"] == ev.SEED and payload["k"] == 3 and payload["resamples"] == 600
    assert payload["confidence"] == pytest.approx(1 - 0.05 / 3)
    assert payload["thresholds"]["min_games"] == 150 and payload["thresholds"]["cooldown_days"] == 30
    assert payload["decision"] == result.decision and payload["market"] is None


def test_an_empty_evidence_set_evaluates_without_crashing():
    empty = paired_data([], [], [], [])
    result = judge(empty)
    assert result.decision == ev.DECISION_INSUFFICIENT and result.n_games == 0
    assert result.log_loss_gain.bound_low is None and result.champion is None
    assert result.gate_text.startswith("needs 150 more games")


# -------------------------------------------------------------------------------------------- decisions

def test_a_clearly_better_challenger_is_promoted_only_once_games_and_days_are_enough(league):
    win, margin, mu_c, mu_h = simulate(400, 21, 7.0, 1.0)
    league.populate(win, margin, mu_c, mu_h, days=40)
    config = ev.EvaluationConfig(resamples=600, n_challengers=1)

    promoted = _evaluate(league, config)
    assert promoted.decision == ev.DECISION_PROMOTE and promoted.n_games == 400
    assert promoted.days_live == pytest.approx(40.25, abs=0.05)
    assert promoted.log_loss_gain.bound_low > 0 and promoted.gate_text == "gate passed"

    # same quality, but the evidence is younger than 14 days
    young = ev.collect_paired_games(league.session, league.champion.id, league.challenger.id)
    too_young = ev.evaluate_challenger(
        league.session, league.challenger, league.champion, NOW - timedelta(days=30), config, data=young
    )
    assert too_young.decision == ev.DECISION_INSUFFICIENT and "days live" in too_young.reason
    assert too_young.gate_text.startswith("needs") and "days" in too_young.gate_text


def test_too_few_games_is_insufficient_even_when_the_challenger_is_excellent():
    data = paired_data(*simulate(120, 4, 8.0, 0.5))
    result = judge(data)
    assert result.decision == ev.DECISION_INSUFFICIENT and result.reason.startswith("not enough evidence")
    assert "30 more games" in result.gate_text


def test_the_promotion_cooldown_keeps_the_champion_and_says_until_when():
    data = paired_data(*simulate(400, 21, 7.0, 1.0))
    assert judge(data, days_since_promotion=None).decision == ev.DECISION_PROMOTE
    blocked = judge(data, days_since_promotion=12.0)
    assert blocked.decision == ev.DECISION_KEEP and "cooldown until" in blocked.reason
    assert blocked.cooldown_until.date() == (NOW + timedelta(days=18)).date()
    assert blocked.gate_text == f"cooldown until {blocked.cooldown_until.date().isoformat()}"
    assert judge(data, days_since_promotion=30.0).decision == ev.DECISION_PROMOTE


def test_a_significantly_worse_challenger_is_retired_from_100_games():
    data = paired_data(*simulate(110, 8, 1.0, 9.0))
    result = judge(data, days_live=3.0)  # even before the promotion gate could open
    assert result.decision == ev.DECISION_RETIRE and "significantly worse" in result.reason
    assert result.log_loss_gain.bound_high < 0

    fewer = paired_data(*simulate(90, 8, 1.0, 9.0))
    assert judge(fewer).decision == ev.DECISION_INSUFFICIENT  # not at 90 games


def test_an_old_challenger_without_a_pass_is_retired_after_90_days_and_300_games():
    data = paired_data(*simulate(320, 31, 5.0, 5.0))  # equal quality: no significant gain, not significantly worse
    assert judge(data, age_days=60.0).decision == ev.DECISION_KEEP
    old = judge(data, age_days=95.0)
    assert old.decision == ev.DECISION_RETIRE and "promotion gate not met" in old.reason
    assert judge(paired_data(*simulate(250, 31, 5.0, 5.0)), age_days=95.0).decision == ev.DECISION_KEEP  # < 300 games
    good = paired_data(*simulate(400, 21, 7.0, 1.0))
    assert judge(good, age_days=95.0, days_since_promotion=5.0).decision == ev.DECISION_KEEP  # gate met, only the cooldown blocks


def test_the_previous_champion_returning_is_a_rollback():
    data = paired_data(*simulate(400, 21, 7.0, 1.0))
    assert judge(data, previous_champion=True).decision == ev.DECISION_ROLLBACK


def test_the_margin_guard_blocks_a_challenger_whose_margin_is_much_worse():
    win, margin, mu_c, mu_h = simulate(400, 21, 7.0, 1.0)
    data = paired_data(win, margin, mu_c, mu_h)
    data.mu_challenger = data.mu_challenger + 15.0  # probabilities stay good, the expected margin is badly biased
    result = judge(data)
    assert result.log_loss_gain.bound_low > 0 and result.margin_nll_gain.bound_low < -0.02
    assert result.decision == ev.DECISION_KEEP and "margin NLL" in result.reason


def test_the_market_guard_blocks_a_challenger_that_drifts_from_the_market():
    win, margin, mu_c, mu_h = simulate(400, 21, 7.0, 1.0)
    data = paired_data(win, margin, mu_c, mu_h)
    # the first 80 games have a market probability that tracks the champion; there the challenger just says 50/50
    data.p_champion[:80] = np.where(win[:80] == 1.0, 0.62, 0.38)
    data.market_p[:80] = data.p_champion[:80]
    data.p_challenger[:80] = 0.5
    result = judge(data)
    assert result.n_market_games == 80
    assert result.market.gap_difference > 0.005
    assert result.log_loss_gain.bound_low > 0  # the rest of the evidence is overwhelming
    assert result.decision == ev.DECISION_KEEP and "market Brier gap" in result.reason
    assert result.gate_text == "gate not passed: worse than the champion against the market"

    market = np.full(data.n, np.nan)
    market[:40] = data.market_p[:40]  # under 50 market games the guard is not applied
    assert judge(replace(data, market_p=market)).decision == ev.DECISION_PROMOTE


def test_bonferroni_makes_the_bound_stricter_with_more_challengers():
    data = paired_data(*simulate(300, 17, 6.0, 4.5))
    one, three = judge(data, k=1), judge(data, k=3)
    assert three.log_loss_gain.bound_low < one.log_loss_gain.bound_low
    assert three.confidence == pytest.approx(1 - 0.05 / 3) and one.confidence == pytest.approx(0.95)

    # a marginal improvement that passes alone but not as one of three
    for seed in range(300):
        marginal = paired_data(*simulate(300, seed, 6.0, 5.2))
        alone = judge(marginal, k=1, resamples=400)
        if alone.decision == ev.DECISION_PROMOTE and judge(marginal, k=3, resamples=400).decision == ev.DECISION_KEEP:
            return
    pytest.fail("no marginal case separated k=1 from k=3")


def test_equal_models_are_almost_never_promoted_at_the_bonferroni_level():
    trials, promoted = 400, {1: 0, 3: 0}
    retired = 0
    for seed in range(trials):
        data = paired_data(*simulate(300, 1000 + seed, 5.0, 5.0))
        for k in promoted:
            result = judge(data, k=k, resamples=400)
            promoted[k] += result.decision in (ev.DECISION_PROMOTE, ev.DECISION_ROLLBACK)
            if k == 1:
                retired += result.decision == ev.DECISION_RETIRE
    assert promoted[1] / trials < 0.08  # nominal 5% (one challenger)
    assert promoted[3] / trials < 0.05  # nominal 1.7% (three challengers)
    assert retired / trials < 0.08


def test_thresholds_can_be_overridden_from_settings():
    settings = SimpleNamespace(LEARNING_MIN_GAMES=40, LEARNING_MIN_DAYS_LIVE=2, LEARNING_COOLDOWN_DAYS=5)
    config = ev.EvaluationConfig.from_settings(settings, resamples=300)
    assert (config.min_games, config.min_days_live, config.cooldown_days, config.resamples) == (40, 2.0, 5.0, 300)
    data = paired_data(*simulate(60, 2, 9.0, 0.5))
    result = ev.evaluate_paired(
        data, now=NOW, days_live=3.0, age_days=3.0, days_since_promotion=6.0, k=1, config=config
    )
    assert result.decision == ev.DECISION_PROMOTE
    defaults = ev.EvaluationConfig.from_settings(SimpleNamespace())
    assert (defaults.min_games, defaults.min_days_live, defaults.cooldown_days) == (150, 14.0, 30.0)


def test_the_settings_defaults_mirror_the_module_constants():
    from app.config import Settings

    fields = Settings.model_fields
    assert fields["LEARNING_MIN_GAMES"].default == ev.MIN_GAMES
    assert fields["LEARNING_MIN_DAYS_LIVE"].default == ev.MIN_DAYS_LIVE
    assert fields["LEARNING_COOLDOWN_DAYS"].default == ev.COOLDOWN_DAYS
    assert fields["LEARNING_AUTOPROMOTE"].default is True
    assert fields["LEARNING_PROPOSAL_DAYS"].default == 7 and fields["LEARNING_MAX_CHALLENGERS"].default == 3


def test_the_number_of_challengers_is_counted_from_the_registry(league):
    config = ev.EvaluationConfig(resamples=200)
    assert ev.count_active_challengers(league.session) == 1
    league.session.add(ModelVersion(name="elo_538", version="c2", role="challenger", params={"sigma": SIGMA}))
    league.session.add(ModelVersion(name="elo_538", version="c3", role="retired", params={"sigma": SIGMA}))
    league.session.commit()
    assert ev.count_active_challengers(league.session) == 2
    result = ev.evaluate_challenger(league.session, league.challenger, league.champion, NOW, config)
    assert result.k == 2
