import importlib.util
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from app.models import BetSide, BetStatus, MarketType, StakingStrategy
from app.services.paper_report import build_report, format_report
from tests.test_settlement import (  # noqa: F401  (world is a fixture)
    CLOSING_AT,
    NOW,
    PLACED,
    TIPOFF,
    add_game,
    add_marker,
    add_prediction,
    add_quote,
    final_game,
    place_bet,
    reload,
    world,
)


def test_the_report_runs_on_empty_tables_and_says_so(world):
    report = build_report(world, NOW)
    text = format_report(report)

    assert [s.strategy for s in report.strategies] == ["flat", "kelly_fractional"]
    assert all(s.bets == 0 and s.win_rate is None and s.roi is None and s.avg_clv is None for s in report.strategies)
    assert report.clv.coverage is None and report.skill.brier_model is None
    assert "No paper bets recorded yet." in text
    assert "No bets on tipped-off games yet." in text
    assert "Cannot be computed yet" in text
    assert "flat" in text and "100.00u" in text


def test_performance_per_strategy_matches_the_paper_performance_view(world):
    game = final_game(world, 110, 100)
    won = place_bet(world, game, MarketType.h2h, BetSide.home, price="2.0000", stake="1.000")
    lost = place_bet(world, game, MarketType.h2h, BetSide.away, price="1.9000", stake="1.000")
    push = place_bet(world, game, MarketType.spreads, BetSide.home, line=-10, price="1.9090", stake="1.000")
    place_bet(world, add_game(world, "NYK", "LAL"), MarketType.h2h, BetSide.home)  # pending, not settled
    kelly = place_bet(
        world, game, MarketType.h2h, BetSide.home, price="2.0000", stake="2.000", strategy=StakingStrategy.kelly_fractional
    )
    from app.services.settlement import settle_bets

    settle_bets(world, NOW)
    # CLV on two flat bets: +11.11% and -5.00%
    won.closing_price, lost.closing_price = Decimal("1.8000"), Decimal("2.0000")
    world.add_all([won, lost])
    world.commit()

    report = build_report(world, NOW)
    flat, kelly_perf = report.strategies

    assert flat.strategy == "flat" and (flat.bets, flat.settled, flat.pending) == (4, 3, 1)
    assert flat.win_rate == pytest.approx(0.5)  # 1 won / (1 won + 1 lost); the push is outside the rate
    assert flat.pnl_units == pytest.approx(1.0 - 1.0 + 0.0)
    assert flat.roi == pytest.approx(0.0)
    assert flat.clv_bets == 2
    assert flat.avg_clv == pytest.approx((2.0 / 1.8 - 1 + 1.9 / 2.0 - 1) / 2, abs=1e-4)
    assert flat.beat_close_rate == pytest.approx(0.5)
    assert flat.bankroll == pytest.approx(100.0)
    assert (kelly_perf.bets, kelly_perf.settled, kelly_perf.win_rate) == (1, 1, 1.0)
    assert kelly_perf.pnl_units == pytest.approx(2.0) and kelly_perf.roi == pytest.approx(1.0)
    assert kelly_perf.avg_clv is None and kelly_perf.bankroll == pytest.approx(102.0)


def test_clv_coverage_counts_bets_and_missed_closings(world):
    covered = add_game(world, "BOS", "LAC", start=TIPOFF)
    moved = add_game(world, "NYK", "LAL", start=TIPOFF)
    missed = add_game(world, "LAC", "NYK", start=TIPOFF)
    future = add_game(world, "LAL", "BOS", start=NOW + timedelta(days=1))
    postponed = add_game(world, "BOS", "NYK", start=TIPOFF, status="postponed")
    add_marker(world, covered)
    add_marker(world, moved)

    with_clv = place_bet(world, covered, MarketType.h2h, BetSide.home)
    with_clv.closing_price = Decimal("1.9000")
    world.add(with_clv)
    line_moved = place_bet(world, moved, MarketType.spreads, BetSide.home, line=-3.5)
    line_moved.closing_line = Decimal("-4.5")
    world.add(line_moved)
    place_bet(world, missed, MarketType.h2h, BetSide.home)
    place_bet(world, future, MarketType.h2h, BetSide.home)
    world.commit()

    clv = build_report(world, NOW).clv

    assert (clv.bets_tipped_off, clv.bets_with_clv, clv.bets_line_moved) == (3, 1, 1)
    assert clv.coverage == pytest.approx(1 / 3)
    assert (clv.games_tipped_off, clv.closings_missed) == (3, 1)  # the future and postponed games do not count
    assert "1 of 3 bets" in format_report(build_report(world, NOW))


def closed_game(world, home, away, home_score, away_score, model_p, pinnacle=(-110, -110), marker=True):
    game = final_game(world, home_score, away_score, home=home, away=away)
    if model_p is not None:
        add_prediction(world, game, MarketType.h2h, BetSide.home, prob=f"{model_p:.5f}")
        add_prediction(world, game, MarketType.h2h, BetSide.away, prob=f"{1 - model_p:.5f}")
    if pinnacle is not None:
        add_quote(world, game, "pinnacle", MarketType.h2h, BetSide.home, pinnacle[0], captured_at=CLOSING_AT)
        add_quote(world, game, "pinnacle", MarketType.h2h, BetSide.away, pinnacle[1], captured_at=CLOSING_AT)
    if marker:
        add_marker(world, game)
    return game


def test_model_skill_compares_brier_scores_on_the_same_games_only(world):
    # A: home wins, model 0.70, close -200/+170 -> fair home 0.642857
    a = closed_game(world, "BOS", "LAC", 110, 100, 0.70, pinnacle=(-200, 170))
    # a stale, earlier quote and a post-tip-off one must not be used
    add_quote(world, a, "pinnacle", MarketType.h2h, BetSide.home, -1000, captured_at=CLOSING_AT - timedelta(hours=3))
    add_quote(world, a, "pinnacle", MarketType.h2h, BetSide.home, 500, captured_at=TIPOFF + timedelta(minutes=10))
    # B: away wins, model 0.40, close -110/-110 -> fair home 0.5
    closed_game(world, "NYK", "LAL", 95, 101, 0.40)
    # excluded: no closing marker / no model prediction / no pinnacle quote / not final
    closed_game(world, "LAC", "NYK", 100, 90, 0.90, marker=False)
    closed_game(world, "LAL", "BOS", 100, 90, None)
    closed_game(world, "BOS", "NYK", 100, 90, 0.90, pinnacle=None)
    add_game(world, "NYK", "BOS")

    skill = build_report(world, NOW).skill

    assert skill.sharp_book == "pinnacle"
    assert (skill.final_games, skill.final_games_with_closing, skill.games_compared) == (5, 4, 2)
    fair_a = (1 / 1.5) / (1 / 1.5 + 1 / 2.7)
    assert skill.brier_model == pytest.approx(((0.70 - 1) ** 2 + 0.40**2) / 2, abs=1e-4)
    assert skill.brier_market == pytest.approx(((fair_a - 1) ** 2 + 0.5**2) / 2, abs=1e-4)
    assert skill.difference == pytest.approx(skill.brier_model - skill.brier_market)
    text = format_report(build_report(world, NOW))
    assert "compared 2" in text and "market better" not in text and "model better" in text


def test_model_skill_with_final_games_but_no_closing_data_is_reported_as_not_computable(world):
    closed_game(world, "BOS", "LAC", 110, 100, 0.7, marker=False)

    report = build_report(world, NOW)

    assert report.skill.final_games == 1 and report.skill.games_compared == 0 and report.skill.difference is None
    assert "Cannot be computed yet" in format_report(report)


def test_the_market_wins_when_the_model_is_worse(world):
    closed_game(world, "BOS", "LAC", 110, 100, 0.30, pinnacle=(-200, 170))  # model says 30%, market 64%, home wins

    skill = build_report(world, NOW).skill

    assert skill.difference > 0
    assert "market better" in format_report(build_report(world, NOW))


# --- CLI -------------------------------------------------------------------------------------------------------------

def _load_cli():
    path = Path(__file__).resolve().parents[1] / "scripts" / "paper_report.py"
    spec = importlib.util.spec_from_file_location("paper_report_cli", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cli_prints_the_report(world, capsys):
    cli = _load_cli()

    assert cli.main(session_factory=lambda: nullcontext(world)) == 0

    out = capsys.readouterr().out
    assert "Paper trading report" in out and "Strategy performance" in out and "Bankroll" in out
