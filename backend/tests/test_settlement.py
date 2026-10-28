from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlmodel import select

from app.models import (
    CAPTURE_CLOSING,
    CAPTURE_OPENING,
    BetSide,
    BetStatus,
    Game,
    MarketType,
    ModelPrediction,
    ModelVersion,
    OddsHistory,
    OddsSnapshotCapture,
    Season,
    SimulatedBet,
    Sportsbook,
    StakingStrategy,
    Team,
)
from app.services.elo_service import MODEL_NAME, MODEL_VERSION
from app.services.settlement import fill_clv, grade_bet, profit_for, settle_bets

TIPOFF = datetime(2026, 10, 21, 23, 30, tzinfo=timezone.utc)
NOW = TIPOFF + timedelta(hours=4)
PLACED = TIPOFF - timedelta(hours=5)
CLOSING_AT = TIPOFF - timedelta(minutes=20)


# --- world builders (shared with test_paper_report) -------------------------------------------------------------

@pytest.fixture
def world(db_session):
    season = Season(season_label="2026-27", start_date=date(2026, 10, 1), end_date=date(2027, 6, 30), is_active=True)
    db_session.add(season)
    for abbr in ("BOS", "LAC", "NYK", "LAL"):
        db_session.add(Team(abbreviation=abbr, full_name=abbr, city="", conference="", division=""))
    db_session.add_all(
        [
            Sportsbook(key="pinnacle", name="Pinnacle", region="eu", is_sharp=True),
            Sportsbook(key="fanduel", name="FanDuel", region="us", is_sharp=False),
        ]
    )
    db_session.add(ModelVersion(name=MODEL_NAME, version=MODEL_VERSION, params={"sigma": 14.0}))
    db_session.commit()
    db_session.season = season
    db_session.teams = {t.abbreviation: t for t in db_session.exec(select(Team)).all()}
    db_session.books = {b.key: b for b in db_session.exec(select(Sportsbook)).all()}
    db_session.model_version = db_session.exec(select(ModelVersion)).first()
    return db_session


def add_game(s, home="BOS", away="LAC", start=TIPOFF, status="scheduled", scores=None):
    game = Game(
        provider_event_id=f"{home}-{away}-{start.isoformat()}",
        season_id=s.season.id,
        home_team_id=s.teams[home].id,
        away_team_id=s.teams[away].id,
        commence_time=start,
        status=status,
        home_score=scores[0] if scores else None,
        away_score=scores[1] if scores else None,
    )
    s.add(game)
    s.commit()
    return game


def final_game(s, home_score, away_score, **kwargs):
    return add_game(s, status="final", scores=(home_score, away_score), **kwargs)


def add_quote(s, game, book, market, side, american, line=None, captured_at=PLACED - timedelta(hours=1), updated_at=None):
    row = OddsHistory(
        game_id=game.id,
        sportsbook_id=s.books[book].id,
        market=market,
        side=side,
        line=None if line is None else Decimal(str(line)),
        price_american=american,
        book_last_update=updated_at or captured_at,
        captured_at=captured_at,
    )
    s.add(row)
    s.commit()
    return row


def add_prediction(s, game, market, side, line=None, prob="0.55000"):
    prediction = ModelPrediction(
        model_version_id=s.model_version.id,
        game_id=game.id,
        market=market,
        side=side,
        line=None if line is None else Decimal(str(line)),
        model_prob=Decimal(prob),
    )
    s.add(prediction)
    s.commit()
    return prediction


def place_bet(
    s, game, market, side, *, line=None, american=-110, price="1.9090", stake="1.000",
    strategy=StakingStrategy.flat, book="pinnacle", placed_at=PLACED, quote_at=None, status=BetStatus.pending,
):
    quote = add_quote(s, game, book, market, side, american, line, captured_at=quote_at or placed_at - timedelta(minutes=5))
    prediction = s.exec(
        select(ModelPrediction).where(
            ModelPrediction.game_id == game.id,
            ModelPrediction.market == market,
            ModelPrediction.side == side,
            ModelPrediction.line == (None if line is None else Decimal(str(line))),
        )
    ).first() or add_prediction(s, game, market, side, line)
    bet = SimulatedBet(
        prediction_id=prediction.id,
        odds_taken_id=quote.id,
        price_taken=Decimal(price),
        line_taken=None if line is None else Decimal(str(line)),
        ev_per_unit=Decimal("0.03000"),
        strategy=strategy,
        stake_units=Decimal(stake),
        bankroll_before=Decimal("100.000"),
        placed_at=placed_at,
        status=status,
    )
    s.add(bet)
    s.commit()
    return bet


def add_marker(s, game, kind=CAPTURE_CLOSING, at=CLOSING_AT):
    s.add(OddsSnapshotCapture(game_id=game.id, kind=kind, captured_at=at))
    s.commit()


def reload(s, row):
    s.refresh(row)
    return row


# --- grading -------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize(
    "market, side, line, home, away, expected",
    [
        ("h2h", "home", None, 110, 100, BetStatus.won),
        ("h2h", "home", None, 100, 110, BetStatus.lost),
        ("h2h", "away", None, 100, 110, BetStatus.won),
        ("h2h", "away", None, 110, 100, BetStatus.lost),
        # home spread -3.5 (half line)
        ("spreads", "home", Decimal("-3.5"), 110, 100, BetStatus.won),
        ("spreads", "home", Decimal("-3.5"), 103, 100, BetStatus.lost),
        # home spread -3 (integer line)
        ("spreads", "home", Decimal("-3"), 110, 100, BetStatus.won),
        ("spreads", "home", Decimal("-3"), 103, 100, BetStatus.push),
        ("spreads", "home", Decimal("-3"), 102, 100, BetStatus.lost),
        # home underdog +2.5
        ("spreads", "home", Decimal("2.5"), 98, 100, BetStatus.won),
        ("spreads", "home", Decimal("2.5"), 95, 100, BetStatus.lost),
        # away spread +4.5 (line_taken is the away line)
        ("spreads", "away", Decimal("4.5"), 103, 100, BetStatus.won),
        ("spreads", "away", Decimal("4.5"), 110, 100, BetStatus.lost),
        ("spreads", "away", Decimal("4.5"), 90, 100, BetStatus.won),
        # away spread +3 (integer)
        ("spreads", "away", Decimal("3"), 103, 100, BetStatus.push),
        ("spreads", "away", Decimal("3"), 104, 100, BetStatus.lost),
        ("spreads", "away", Decimal("3"), 102, 100, BetStatus.won),
        # away favourite -6.5
        ("spreads", "away", Decimal("-6.5"), 90, 100, BetStatus.won),
        ("spreads", "away", Decimal("-6.5"), 95, 100, BetStatus.lost),
    ],
)
def test_grade_bet(market, side, line, home, away, expected):
    assert grade_bet(market, side, line, home, away) == expected


def test_grade_bet_refuses_markets_it_does_not_settle():
    assert grade_bet("totals", "over", Decimal("220.5"), 110, 100) is None
    assert grade_bet("spreads", "home", None, 110, 100) is None
    assert grade_bet("player_points", "over", Decimal("25.5"), 110, 100) is None


def test_profit_for():
    assert profit_for(BetStatus.won, Decimal("2.500"), Decimal("2.1000")) == Decimal("2.750")
    assert profit_for(BetStatus.won, Decimal("1.000"), Decimal("1.9090")) == Decimal("0.909")
    assert profit_for(BetStatus.lost, Decimal("2.500"), Decimal("2.1000")) == Decimal("-2.500")
    assert profit_for(BetStatus.push, Decimal("2.500"), Decimal("2.1000")) == Decimal("0.000")


# --- settle_bets -----------------------------------------------------------------------------------------------------

def test_settle_bets_updates_status_profit_and_timestamp(world):
    game = final_game(world, 110, 100)
    won = place_bet(world, game, MarketType.h2h, BetSide.home, price="2.1000", stake="2.500")
    lost = place_bet(world, game, MarketType.h2h, BetSide.away, price="1.9090", stake="1.000")
    pushed = place_bet(world, game, MarketType.spreads, BetSide.home, line=-10, price="1.9090", stake="3.000")
    spread_win = place_bet(world, game, MarketType.spreads, BetSide.away, line=10.5, price="1.9500", stake="1.000")

    summary = settle_bets(world, NOW)

    assert dict(summary.settled) == {"won": 2, "lost": 1, "push": 1}
    won, lost, pushed, spread_win = (reload(world, b) for b in (won, lost, pushed, spread_win))
    assert (won.status, won.profit_units) == (BetStatus.won, Decimal("2.750"))
    assert (lost.status, lost.profit_units) == (BetStatus.lost, Decimal("-1.000"))
    assert (pushed.status, pushed.profit_units) == (BetStatus.push, Decimal("0.000"))
    assert (spread_win.status, spread_win.profit_units) == (BetStatus.won, Decimal("0.950"))
    assert {b.settled_at.replace(tzinfo=None) for b in (won, lost, pushed, spread_win)} == {NOW.replace(tzinfo=None)}
    assert summary.profit_units == Decimal("2.750") - 1 + 0 + Decimal("0.950")


def test_settle_bets_is_idempotent_and_never_resettles(world):
    game = final_game(world, 110, 100)
    bet = place_bet(world, game, MarketType.h2h, BetSide.home)
    settle_bets(world, NOW)
    first = reload(world, bet)
    first_settled_at, first_profit = first.settled_at, first.profit_units

    # a later score correction must not reopen a settled bet
    game.home_score, game.away_score = 90, 100
    world.add(game)
    world.commit()
    second = settle_bets(world, NOW + timedelta(hours=1))

    assert second.total_settled == 0
    bet = reload(world, bet)
    assert (bet.status, bet.profit_units, bet.settled_at) == (BetStatus.won, first_profit, first_settled_at)


def test_games_that_are_not_final_leave_their_bets_pending(world):
    scheduled = add_game(world, "BOS", "LAC", start=TIPOFF)
    postponed = add_game(world, "NYK", "LAL", status="postponed")
    no_scores = add_game(world, "LAC", "NYK", status="final")
    pending = [
        place_bet(world, scheduled, MarketType.h2h, BetSide.home),
        place_bet(world, postponed, MarketType.h2h, BetSide.home),
        place_bet(world, no_scores, MarketType.h2h, BetSide.home),
    ]

    summary = settle_bets(world, NOW)

    assert summary.total_settled == 0 and summary.skipped_no_score == 1
    assert [reload(world, b).status for b in pending] == [BetStatus.pending] * 3
    assert all(reload(world, b).settled_at is None and reload(world, b).profit_units is None for b in pending)


def test_unsupported_markets_stay_pending(world):
    game = final_game(world, 110, 100)
    totals = place_bet(world, game, MarketType.totals, BetSide.over, line=210.5)

    summary = settle_bets(world, NOW)

    assert summary.skipped_unsupported == 1 and reload(world, totals).status == BetStatus.pending


def test_both_strategies_of_one_prediction_settle_independently(world):
    game = final_game(world, 99, 100)
    flat = place_bet(world, game, MarketType.h2h, BetSide.away, stake="1.000", strategy=StakingStrategy.flat)
    kelly = place_bet(world, game, MarketType.h2h, BetSide.away, stake="1.750", price="1.9090", strategy=StakingStrategy.kelly_fractional)
    shrunk = place_bet(world, game, MarketType.h2h, BetSide.away, stake="0.800", price="1.9090", strategy=StakingStrategy.kelly_shrunk)
    market = place_bet(world, game, MarketType.h2h, BetSide.away, stake="1.000", price="2.0000", strategy=StakingStrategy.market_edge)

    settle_bets(world, NOW)

    assert reload(world, flat).profit_units == Decimal("0.909")
    assert reload(world, kelly).profit_units == Decimal("1.591")  # 1.75 * 0.909 = 1.59075
    assert reload(world, shrunk).profit_units == Decimal("0.727")  # 0.80 * 0.909 = 0.7272
    assert reload(world, market).profit_units == Decimal("1.000")  # 1.00 * (2.0 - 1.0) = 1.000


def test_dry_run_settles_nothing(world):
    game = final_game(world, 110, 100)
    bet = place_bet(world, game, MarketType.h2h, BetSide.home)

    summary = settle_bets(world, NOW, dry_run=True)

    assert summary.total_settled == 1 and reload(world, bet).status == BetStatus.pending


# --- fill_clv --------------------------------------------------------------------------------------------------------

def spread_bet(world, game, **kwargs):
    kwargs.setdefault("line", -3.5)
    return place_bet(world, game, MarketType.spreads, BetSide.home, **kwargs)


def test_a_matching_closing_quote_fills_price_line_and_a_positive_clv(world):
    game = add_game(world)
    bet = spread_bet(world, game, american=100, price="2.0000")
    closing = add_quote(world, game, "pinnacle", MarketType.spreads, BetSide.home, -125, -3.5, captured_at=CLOSING_AT)
    add_marker(world, game)

    summary = fill_clv(world, NOW)

    bet = reload(world, bet)
    assert summary.filled == 1
    assert bet.closing_odds_id == closing.id
    assert bet.closing_price == Decimal("1.8000")
    assert bet.closing_line == Decimal("-3.5")
    assert float(bet.clv_pct) == pytest.approx(2.0 / 1.8 - 1, abs=1e-4)
    assert float(bet.clv_pct) > 0


def test_a_worse_closing_price_gives_a_negative_clv(world):
    game = add_game(world)
    bet = spread_bet(world, game, american=100, price="2.0000")
    add_quote(world, game, "pinnacle", MarketType.spreads, BetSide.home, 110, -3.5, captured_at=CLOSING_AT)
    add_marker(world, game)

    fill_clv(world, NOW)

    assert float(reload(world, bet).clv_pct) == pytest.approx(2.0 / 2.1 - 1, abs=1e-4)


def test_an_unchanged_price_is_a_zero_clv_not_a_missing_one(world):
    game = add_game(world)
    bet = place_bet(world, game, MarketType.h2h, BetSide.home, american=-110, price="1.9090")  # the feed stores no new row
    add_marker(world, game)

    fill_clv(world, NOW)

    bet = reload(world, bet)
    assert bet.closing_price == Decimal("1.9090") and bet.closing_line is None
    assert float(bet.clv_pct) == 0.0


def test_no_closing_marker_means_no_clv_even_when_later_quotes_exist(world):
    game = add_game(world)
    bet = spread_bet(world, game)
    add_quote(world, game, "pinnacle", MarketType.spreads, BetSide.home, -130, -3.5, captured_at=CLOSING_AT)
    add_marker(world, game, kind=CAPTURE_OPENING)  # an opening marker is not a closing line

    summary = fill_clv(world, NOW)

    bet = reload(world, bet)
    assert summary.no_closing_marker == 1
    assert bet.closing_price is None and bet.closing_odds_id is None and bet.clv_pct is None


def test_a_closing_capture_before_the_bet_does_not_count(world):
    game = add_game(world)
    bet = spread_bet(world, game, placed_at=CLOSING_AT + timedelta(minutes=5), quote_at=CLOSING_AT + timedelta(minutes=4))
    add_quote(world, game, "pinnacle", MarketType.spreads, BetSide.home, -130, -3.5, captured_at=CLOSING_AT)
    add_marker(world, game)

    summary = fill_clv(world, NOW)

    assert summary.closing_before_bet == 1 and reload(world, bet).closing_price is None


def test_a_moved_line_leaves_the_price_null_and_records_where_the_book_closed(world):
    game = add_game(world)
    bet = spread_bet(world, game, line=-3.5)
    add_quote(world, game, "pinnacle", MarketType.spreads, BetSide.home, -105, -4.5, captured_at=CLOSING_AT)
    add_marker(world, game)

    summary = fill_clv(world, NOW)

    bet = reload(world, bet)
    assert summary.line_moved == 1
    assert bet.closing_price is None and bet.closing_odds_id is None
    assert bet.closing_line == Decimal("-4.5") and bet.clv_pct is None


def test_only_the_same_sportsbook_counts(world):
    game = add_game(world)
    bet = spread_bet(world, game, american=100, price="2.0000", book="pinnacle")
    add_quote(world, game, "fanduel", MarketType.spreads, BetSide.home, -300, -3.5, captured_at=CLOSING_AT)
    add_marker(world, game)

    fill_clv(world, NOW)

    bet = reload(world, bet)  # pinnacle never re-quoted: its own quote is still the closing one (0 CLV)
    assert bet.closing_price == Decimal("2.0000") and float(bet.clv_pct) == 0.0


def test_quotes_after_tipoff_are_ignored(world):
    game = add_game(world)
    bet = spread_bet(world, game, american=100, price="2.0000")
    add_quote(world, game, "pinnacle", MarketType.spreads, BetSide.home, -250, -3.5, captured_at=TIPOFF + timedelta(minutes=30))
    add_marker(world, game)

    fill_clv(world, NOW)

    assert reload(world, bet).closing_price == Decimal("2.0000")


def test_a_game_that_has_not_tipped_off_is_left_alone(world):
    game = add_game(world)
    bet = spread_bet(world, game)
    add_quote(world, game, "pinnacle", MarketType.spreads, BetSide.home, -130, -3.5, captured_at=CLOSING_AT)
    add_marker(world, game)

    summary = fill_clv(world, TIPOFF - timedelta(minutes=10))

    assert summary.candidates == 0 and reload(world, bet).closing_price is None


def test_the_other_side_and_other_market_of_the_book_are_not_mixed_up(world):
    game = add_game(world)
    bet = spread_bet(world, game, american=100, price="2.0000")
    add_quote(world, game, "pinnacle", MarketType.spreads, BetSide.away, -400, 3.5, captured_at=CLOSING_AT)
    add_quote(world, game, "pinnacle", MarketType.h2h, BetSide.home, -400, None, captured_at=CLOSING_AT)
    add_marker(world, game)

    fill_clv(world, NOW)

    assert reload(world, bet).closing_price == Decimal("2.0000")


def test_fill_clv_is_idempotent_and_dry_run_writes_nothing(world):
    game = add_game(world)
    bet = spread_bet(world, game, american=100, price="2.0000")
    add_quote(world, game, "pinnacle", MarketType.spreads, BetSide.home, -125, -3.5, captured_at=CLOSING_AT)
    add_marker(world, game)

    preview = fill_clv(world, NOW, dry_run=True)
    assert preview.filled == 1 and reload(world, bet).closing_price is None

    fill_clv(world, NOW)
    first = reload(world, bet)
    first_id, first_price = first.closing_odds_id, first.closing_price
    add_quote(world, game, "pinnacle", MarketType.spreads, BetSide.home, -300, -3.5, captured_at=CLOSING_AT + timedelta(minutes=1))
    again = fill_clv(world, NOW)

    assert again.candidates == 0
    bet = reload(world, bet)
    assert (bet.closing_odds_id, bet.closing_price) == (first_id, first_price)


def test_clv_is_independent_of_settlement(world):
    game = final_game(world, 110, 100)
    bet = spread_bet(world, game, american=100, price="2.0000")
    add_quote(world, game, "pinnacle", MarketType.spreads, BetSide.home, -125, -3.5, captured_at=CLOSING_AT)
    add_marker(world, game)

    settle_bets(world, NOW)
    fill_clv(world, NOW)

    bet = reload(world, bet)
    assert bet.status == BetStatus.won and bet.closing_price == Decimal("1.8000")
