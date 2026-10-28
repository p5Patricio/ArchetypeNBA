from datetime import datetime, timedelta, timezone
from decimal import Decimal
import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from app.models import (
    BetSide,
    BetStatus,
    Game,
    MarketType,
    ModelPrediction,
    ModelVersion,
    SimulatedBet,
    Sportsbook,
    StakingStrategy,
    Team,
)
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


def test_paper_api_empty_db_returns_200(client: TestClient):
    # Summary on empty db
    resp = client.get("/api/v1/paper/summary")
    assert resp.status_code == 200
    data = resp.json()
    assert "strategies" in data
    assert any(s["strategy"] == "flat" for s in data["strategies"])
    assert data["pinnacle_clv"]["games"] == 0
    assert data["pinnacle_clv"]["exclusions"]["total"] == 0
    assert data["brier"]["games_compared"] == 0

    # Bets on empty db
    resp = client.get("/api/v1/paper/bets")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0
    assert data["bets"] == []

    # Bankroll on empty db
    resp = client.get("/api/v1/paper/bankroll")
    assert resp.status_code == 200
    data = resp.json()
    assert "series" in data
    assert data["series"]["flat"] == []
    assert data["series"]["kelly_fractional"] == []


def test_paper_summary_with_bets(client: TestClient, world):
    game = add_game(world, "BOS", "LAC", start=TIPOFF)
    add_marker(world, game, at=CLOSING_AT)

    # Flat bet
    b_flat = place_bet(
        world, game, MarketType.h2h, BetSide.home, price="2.0000", stake="1.000",
        strategy=StakingStrategy.flat, placed_at=PLACED
    )
    b_flat.status = BetStatus.won
    b_flat.profit_units = Decimal("1.000")
    b_flat.settled_at = TIPOFF + timedelta(hours=3)
    b_flat.closing_price = Decimal("1.8000")
    world.add(b_flat)

    # Pinnacle closing quote
    add_quote(world, game, "pinnacle", MarketType.h2h, BetSide.home, -110, captured_at=CLOSING_AT)
    add_quote(world, game, "pinnacle", MarketType.h2h, BetSide.away, -110, captured_at=CLOSING_AT)
    world.commit()

    resp = client.get("/api/v1/paper/summary")
    assert resp.status_code == 200
    data = resp.json()

    flat_strat = next(s for s in data["strategies"] if s["strategy"] == "flat")
    assert flat_strat["bets"] == 1
    assert flat_strat["settled"] == 1
    assert flat_strat["pnl_units"] == 1.0
    assert flat_strat["bankroll"] == 101.0
    assert flat_strat["win_rate"] == 1.0

    pclv = data["pinnacle_clv"]
    assert pclv["games"] == 1
    assert pclv["mean_clv"] is not None


def test_paper_bets_list_filters_and_pagination(client: TestClient, world):
    game = add_game(world, "BOS", "LAC", start=TIPOFF)
    # 2 bets: 1 flat won, 1 kelly pending
    b1 = place_bet(
        world, game, MarketType.h2h, BetSide.home, price="1.9500", stake="1.000",
        strategy=StakingStrategy.flat, placed_at=PLACED
    )
    b1.status = BetStatus.won
    b1.profit_units = Decimal("0.950")
    b1.settled_at = TIPOFF + timedelta(hours=3)

    b2 = place_bet(
        world, game, MarketType.spreads, BetSide.away, line=3.5, price="1.9090", stake="2.000",
        strategy=StakingStrategy.kelly_fractional, placed_at=PLACED + timedelta(minutes=10)
    )
    world.add_all([b1, b2])
    world.commit()

    # Query all
    resp = client.get("/api/v1/paper/bets")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    assert len(data["bets"]) == 2
    # Newest first: b2 placed after b1
    assert data["bets"][0]["id"] == b2.id
    assert data["bets"][0]["game"]["home_team"] == "BOS"
    assert data["bets"][0]["game"]["away_team"] == "LAC"
    assert data["bets"][0]["strategy"] == "kelly_fractional"
    assert data["bets"][0]["line"] == 3.5

    # Filter by strategy
    resp_flat = client.get("/api/v1/paper/bets?strategy=flat")
    assert resp_flat.status_code == 200
    data_flat = resp_flat.json()
    assert data_flat["total"] == 1
    assert data_flat["bets"][0]["id"] == b1.id
    assert data_flat["bets"][0]["profit_units"] == 0.95

    # Filter by status
    resp_pending = client.get("/api/v1/paper/bets?status=pending")
    assert resp_pending.status_code == 200
    assert resp_pending.json()["total"] == 1
    assert resp_pending.json()["bets"][0]["id"] == b2.id

    # Limit max validation
    resp_invalid = client.get("/api/v1/paper/bets?limit=250")
    assert resp_invalid.status_code == 422


def test_paper_bankroll_series(client: TestClient, world):
    game1 = add_game(world, "BOS", "LAC", start=TIPOFF)
    game2 = add_game(world, "NYK", "LAL", start=TIPOFF + timedelta(days=1))

    # Two settled bets for flat
    b1 = place_bet(
        world, game1, MarketType.h2h, BetSide.home, price="2.0000", stake="1.000",
        strategy=StakingStrategy.flat, placed_at=PLACED
    )
    b1.status = BetStatus.won
    b1.profit_units = Decimal("1.000")
    b1.settled_at = TIPOFF + timedelta(hours=3)

    b2 = place_bet(
        world, game2, MarketType.h2h, BetSide.home, price="1.9000", stake="1.000",
        strategy=StakingStrategy.flat, placed_at=PLACED + timedelta(days=1)
    )
    b2.status = BetStatus.lost
    b2.profit_units = Decimal("-1.000")
    b2.settled_at = TIPOFF + timedelta(days=1, hours=3)

    world.add_all([b1, b2])
    world.commit()

    resp = client.get("/api/v1/paper/bankroll")
    assert resp.status_code == 200
    series = resp.json()["series"]

    assert len(series["flat"]) == 2
    assert series["flat"][0]["cumulative_profit_units"] == 1.0
    assert series["flat"][0]["bankroll"] == 101.0
    assert series["flat"][1]["cumulative_profit_units"] == 0.0
    assert series["flat"][1]["bankroll"] == 100.0

    # kelly has no settled bets
    assert series["kelly_fractional"] == []
