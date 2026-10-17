"""Behavior tests for the Phase 4 quant paper-trading schema (SQLite)."""
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import (
    BetSide,
    BetStatus,
    Game,
    MarketType,
    ModelPrediction,
    ModelVersion,
    OddsHistory,
    Season,
    SimulatedBet,
    Sportsbook,
    StakingStrategy,
    Team,
)

TIP_OFF = datetime(2026, 10, 25, 23, 30, tzinfo=timezone.utc)


def _team(abbreviation: str) -> Team:
    return Team(
        abbreviation=abbreviation,
        full_name=f"{abbreviation} Team",
        city=abbreviation,
        conference="East",
        division="Atlantic",
    )


@pytest.fixture
def world(db_session):
    """Season, two teams, one game and one sharp sportsbook."""
    season = Season(season_label="2026-27")
    home, away = _team("BOS"), _team("NYK")
    book = Sportsbook(key="pinnacle", name="Pinnacle", region="eu", is_sharp=True)
    db_session.add_all([season, home, away, book])
    db_session.commit()

    game = Game(
        nba_game_id="0022600001",
        provider_event_id="evt-1",
        season_id=season.id,
        home_team_id=home.id,
        away_team_id=away.id,
        commence_time=TIP_OFF,
    )
    db_session.add(game)
    db_session.commit()
    return {"season": season, "home": home, "away": away, "book": book, "game": game}


def _odds(world, price_american: int, **overrides) -> OddsHistory:
    fields = dict(
        game_id=world["game"].id,
        sportsbook_id=world["book"].id,
        market=MarketType.h2h,
        side=BetSide.home,
        price_american=price_american,
        book_last_update=TIP_OFF,
    )
    fields.update(overrides)
    return OddsHistory(**fields)


def _prediction(db_session, world, model_prob: str) -> ModelPrediction:
    version = ModelVersion(name="elo", version="1")
    db_session.add(version)
    db_session.commit()
    prediction = ModelPrediction(
        model_version_id=version.id,
        game_id=world["game"].id,
        market=MarketType.h2h,
        side=BetSide.home,
        model_prob=Decimal(model_prob),
    )
    db_session.add(prediction)
    db_session.commit()
    return prediction


def test_game_defaults_and_odds_round_trip(db_session, world):
    odds = _odds(world, 150)
    db_session.add(odds)
    db_session.commit()
    db_session.refresh(odds)

    assert world["game"].status == "scheduled"
    assert world["book"].is_sharp is True
    assert odds.market == MarketType.h2h
    assert odds.player_id is None
    assert odds.captured_at is not None


@pytest.mark.parametrize(
    "price_american, expected",
    [(150, 2.5), (-110, 1.9091), (100, 2.0), (-200, 1.5)],
)
def test_price_decimal_is_derived_from_american_price(db_session, world, price_american, expected):
    odds = _odds(world, price_american)
    db_session.add(odds)
    db_session.commit()
    db_session.refresh(odds)

    assert float(odds.price_decimal) == pytest.approx(expected, abs=1e-4)


def test_fair_decimal_is_inverse_of_model_prob(db_session, world):
    prediction = _prediction(db_session, world, "0.40000")
    db_session.refresh(prediction)

    assert float(prediction.fair_decimal) == pytest.approx(2.5, abs=1e-4)


def _bet(world, odds, prediction, **overrides) -> SimulatedBet:
    fields = dict(
        prediction_id=prediction.id,
        odds_taken_id=odds.id,
        price_taken=Decimal("2.5000"),
        ev_per_unit=Decimal("0.10000"),
        strategy=StakingStrategy.flat,
        stake_units=Decimal("1.000"),
        bankroll_before=Decimal("100.000"),
    )
    fields.update(overrides)
    return SimulatedBet(**fields)


def test_clv_is_computed_only_when_closing_price_is_set(db_session, world):
    odds = _odds(world, 150)
    db_session.add(odds)
    db_session.commit()
    prediction = _prediction(db_session, world, "0.45000")

    open_bet = _bet(world, odds, prediction)
    closed_bet = _bet(
        world, odds, prediction, closing_price=Decimal("2.0000"), closing_odds_id=odds.id
    )
    db_session.add_all([open_bet, closed_bet])
    db_session.commit()
    db_session.refresh(open_bet)
    db_session.refresh(closed_bet)

    assert open_bet.status == BetStatus.pending
    assert open_bet.clv_pct is None
    assert float(closed_bet.clv_pct) == pytest.approx(0.25, abs=1e-5)


def test_game_rejects_same_home_and_away_team(db_session, world):
    game = Game(
        nba_game_id="0022600002",
        season_id=world["season"].id,
        home_team_id=world["home"].id,
        away_team_id=world["home"].id,
        commence_time=TIP_OFF,
    )
    db_session.add(game)
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_odds_rejects_price_between_minus_100_and_plus_100(db_session, world):
    db_session.add(_odds(world, 50))
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_settled_bet_requires_settled_at(db_session, world):
    odds = _odds(world, 150)
    db_session.add(odds)
    db_session.commit()
    prediction = _prediction(db_session, world, "0.45000")

    db_session.add(_bet(world, odds, prediction, status=BetStatus.won))
    with pytest.raises(IntegrityError):
        db_session.commit()
