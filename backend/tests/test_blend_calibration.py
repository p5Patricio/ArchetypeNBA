from datetime import timedelta
from decimal import Decimal

import numpy as np
import pytest
from sqlmodel import select

from app.analytics.props_engine import devig_two_way
from app.models import BetSide, MarketType, ModelPrediction, ModelVersion
from app.services import blend_calibration
from app.services.prediction_recorder import PredictionRecorder  # noqa: F401  (imports the models consistently)
from tests.test_prediction_recorder import NOW, World, american, world  # noqa: F401  (world is a fixture)

PAST = NOW - timedelta(days=2)


def _final(world, home_score, away_score, event):
    game = world.game(hours=-48.0, status="final", event=event)
    game.home_score, game.away_score = home_score, away_score
    world.session.add(game)
    world.session.commit()
    return game


def _predict(world, game, prob, predicted_at, model=None):
    model = model or world.session.exec(select(ModelVersion)).first()
    row = ModelPrediction(
        model_version_id=model.id,
        game_id=game.id,
        market=MarketType.h2h,
        side=BetSide.home,
        model_prob=Decimal(str(prob)),
        predicted_at=predicted_at,
    )
    world.session.add(row)
    world.session.commit()
    return row


def test_calibration_uses_the_pinnacle_pair_as_of_the_prediction_not_the_close(world):
    game = _final(world, 110, 100, "g1")
    predicted = game.commence_time - timedelta(hours=10)
    world.h2h(game, "pinnacle", -170, 145, captured=predicted - timedelta(minutes=30))
    world.h2h(game, "pinnacle", -400, 320, captured=predicted + timedelta(hours=5))  # later move: not known then
    _predict(world, game, 0.66, predicted)

    data = blend_calibration.load_calibration_data(world.session, world.session.exec(select(ModelVersion)).first().id)

    assert data.n == 1
    assert data.p_models == [pytest.approx(0.66)]
    assert data.p_fairs == [pytest.approx(devig_two_way(american(-170), american(145))[0])]
    assert data.outcomes == [1.0]


def test_calibration_skips_games_that_cannot_be_compared_fairly(world):
    model = world.session.exec(select(ModelVersion)).first()

    no_pair_then = _final(world, 100, 90, "g-late-quotes")  # Pinnacle appears only after the prediction
    predicted = no_pair_then.commence_time - timedelta(hours=10)
    world.h2h(no_pair_then, "pinnacle", -150, 130, captured=predicted + timedelta(hours=1))
    _predict(world, no_pair_then, 0.6, predicted)

    soft_only = _final(world, 100, 90, "g-soft-book")  # only a soft book quoted
    world.h2h(soft_only, "draftkings", -150, 130, captured=predicted - timedelta(hours=1))
    _predict(world, soft_only, 0.6, predicted)

    after_tip = _final(world, 100, 90, "g-after-tip")  # recorded at or after tip-off
    world.h2h(after_tip, "pinnacle", -150, 130, captured=after_tip.commence_time - timedelta(hours=2))
    _predict(world, after_tip, 0.6, after_tip.commence_time)

    no_time = _final(world, 100, 90, "g-no-time")  # predicted_at unknown
    world.h2h(no_time, "pinnacle", -150, 130, captured=predicted - timedelta(hours=1))
    _predict(world, no_time, 0.6, None)

    not_final = world.game(hours=-48.0, status="scheduled", event="g-not-final")
    world.h2h(not_final, "pinnacle", -150, 130, captured=predicted - timedelta(hours=1))
    _predict(world, not_final, 0.6, not_final.commence_time - timedelta(hours=10))

    other_model = ModelVersion(name="other", version="1", params={}, role="challenger")
    world.session.add(other_model)
    world.session.commit()
    challenger_game = _final(world, 100, 90, "g-challenger")
    world.h2h(challenger_game, "pinnacle", -150, 130, captured=predicted - timedelta(hours=1))
    _predict(world, challenger_game, 0.6, predicted, model=other_model)

    assert blend_calibration.load_calibration_data(world.session, model.id).n == 0
    assert blend_calibration.load_calibration_data(world.session, other_model.id).n == 1


def test_compute_blend_weight_is_zero_under_the_minimum_and_reports_the_counts(world):
    game = _final(world, 90, 100, "g-away-win")
    predicted = game.commence_time - timedelta(hours=10)
    world.h2h(game, "pinnacle", -110, -110, captured=predicted - timedelta(hours=1))
    _predict(world, game, 0.7, predicted)

    blend = blend_calibration.compute_blend_weight(world.session)

    assert blend.n == 1 and blend.w_used == 0.0
    assert "n=1 games" in blend.report_line() and "6pp" in blend.report_line()


def _american_from_prob(p):
    return round(-100.0 * p / (1.0 - p)) if p >= 0.5 else round(100.0 * (1.0 - p) / p)


def test_the_weight_is_positive_end_to_end_when_the_champion_knows_more_than_pinnacle(world):
    rng = np.random.default_rng(11)
    n = 300
    shared = rng.normal(0.0, 0.5, n)
    private = rng.normal(0.0, 0.5, n)
    p_true = 1.0 / (1.0 + np.exp(-(shared + private)))
    p_market = 1.0 / (1.0 + np.exp(-shared))
    p_model = 1.0 / (1.0 + np.exp(-(shared + private + rng.normal(0.0, 0.3, n))))
    home_won = rng.random(n) < p_true
    for i in range(n):
        game = _final(world, 110 if home_won[i] else 100, 100 if home_won[i] else 110, f"e2e-{i}")
        predicted = game.commence_time - timedelta(hours=8)
        pm = float(p_market[i])
        world.h2h(game, "pinnacle", _american_from_prob(pm), _american_from_prob(1.0 - pm), captured=predicted - timedelta(minutes=20))
        _predict(world, game, round(float(p_model[i]), 5), predicted)

    blend = blend_calibration.compute_blend_weight(world.session)

    assert blend.n == n
    assert blend.w_hat >= 0.2
    assert 0.0 < blend.w_used < blend.w_hat


def _load_blend_cli():
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "scripts" / "blend_weight.py"
    spec = importlib.util.spec_from_file_location("blend_weight_cli", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_blend_weight_cli_prints_the_weight_and_the_disagreement_distribution(world, capsys):
    from contextlib import nullcontext

    for i, (p_model, odds) in enumerate(((0.72, (-170, 145)), (0.52, (-110, -110)))):
        game = _final(world, 110, 100, f"cli-{i}")
        predicted = game.commence_time - timedelta(hours=6)
        world.h2h(game, "pinnacle", *odds, captured=predicted - timedelta(minutes=5))
        _predict(world, game, p_model, predicted)

    assert _load_blend_cli().main(session_factory=lambda: nullcontext(world.session)) == 0

    out = capsys.readouterr().out
    assert "calibrated blend weight: w_used=0.000" in out and "n=2 games" in out
    assert "|p_model - p_fair|" in out and "within the 6pp cap: 1 of 2" in out
    assert "mean home probability" in out
