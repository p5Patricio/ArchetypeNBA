from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlmodel import select

from app.analytics import betting_policy as policy
from app.analytics import elo
from app.models import (
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
    TeamEloRating,
)
from app.services.elo_service import MODEL_NAME, MODEL_VERSION
from app.services import model_registry
from app.services.prediction_recorder import PredictionRecorder, RecorderError

NOW = datetime(2026, 10, 20, 18, 0, tzinfo=timezone.utc)
SIGMA = 14.0
RATINGS = {"AAA": 1600.0, "BBB": 1500.0, "CCC": 1550.0, "DDD": 1450.0}

# Opening night: ratings were set last season, so the carryover applies once.
MU = elo.expected_margin(elo.season_carryover(1600.0), elo.season_carryover(1500.0))  # AAA at home vs BBB
P_HOME = elo.expected_home_win_prob(elo.season_carryover(1600.0), elo.season_carryover(1500.0))


def american(price):
    """Decimal odds as the recorder computes them from an American price."""
    return round(100.0 / abs(price) + 1.0, 3) if price < 0 else round(price / 100.0 + 1.0, 3)


class World:
    def __init__(self, session):
        self.session = session
        self.old = Season(season_label="2025-26", is_active=True)
        self.new = Season(season_label="2026-27")
        session.add_all([self.old, self.new])
        self.teams = {}
        for abbr in [*RATINGS, "EEE"]:
            team = Team(abbreviation=abbr, full_name=f"{abbr} Team", city=abbr, conference="East", division="Atlantic")
            session.add(team)
            self.teams[abbr] = team
        self.books = {
            key: Sportsbook(key=key, name=key, region="eu" if key == "pinnacle" else "us", is_sharp=key == "pinnacle")
            for key in ("pinnacle", "draftkings", "fanduel")
        }
        session.add_all(self.books.values())
        model = ModelVersion(name=MODEL_NAME, version=MODEL_VERSION, params={"sigma": SIGMA})
        session.add(model)
        session.commit()
        for i, (abbr, rating) in enumerate(RATINGS.items()):
            session.add(
                TeamEloRating(
                    model_version_id=model.id,
                    team_id=self.teams[abbr].id,
                    season_id=self.old.id,
                    game_id=f"00225{i:05d}",
                    game_date=date(2026, 4, 10),
                    rating_after=rating,
                )
            )
        session.commit()
        self._updates = 0

    def game(self, home="AAA", away="BBB", hours=5.0, status="scheduled", season=None, event=None):
        game = Game(
            provider_event_id=event or f"evt-{home}-{away}-{hours}",
            season_id=(season or self.old).id,  # the real rows point at the old season: the recorder must not trust it
            home_team_id=self.teams[home].id,
            away_team_id=self.teams[away].id,
            commence_time=NOW + timedelta(hours=hours),
            status=status,
        )
        self.session.add(game)
        self.session.commit()
        return game

    def quote(self, game, book, market, side, line, price, captured=None, updated=None, player_id=None):
        captured = captured or NOW - timedelta(minutes=10)
        self._updates += 1
        row = OddsHistory(
            game_id=game.id,
            sportsbook_id=self.books[book].id,
            market=market,
            player_id=player_id,
            side=side,
            line=None if line is None else Decimal(str(line)),
            price_american=price,
            book_last_update=updated or captured - timedelta(minutes=1, seconds=self._updates),
            captured_at=captured,
        )
        self.session.add(row)
        self.session.commit()
        return row

    def h2h(self, game, book, home_price, away_price, **kw):
        return (
            self.quote(game, book, MarketType.h2h, BetSide.home, None, home_price, **kw),
            self.quote(game, book, MarketType.h2h, BetSide.away, None, away_price, **kw),
        )

    def spread(self, game, book, home_line, home_price, away_price, **kw):
        return (
            self.quote(game, book, MarketType.spreads, BetSide.home, home_line, home_price, **kw),
            self.quote(game, book, MarketType.spreads, BetSide.away, -home_line, away_price, **kw),
        )

    def total(self, game, book, line, over_price, under_price, **kw):
        return (
            self.quote(game, book, MarketType.totals, BetSide.over, line, over_price, **kw),
            self.quote(game, book, MarketType.totals, BetSide.under, line, under_price, **kw),
        )

    def prop(self, game, book, player_id, market, line, over_price, under_price, **kw):
        return (
            self.quote(game, book, market, BetSide.over, line, over_price, player_id=player_id, **kw),
            self.quote(game, book, market, BetSide.under, line, under_price, player_id=player_id, **kw),
        )

    def recorder(self, **kw):
        return PredictionRecorder(self.session, now=kw.pop("now", NOW), **kw)

    def bet(self, game, stake, strategy=StakingStrategy.flat, status=BetStatus.pending, profit=None,
            market=MarketType.h2h, side=BetSide.home, line=None, placed_at=NOW):
        """A pre-existing bet (own prediction and odds rows) for ledger tests."""
        version = self.session.exec(select(ModelVersion)).one()
        odds = self.quote(game, "draftkings", market, side, line, 150, captured=NOW - timedelta(days=3))
        prediction = ModelPrediction(
            model_version_id=version.id, game_id=game.id, market=market, side=side,
            line=None if line is None else Decimal(str(line)), model_prob=Decimal("0.5"),
        )
        self.session.add(prediction)
        self.session.commit()
        bet = SimulatedBet(
            prediction_id=prediction.id, odds_taken_id=odds.id, price_taken=Decimal("2.5"), ev_per_unit=Decimal("0.1"),
            strategy=strategy, stake_units=Decimal(str(stake)), bankroll_before=Decimal("100"), status=status,
            profit_units=None if profit is None else Decimal(str(profit)), placed_at=placed_at,
            settled_at=None if status == BetStatus.pending else placed_at,
        )
        self.session.add(bet)
        self.session.commit()
        return bet


@pytest.fixture
def world(db_session):
    return World(db_session)


def _predictions(session):
    return session.exec(select(ModelPrediction)).all()


def _bets(session):
    return session.exec(select(SimulatedBet)).all()


def _bets_of(session, game):
    """strategy -> bet, for the bets whose prediction belongs to ``game``."""
    return {
        b.strategy: b
        for b in _bets(session)
        if session.get(ModelPrediction, b.prediction_id).game_id == game.id and b.placed_at is not None
    }


def _by_target(session):
    return {(p.market, p.side, None if p.line is None else float(p.line)): p for p in _predictions(session)}


# --- predictions ------------------------------------------------------------------------------


def test_h2h_predictions_are_recorded_for_a_game_without_odds(world, db_session):
    game = world.game()

    summary = world.recorder().run()

    preds = _by_target(db_session)
    assert set(preds) == {(MarketType.h2h, BetSide.home, None), (MarketType.h2h, BetSide.away, None)}
    home, away = preds[(MarketType.h2h, BetSide.home, None)], preds[(MarketType.h2h, BetSide.away, None)]
    assert float(home.model_prob) == pytest.approx(P_HOME, abs=1e-5)
    assert float(away.model_prob) == pytest.approx(1.0 - P_HOME, abs=1e-5)
    assert float(home.projection) == pytest.approx(MU, abs=0.01)
    assert home.game_id == game.id and home.predicted_at is not None
    assert (summary.games_considered, summary.games_processed, summary.predictions_written) == (1, 1, 2)
    assert summary.skipped["no_fresh_quotes"] == 3
    assert _bets(db_session) == []


def test_opening_night_ratings_include_the_season_carryover(world, db_session):
    world.game()  # season_id points at 2025-26, but the tip-off belongs to 2026-27

    world.recorder().run()

    raw_p = elo.expected_home_win_prob(1600.0, 1500.0)
    stored = float(_by_target(db_session)[(MarketType.h2h, BetSide.home, None)].model_prob)
    assert stored == pytest.approx(P_HOME, abs=1e-5)
    assert abs(stored - raw_p) > 0.01


def test_ratings_are_not_regressed_inside_the_same_season(world, db_session):
    now = datetime(2026, 4, 1, 6, 0, tzinfo=timezone.utc)  # the game is in 2025-26, like the rating rows
    game = world.game()
    game.commence_time = now + timedelta(hours=5)
    db_session.add(game)
    db_session.commit()

    world.recorder(now=now).run()

    home = _by_target(db_session)[(MarketType.h2h, BetSide.home, None)]
    assert float(home.projection) == pytest.approx(elo.expected_margin(1600.0, 1500.0), abs=0.01)


def test_spread_predictions_cover_every_quoted_line_on_both_sides(world, db_session):
    game = world.game()
    world.spread(game, "pinnacle", -3.5, -110, -110)
    world.spread(game, "draftkings", -4.5, -110, -110)
    world.spread(game, "fanduel", -3.0, -110, -110)

    world.recorder().run()

    preds = _by_target(db_session)
    spreads = {key for key in preds if key[0] == MarketType.spreads}
    home_lines = (-4.5, -3.5, -3.0)
    assert spreads == {(MarketType.spreads, BetSide.home, line) for line in home_lines} | {
        (MarketType.spreads, BetSide.away, -line) for line in home_lines
    }
    for home_line in (-4.5, -3.5, -3.0):
        p_home_win, _, p_away_win = elo.spread_probabilities(MU, SIGMA, home_line)
        assert float(preds[(MarketType.spreads, BetSide.home, home_line)].model_prob) == pytest.approx(p_home_win, abs=1e-5)
        assert float(preds[(MarketType.spreads, BetSide.away, -home_line)].model_prob) == pytest.approx(p_away_win, abs=1e-5)
        assert float(preds[(MarketType.spreads, BetSide.home, home_line)].projection) == pytest.approx(MU, abs=0.01)


def test_an_integer_line_stores_the_win_probability_without_the_push(world, db_session):
    game = world.game()
    world.spread(game, "pinnacle", -3.0, -110, -110)

    world.recorder().run()

    p_win, p_push, p_loss = elo.spread_probabilities(MU, SIGMA, -3.0)
    assert p_push > 0
    stored = float(_by_target(db_session)[(MarketType.spreads, BetSide.home, -3.0)].model_prob)
    assert stored == pytest.approx(p_win, abs=1e-5)


def test_a_moved_line_replaces_the_books_old_quote(world, db_session):
    game = world.game()
    early = NOW - timedelta(hours=3)
    world.spread(game, "pinnacle", -3.5, -110, -110, captured=early, updated=early)
    world.spread(game, "pinnacle", -4.0, -110, -110)

    world.recorder().run()

    lines = {key[2] for key in _by_target(db_session) if key[0] == MarketType.spreads and key[1] == BetSide.home}
    assert lines == {-4.0}


# --- fair probability and candidates -------------------------------------------------------


def test_without_a_sharp_book_predictions_are_recorded_but_nothing_is_bet(world, db_session):
    game = world.game()
    world.h2h(game, "draftkings", -150, 130)
    world.spread(game, "fanduel", -3.5, -105, -115)

    summary = world.recorder().run()

    assert len(_predictions(db_session)) == 4  # the h2h pair and one spread pair
    assert _bets(db_session) == []
    assert summary.skipped["no_sharp_reference"] == 2
    assert summary.candidates == []


def test_a_book_on_a_different_line_than_the_sharp_pair_is_ignored(world, db_session):
    game = world.game()
    world.spread(game, "pinnacle", -3.5, -110, -110)
    world.spread(game, "fanduel", -3.5, 105, -125)
    world.spread(game, "draftkings", -4.5, 300, -400)  # a far better price, but not the same line

    world.recorder().run()

    home_bets = [b for b in _bets(db_session) if b.strategy == StakingStrategy.flat]
    assert len(home_bets) == 1
    bet = home_bets[0]
    assert float(bet.line_taken) == -3.5
    odds = db_session.get(OddsHistory, bet.odds_taken_id)
    assert (odds.sportsbook_id, odds.side) == (world.books["fanduel"].id, BetSide.home)
    assert float(bet.price_taken) == pytest.approx(2.05)


def test_the_best_price_across_books_is_taken(world, db_session):
    game = world.game()
    world.h2h(game, "pinnacle", -150, 130)
    world.h2h(game, "fanduel", -145, 120)
    dk_home, _ = world.h2h(game, "draftkings", -140, 110)

    world.recorder().run()

    bets = _bets(db_session)
    assert {b.odds_taken_id for b in bets} == {dk_home.id}
    assert float(bets[0].price_taken) == pytest.approx(american(-140))


def test_a_candidate_without_enough_edge_is_not_bet(world, db_session):
    game = world.game()
    world.h2h(game, "pinnacle", -250, 210)  # the market already agrees with (or beats) the model

    summary = world.recorder().run()

    assert _bets(db_session) == []
    assert summary.skipped["edge_below_min"] == 2
    assert len(summary.candidates) == 2


def test_an_eligible_candidate_creates_a_flat_and_a_kelly_bet_with_the_right_fields(world, db_session):
    game = world.game()
    pinnacle_home, _ = world.h2h(game, "pinnacle", -170, 145)

    summary = world.recorder().run()

    bets = {b.strategy: b for b in _bets(db_session)}
    assert set(bets) == {StakingStrategy.flat, StakingStrategy.kelly_fractional, StakingStrategy.kelly_shrunk}
    assert dict(summary.bets_placed) == {"flat": 1, "kelly_fractional": 1, "kelly_shrunk": 1}

    candidate = next(c for c in summary.candidates if c.eligible)
    prediction = _by_target(db_session)[(MarketType.h2h, BetSide.home, None)]
    flat, kelly, shrunk = bets[StakingStrategy.flat], bets[StakingStrategy.kelly_fractional], bets[StakingStrategy.kelly_shrunk]
    for bet in (flat, kelly, shrunk):
        assert bet.prediction_id == prediction.id
        assert bet.odds_taken_id == pinnacle_home.id
        assert float(bet.price_taken) == pytest.approx(american(-170))
        assert bet.line_taken is None
        assert float(bet.fair_prob_at_bet) == pytest.approx(candidate.p_fair, abs=1e-5)
        assert float(bet.ev_per_unit) == pytest.approx(candidate.ev, abs=1e-5)
        assert float(bet.bankroll_before) == 100.0
        assert bet.status == BetStatus.pending
        assert bet.placed_at.replace(tzinfo=timezone.utc) == NOW

    p_blend = policy.shrink_probability(candidate.p_cond, candidate.p_fair)
    f_star = policy.kelly_fraction(p_blend, 0.0, american(-170))
    break_even = 1.0 / american(-170)
    edge = p_blend - break_even
    shrink = policy.shrink_factor(edge, policy.MODEL_PROB_NOISE_SD)
    assert float(flat.stake_units) == 1.0 and flat.kelly_multiplier is None
    assert float(kelly.kelly_multiplier) == 0.25
    assert float(kelly.stake_units) == pytest.approx(round(100.0 * f_star * 0.25, 3), abs=1e-3)
    assert 0.05 < float(kelly.stake_units) < 2.0
    assert float(shrunk.kelly_multiplier) == pytest.approx(round(0.5 * shrink, 3), abs=1e-3)
    assert float(shrunk.stake_units) == pytest.approx(round(100.0 * f_star * 0.5 * shrink, 3), abs=1e-3)
    assert 0.0 < float(shrunk.stake_units) < 2.0


def test_the_kelly_stake_is_capped_at_two_percent_of_the_bankroll(world, db_session):
    game = world.game()
    world.h2h(game, "pinnacle", -150, 130)
    world.h2h(game, "draftkings", -140, 110)  # a bigger edge: full-Kelly quarter exceeds the 2% cap

    world.recorder().run()

    kelly = next(b for b in _bets(db_session) if b.strategy == StakingStrategy.kelly_fractional)
    assert float(kelly.stake_units) == 2.0


def test_a_spread_bet_records_the_line_and_the_prediction_at_that_line(world, db_session):
    game = world.game()
    world.spread(game, "pinnacle", -3.5, -110, -110)
    fanduel_home, _ = world.spread(game, "fanduel", -3.5, 105, -125)

    world.recorder().run()

    bet = next(b for b in _bets(db_session) if b.strategy == StakingStrategy.flat)
    prediction = db_session.get(ModelPrediction, bet.prediction_id)
    assert (prediction.market, prediction.side, float(prediction.line)) == (MarketType.spreads, BetSide.home, -3.5)
    assert bet.odds_taken_id == fanduel_home.id
    assert float(bet.fair_prob_at_bet) == pytest.approx(0.5, abs=1e-5)


def test_the_away_side_is_bet_at_its_own_line(world, db_session):
    game = world.game(home="DDD", away="AAA")  # the model expects the visitor to win
    world.spread(game, "pinnacle", -3.5, -110, -110)  # ... yet the market makes the home side a 3.5-point favourite
    world.spread(game, "draftkings", -3.5, -110, 105)

    world.recorder().run()

    bets = _bets_of(db_session, game)
    prediction = db_session.get(ModelPrediction, bets[StakingStrategy.flat].prediction_id)
    assert (prediction.market, prediction.side, float(prediction.line)) == (MarketType.spreads, BetSide.away, 3.5)
    assert float(bets[StakingStrategy.flat].line_taken) == 3.5
    assert len(_bets(db_session)) == 4


# --- idempotency and guards --------------------------------------------------------------------


def test_a_second_run_writes_nothing(world, db_session):
    game = world.game()
    world.h2h(game, "pinnacle", -170, 145)
    world.spread(game, "pinnacle", -3.5, -110, -110)
    world.recorder().run()
    before = (len(_predictions(db_session)), len(_bets(db_session)))

    summary = world.recorder().run()

    assert (len(_predictions(db_session)), len(_bets(db_session))) == before
    assert summary.predictions_written == 0 and summary.predictions_existing == before[0]
    assert sum(summary.bets_placed.values()) == 0
    assert summary.skipped["already_bet"] == 3


def test_only_one_bet_per_side_even_if_the_line_moves(world, db_session):
    game = world.game()
    world.spread(game, "pinnacle", -3.5, -110, -110)
    world.spread(game, "fanduel", -3.5, 105, -125)
    world.recorder().run()
    first = {b.id for b in _bets(db_session)}

    later = NOW + timedelta(minutes=30)
    world.spread(game, "pinnacle", -2.5, -110, -110, captured=later - timedelta(minutes=5))
    world.spread(game, "fanduel", -2.5, 105, -125, captured=later - timedelta(minutes=5))
    summary = world.recorder(now=later).run()

    assert {b.id for b in _bets(db_session)} == first
    assert summary.skipped["already_bet"] == 4


def test_the_horizon_is_inclusive_and_nothing_at_or_after_tip_off_is_touched(world, db_session):
    inside = world.game(hours=20, event="inside")
    world.game(home="EEE", away="DDD", hours=20 + 1 / 3600, event="just-outside")
    world.game(home="EEE", away="CCC", hours=0, event="tipping-off-now")
    world.game(home="CCC", away="DDD", hours=-1, event="started")
    world.h2h(inside, "pinnacle", -170, 145)

    summary = world.recorder().run()

    assert summary.games_considered == 1
    assert {p.game_id for p in _predictions(db_session)} == {inside.id}


def test_a_stale_quote_is_ignored(world, db_session):
    game = world.game()
    world.h2h(game, "pinnacle", -170, 145, captured=NOW - timedelta(hours=7))

    summary = world.recorder().run()

    assert _bets(db_session) == []
    assert len(_predictions(db_session)) == 2  # h2h predictions are recorded anyway
    assert summary.skipped["no_fresh_quotes"] >= 1


def test_a_recent_capture_marker_keeps_an_unchanged_old_quote_fresh(world, db_session):
    game = world.game()
    world.h2h(game, "pinnacle", -170, 145, captured=NOW - timedelta(hours=7))
    db_session.add(OddsSnapshotCapture(game_id=game.id, kind="opening", captured_at=NOW - timedelta(minutes=30)))
    db_session.commit()

    world.recorder().run()

    assert len(_bets(db_session)) == 3


def test_quotes_captured_after_now_are_ignored(world, db_session):
    game = world.game()
    world.h2h(game, "pinnacle", -170, 145, captured=NOW + timedelta(minutes=5))

    world.recorder().run()

    assert _bets(db_session) == []


def test_a_game_is_skipped_while_a_team_has_an_earlier_unsettled_game(world, db_session):
    first = world.game(home="AAA", away="BBB", hours=3, event="first")
    second = world.game(home="CCC", away="AAA", hours=15, event="second")

    summary = world.recorder().run()

    assert {p.game_id for p in _predictions(db_session)} == {first.id}
    assert summary.skipped["stale_ratings_earlier_game"] == 1
    assert summary.games_considered == 2 and summary.games_processed == 1


def test_a_live_game_that_started_recently_also_blocks(world, db_session):
    world.game(home="AAA", away="BBB", hours=-2, status="live", event="live")
    world.game(home="CCC", away="AAA", hours=4, event="later")

    summary = world.recorder().run()

    assert _predictions(db_session) == []
    assert summary.skipped["stale_ratings_earlier_game"] == 1


def test_settled_or_long_gone_earlier_games_do_not_block(world, db_session):
    world.game(home="AAA", away="BBB", hours=-5, status="final", event="done")
    world.game(home="AAA", away="CCC", hours=-30, status="scheduled", event="stuck-for-days")
    later = world.game(home="BBB", away="AAA", hours=4, event="later")

    summary = world.recorder().run()

    assert {p.game_id for p in _predictions(db_session)} == {later.id}
    assert summary.skipped["stale_ratings_earlier_game"] == 0


def test_a_team_without_ratings_is_skipped(world, db_session):
    world.game(home="AAA", away="EEE")

    summary = world.recorder().run()

    assert _predictions(db_session) == []
    assert summary.skipped["missing_ratings"] == 1


def test_the_recorder_refuses_to_run_without_a_registered_model(world, db_session):
    for version in db_session.exec(select(ModelVersion)).all():
        db_session.delete(version)
    db_session.commit()
    world.game()

    with pytest.raises(RecorderError, match="not registered"):
        world.recorder().run()


# --- bankroll and exposure caps ----------------------------------------------------------------


def test_the_bankroll_of_each_strategy_is_100_plus_its_settled_profit(world, db_session):
    other = world.game(home="CCC", away="DDD", hours=40, event="other")
    world.bet(other, 1, StakingStrategy.flat, BetStatus.won, profit=20, side=BetSide.home)
    world.bet(other, 1, StakingStrategy.kelly_fractional, BetStatus.lost, profit=-10, side=BetSide.away)
    world.bet(other, 3, StakingStrategy.flat, BetStatus.pending, side=BetSide.away)  # pending: not subtracted
    game = world.game()
    world.h2h(game, "pinnacle", -170, 145)

    world.recorder().run()

    new_bets = _bets_of(db_session, game)
    assert float(new_bets[StakingStrategy.flat].bankroll_before) == 120.0
    assert float(new_bets[StakingStrategy.kelly_fractional].bankroll_before) == 90.0


def test_the_daily_cap_limits_the_stake_with_what_is_left(world, db_session):
    other = world.game(home="CCC", away="DDD", hours=40, event="other")
    world.bet(other, 9.5, StakingStrategy.flat)  # 10% of 100 per day: 0.5 left
    game = world.game()
    world.h2h(game, "pinnacle", -170, 145)

    world.recorder().run()

    placed = _bets_of(db_session, game)
    assert float(placed[StakingStrategy.flat].stake_units) == pytest.approx(0.5)
    assert float(placed[StakingStrategy.kelly_fractional].stake_units) > 0.5  # the other strategy has its own budget


def test_a_day_with_no_room_left_places_nothing_for_that_strategy(world, db_session):
    other = world.game(home="CCC", away="DDD", hours=40, event="other")
    world.bet(other, 9.97, StakingStrategy.flat)
    game = world.game()
    world.h2h(game, "pinnacle", -170, 145)

    summary = world.recorder().run()

    assert summary.skipped["stake_below_min"] == 1
    assert summary.bets_placed["flat"] == 0 and summary.bets_placed["kelly_fractional"] == 1


def test_the_per_game_cap_counts_stakes_on_other_markets_of_the_same_game(world, db_session):
    game = world.game()
    world.bet(game, 3.5, StakingStrategy.flat, market=MarketType.spreads, line=-9.5)  # 4% of 100 per game: 0.5 left
    world.h2h(game, "pinnacle", -170, 145)

    world.recorder().run()

    assert float(_bets_of(db_session, game)[StakingStrategy.flat].stake_units) == pytest.approx(0.5)


def test_yesterdays_stakes_do_not_count_against_todays_cap(world, db_session):
    other = world.game(home="CCC", away="DDD", hours=40, event="other")
    world.bet(other, 9.9, StakingStrategy.flat, placed_at=NOW - timedelta(days=3))
    game = world.game()
    world.h2h(game, "pinnacle", -170, 145)

    world.recorder().run()

    assert float(_bets_of(db_session, game)[StakingStrategy.flat].stake_units) == 1.0


# --- dry run ------------------------------------------------------------------------------------


def test_a_dry_run_computes_everything_and_writes_nothing(world, db_session):
    game = world.game()
    world.h2h(game, "pinnacle", -170, 145)
    world.spread(game, "pinnacle", -3.5, -110, -110)

    dry = world.recorder().run(dry_run=True)

    assert _predictions(db_session) == [] and _bets(db_session) == []
    assert dry.dry_run and dry.predictions_written == 4
    assert dry.bets_placed["flat"] == 1 and dry.bets_placed["kelly_fractional"] == 1 and dry.bets_placed["kelly_shrunk"] == 1

    real = world.recorder().run()
    assert real.predictions_written == dry.predictions_written
    assert dict(real.bets_placed) == dict(dry.bets_placed)


# --- totals bets and market_edge ---------------------------------------------------------------


def test_totals_are_bet_only_by_market_edge_and_never_model_strategies(world, db_session):
    game = world.game()
    # Pinnacle devigged 50/50 at 220.5: -110 / -110
    world.total(game, "pinnacle", 220.5, -110, -110)
    # DraftKings offers Over 220.5 at +105 (price 2.05, EV = 0.5 * 2.05 - 1 = +2.5%)
    world.total(game, "draftkings", 220.5, 105, -125)

    summary = world.recorder().run()

    # Flat, kelly_fractional, kelly_shrunk must NEVER bet totals
    assert summary.bets_placed["flat"] == 0
    assert summary.bets_placed["kelly_fractional"] == 0
    assert summary.bets_placed["kelly_shrunk"] == 0
    assert summary.bets_placed["market_edge"] == 1

    bets = _bets_of(db_session, game)
    assert set(bets) == {StakingStrategy.market_edge}
    bet = bets[StakingStrategy.market_edge]
    assert float(bet.price_taken) == pytest.approx(2.05)
    assert float(bet.line_taken) == 220.5
    assert float(bet.stake_units) == 1.0  # flat 1 unit
    assert bet.status == BetStatus.pending

    pred = db_session.get(ModelPrediction, bet.prediction_id)
    assert pred.market == MarketType.totals
    assert pred.side == BetSide.over
    assert float(pred.line) == 220.5
    assert float(pred.model_prob) == pytest.approx(0.5, abs=1e-5)
    assert pred.projection is None

    # Benchmark model verification: totals attach to market_pinnacle, never champion
    champ = model_registry.get_champion(db_session)
    assert champ is not None
    assert pred.model_version_id != champ.id
    benchmark = db_session.get(ModelVersion, pred.model_version_id)
    assert benchmark.name == "market_pinnacle"
    assert benchmark.version == "1"
    assert benchmark.role == "benchmark"
    assert benchmark.params == {"family": "market"}
    assert benchmark.notes == "Pinnacle's de-vigged probability, not a forecasting model"
    # Champion stats in recorder summary must not be inflated by totals
    champ_stats = summary.models[champ.id]
    # In world, 1 game was predicted: 2 h2h predictions (home & away) stored, 0 totals attributed to champion
    assert champ_stats.predictions_written == 2


def test_totals_shadow_model_predictions_recorded_and_no_bets_created(world, db_session):
    game = world.game()
    world.total(game, "pinnacle", 220.5, -110, -110)

    summary1 = world.recorder().run()

    # Model row totals_pace v1 exists with role='shadow'
    shadow_model = db_session.exec(
        select(ModelVersion).where(
            ModelVersion.name == "totals_pace",
            ModelVersion.version == "1",
        )
    ).one()
    assert shadow_model.role == "shadow"
    assert shadow_model.params == {"family": "totals", "window": 10, "prior_weight": 5.0}

    # Predictions under totals_pace
    shadow_preds = db_session.exec(
        select(ModelPrediction).where(
            ModelPrediction.model_version_id == shadow_model.id,
            ModelPrediction.game_id == game.id,
            ModelPrediction.market == MarketType.totals,
        )
    ).all()
    assert len(shadow_preds) == 2
    by_side = {p.side: p for p in shadow_preds}
    assert BetSide.over in by_side and BetSide.under in by_side
    pred_over, pred_under = by_side[BetSide.over], by_side[BetSide.under]
    assert float(pred_over.line) == 220.5
    assert float(pred_under.line) == 220.5
    assert pred_over.projection is not None
    assert float(pred_over.projection) == pytest.approx(220.0, abs=1.0)
    assert float(pred_over.model_prob) + float(pred_under.model_prob) == pytest.approx(1.0, abs=1e-4)

    # NO bets of any kind come from totals_pace
    bets_from_shadow = db_session.exec(
        select(SimulatedBet).join(ModelPrediction).where(
            ModelPrediction.model_version_id == shadow_model.id
        )
    ).all()
    assert bets_from_shadow == []

    # Re-running is idempotent: 0 new predictions written for totals_pace
    summary2 = world.recorder().run()
    shadow_preds_after = db_session.exec(
        select(ModelPrediction).where(
            ModelPrediction.model_version_id == shadow_model.id,
            ModelPrediction.game_id == game.id,
        )
    ).all()
    assert len(shadow_preds_after) == 2


def test_props_shadow_model_predictions_recorded_and_no_bets_created(world, db_session):
    from app.models import Player, PlayerSeasonStats
    game = world.game()

    # Add a player with multi-season stats in DB so load_baselines_from_db finds him
    player = Player(id=101, full_name="Luka Doncic")
    db_session.add(player)
    db_session.commit()
    season = world.old
    db_session.add(
        PlayerSeasonStats(
            player_id=player.id,
            team_id=world.teams["AAA"].id,
            season_id=season.id,
            gp=20,
            min=700.0,
            pts=560.0,
            reb=140.0,
            ast=140.0,
        )
    )
    db_session.commit()

    # Add prop quote for this player
    world.prop(game, "draftkings", player.id, MarketType.player_points, 27.5, -115, -105)

    summary1 = world.recorder().run()

    # Model row props_nb v1 exists with role='shadow'
    shadow_model = db_session.exec(
        select(ModelVersion).where(
            ModelVersion.name == "props_nb",
            ModelVersion.version == "1",
        )
    ).one()
    assert shadow_model.role == "shadow"
    assert shadow_model.params == {"family": "props", "distribution": "negative_binomial"}

    # Predictions under props_nb: exactly 2 rows (over and under)
    shadow_preds = db_session.exec(
        select(ModelPrediction).where(
            ModelPrediction.model_version_id == shadow_model.id,
            ModelPrediction.game_id == game.id,
            ModelPrediction.market == MarketType.player_points,
            ModelPrediction.player_id == player.id,
        )
    ).all()
    assert len(shadow_preds) == 2
    by_side = {p.side: p for p in shadow_preds}
    assert BetSide.over in by_side and BetSide.under in by_side
    pred_over, pred_under = by_side[BetSide.over], by_side[BetSide.under]
    assert float(pred_over.line) == 27.5
    assert float(pred_under.line) == 27.5
    assert pred_over.projection is not None
    # 560 pts / 700 min = 0.80 pts/min * 35.0 avg min = 28.0 projected mean
    assert float(pred_over.projection) == pytest.approx(28.0, abs=0.5)
    assert float(pred_over.model_prob) + float(pred_under.model_prob) == pytest.approx(1.0, abs=1e-3)

    # NO bets of any kind come from props_nb
    bets_from_shadow = db_session.exec(
        select(SimulatedBet).join(ModelPrediction).where(
            ModelPrediction.model_version_id == shadow_model.id
        )
    ).all()
    assert bets_from_shadow == []

    # Re-running is idempotent: 0 new predictions written for props_nb
    summary2 = world.recorder().run()
    shadow_preds_after = db_session.exec(
        select(ModelPrediction).where(
            ModelPrediction.model_version_id == shadow_model.id,
            ModelPrediction.game_id == game.id,
            ModelPrediction.player_id == player.id,
        )
    ).all()
    assert len(shadow_preds_after) == 2


def test_props_shadow_skips_players_without_baselines(world, db_session):
    from app.models import Player
    game = world.game()

    # Player has no PlayerSeasonStats in DB
    player = Player(id=202, full_name="Unknown Prospect")
    db_session.add(player)
    db_session.commit()

    world.prop(game, "draftkings", player.id, MarketType.player_points, 15.5, -110, -110)

    summary = world.recorder().run()
    assert summary.skipped["no_baseline"] >= 1

    shadow_model = db_session.exec(
        select(ModelVersion).where(
            ModelVersion.name == "props_nb",
            ModelVersion.version == "1",
        )
    ).one()
    shadow_preds = db_session.exec(
        select(ModelPrediction).where(
            ModelPrediction.model_version_id == shadow_model.id,
            ModelPrediction.game_id == game.id,
            ModelPrediction.player_id == player.id,
        )
    ).all()
    assert shadow_preds == []


def test_totals_best_price_across_books_is_taken(world, db_session):
    game = world.game()
    world.total(game, "pinnacle", 220.5, -110, -110)
    world.quote(game, "draftkings", MarketType.totals, BetSide.under, 220.5, 105)
    fd_under = world.quote(game, "fanduel", MarketType.totals, BetSide.under, 220.5, 110)  # +110 (2.10) > +105 (2.05)

    summary = world.recorder().run()

    assert summary.bets_placed["market_edge"] == 1
    bet = next(b for b in _bets(db_session) if b.strategy == StakingStrategy.market_edge)
    assert bet.odds_taken_id == fd_under.id
    assert float(bet.price_taken) == pytest.approx(2.10)
    assert float(bet.line_taken) == 220.5
    pred = db_session.get(ModelPrediction, bet.prediction_id)
    assert pred.side == BetSide.under


def test_totals_idempotency_second_run_places_no_duplicate(world, db_session):
    game = world.game()
    world.total(game, "pinnacle", 220.5, -110, -110)
    world.quote(game, "draftkings", MarketType.totals, BetSide.over, 220.5, 110)

    summary1 = world.recorder().run()
    assert summary1.bets_placed["market_edge"] == 1
    n_preds_1 = len(_predictions(db_session))
    n_bets_1 = len(_bets(db_session))

    summary2 = world.recorder().run()
    assert summary2.bets_placed["market_edge"] == 0
    assert summary2.skipped["already_bet"] >= 1
    assert len(_predictions(db_session)) == n_preds_1
    assert len(_bets(db_session)) == n_bets_1


def test_totals_no_edge_no_bet(world, db_session):
    game = world.game()
    # -110 / -110 at all books -> EV < 0
    world.total(game, "pinnacle", 220.5, -110, -110)
    world.total(game, "draftkings", 220.5, -110, -110)

    summary = world.recorder().run()
    assert summary.bets_placed["market_edge"] == 0
    assert summary.skipped["ev_below_min"] >= 1
    assert _bets(db_session) == []


def test_totals_predictions_do_not_pollute_model_league(world, db_session):
    from app.services.league_report import build_league
    from app.services.model_promotion import (
        ManualOverrideRefused,
        league_rows,
        manual_promote,
        manual_retire,
    )
    from app.services.paper_report import _active_models

    game = world.game()
    world.total(game, "pinnacle", 220.5, -110, -110)
    world.quote(game, "draftkings", MarketType.totals, BetSide.over, 220.5, 110)

    # Place the totals bet and create prediction
    world.recorder().run()

    # Verify model league and promotion queries
    all_league_rows = league_rows(db_session)
    # The benchmark model MUST NOT appear in league_rows
    assert not any(r.role == "benchmark" for r in all_league_rows)
    assert not any("market_pinnacle" in r.label for r in all_league_rows)

    rows = {r.label: r for r in all_league_rows}
    champ_row = rows[f"{MODEL_NAME} {MODEL_VERSION}"]
    # league_rows strictly counts h2h home predictions:
    # Game had no h2h quotes so 1 h2h home prediction was recorded for AAA vs BBB
    assert champ_row.predictions == 1

    league = build_league(db_session, NOW)
    assert league.champion is not None
    assert league.champion.predictions == 1
    assert not any(c.role == "benchmark" for c in league.challengers)

    # Active models in paper_report must not list benchmark model
    active = _active_models(db_session)
    assert not any(a.role == "benchmark" for a in active)
    champ_active = next(a for a in active if a.role == "champion")
    # Champion has 2 predictions (home and away h2h), totals prediction is NOT counted
    assert champ_active.predictions == 2

    # Verify no totals prediction or bet is attached to champion
    champ = model_registry.get_champion(db_session)
    champ_totals_preds = db_session.exec(
        select(ModelPrediction).where(
            ModelPrediction.model_version_id == champ.id,
            ModelPrediction.market == MarketType.totals,
        )
    ).all()
    assert champ_totals_preds == []

    # Manual override refusal on benchmark model
    bench = db_session.exec(select(ModelVersion).where(ModelVersion.role == "benchmark")).one()
    with pytest.raises(ManualOverrideRefused, match="is a benchmark model"):
        manual_promote(db_session, bench.id, "try promote", NOW)
    with pytest.raises(ManualOverrideRefused, match="is a benchmark model"):
        manual_retire(db_session, bench.id, "try retire", NOW)

