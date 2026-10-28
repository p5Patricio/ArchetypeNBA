from datetime import datetime, timedelta, timezone
from decimal import Decimal
import math
import pytest

from app.models import (
    BetSide,
    BetStatus,
    MarketType,
    ModelPrediction,
    SimulatedBet,
    StakingStrategy,
)
from app.services.clv_report import build_pinnacle_clv_report
from tests.test_settlement import (  # noqa: F401 (world fixture)
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
    world,
)


def test_pinnacle_clv_report_empty_db(world):
    report = build_pinnacle_clv_report(world, NOW)
    assert report.total_bets == 0
    assert report.games_count == 0
    assert report.stats.n_games == 0
    assert report.stats.mean_clv is None
    assert report.same_book_avg_clv is None
    assert report.exclusions.total == 0
    assert report.game_rows == []


def test_pinnacle_clv_h2h_bet(world):
    game = add_game(world, "BOS", "LAC", start=TIPOFF)
    add_marker(world, game, at=CLOSING_AT)

    # Bet placed at soft book: price 2.0000
    bet = place_bet(world, game, MarketType.h2h, BetSide.home, price="2.0000", placed_at=PLACED)
    bet.closing_price = Decimal("1.9048")  # same-book closing price (generates clv_pct ~ +5%)
    world.add(bet)
    world.commit()

    # Pinnacle closing quote: BOS -200 (1.500), LAC +170 (2.700)
    add_quote(world, game, "pinnacle", MarketType.h2h, BetSide.home, -200, captured_at=CLOSING_AT)
    add_quote(world, game, "pinnacle", MarketType.h2h, BetSide.away, 170, captured_at=CLOSING_AT)

    report = build_pinnacle_clv_report(world, NOW)
    assert report.total_bets == 1
    assert report.games_count == 1
    assert report.stats.n_games == 1
    assert report.exclusions.total == 0

    # Fair prob for BOS = (1/1.5) / (1/1.5 + 1/2.7) = 0.642857
    fair_prob = (1.0 / 1.5) / (1.0 / 1.5 + 1.0 / 2.7)
    fair_price = 1.0 / fair_prob
    expected_log_clv = math.log(2.0 / fair_price)

    assert report.stats.mean_clv == pytest.approx(expected_log_clv)
    assert report.same_book_avg_clv == pytest.approx(2.0 / 1.9048 - 1.0, abs=1e-4)
    assert len(report.game_rows) == 1
    assert report.game_rows[0].fair_closing_price == pytest.approx(fair_price)
    assert report.game_rows[0].log_clv == pytest.approx(expected_log_clv)


def test_pinnacle_clv_spreads_and_duplicate_bets_clustered(world):
    game = add_game(world, "BOS", "LAC", start=TIPOFF)
    add_marker(world, game, at=CLOSING_AT)

    # Flat bet and Kelly bet on same game and spread line -3.5
    b1 = place_bet(
        world, game, MarketType.spreads, BetSide.home, line=-3.5, price="1.9500", strategy=StakingStrategy.flat, placed_at=PLACED
    )
    b2 = place_bet(
        world, game, MarketType.spreads, BetSide.home, line=-3.5, price="2.0000", strategy=StakingStrategy.kelly_fractional, placed_at=PLACED
    )

    # Pinnacle closing spread: BOS -3.5 at -110 (1.909), LAC +3.5 at -110 (1.909)
    add_quote(world, game, "pinnacle", MarketType.spreads, BetSide.home, -110, line=-3.5, captured_at=CLOSING_AT)
    add_quote(world, game, "pinnacle", MarketType.spreads, BetSide.away, -110, line=3.5, captured_at=CLOSING_AT)

    report = build_pinnacle_clv_report(world, NOW)
    assert report.total_bets == 2
    assert report.games_count == 1  # Clustered into 1 independent game!
    assert report.exclusions.total == 0

    # Devigged fair prob for even quotes (-110 / -110) = 0.5, fair price = 2.0
    fair_price = 2.0
    clv1 = math.log(1.95 / fair_price)
    clv2 = math.log(2.00 / fair_price)
    expected_game_clv = (clv1 + clv2) / 2.0

    assert report.stats.mean_clv == pytest.approx(expected_game_clv)
    assert len(report.game_rows) == 1
    assert report.game_rows[0].bets_count == 2
    assert report.game_rows[0].mean_price_taken == pytest.approx(1.975)


def test_pinnacle_clv_exclusions(world):
    # Game 1: no closing marker
    g1 = add_game(world, "BOS", "LAC", start=TIPOFF)
    place_bet(world, g1, MarketType.h2h, BetSide.home, placed_at=PLACED)

    # Game 2: closing before bet placed
    g2 = add_game(world, "NYK", "LAL", start=TIPOFF)
    add_marker(world, g2, at=CLOSING_AT)
    place_bet(world, g2, MarketType.h2h, BetSide.home, placed_at=CLOSING_AT + timedelta(minutes=5))

    # Game 3: no Pinnacle quote
    g3 = add_game(world, "LAC", "NYK", start=TIPOFF)
    add_marker(world, g3, at=CLOSING_AT)
    place_bet(world, g3, MarketType.h2h, BetSide.home, book="fanduel", placed_at=PLACED)

    # Game 4: spread line moved at Pinnacle (-3.5 bet, but Pinnacle closed at -4.5)
    g4 = add_game(world, "LAL", "BOS", start=TIPOFF)
    add_marker(world, g4, at=CLOSING_AT)
    place_bet(world, g4, MarketType.spreads, BetSide.home, line=-3.5, placed_at=PLACED)
    add_quote(world, g4, "pinnacle", MarketType.spreads, BetSide.home, -110, line=-4.5, captured_at=CLOSING_AT)
    add_quote(world, g4, "pinnacle", MarketType.spreads, BetSide.away, -110, line=4.5, captured_at=CLOSING_AT)

    # Game 5: one-sided quote at Pinnacle
    g5 = add_game(world, "BOS", "NYK", start=TIPOFF)
    add_marker(world, g5, at=CLOSING_AT)
    place_bet(world, g5, MarketType.h2h, BetSide.home, placed_at=PLACED)
    add_quote(world, g5, "pinnacle", MarketType.h2h, BetSide.home, -150, captured_at=CLOSING_AT)

    report = build_pinnacle_clv_report(world, NOW)
    assert report.total_bets == 5
    assert report.games_count == 0
    assert report.exclusions.no_closing_marker == 1
    assert report.exclusions.closing_before_bet == 1
    assert report.exclusions.no_pinnacle_quote == 1
    assert report.exclusions.line_moved == 1
    assert report.exclusions.one_sided_quote == 1
    assert report.exclusions.total == 5
