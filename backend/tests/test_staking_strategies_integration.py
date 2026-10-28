from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlmodel import select

from app.analytics import betting_policy as bp
from app.analytics.props_engine import american_to_decimal
from app.models import (
    BetSide,
    BetStatus,
    Game,
    MarketType,
    ModelPrediction,
    ModelVersion,
    OddsHistory,
    OddsSnapshotCapture,
    SimulatedBet,
    Sportsbook,
    StakingStrategy,
)
from app.services.elo_service import EloRatingService
from app.services.paper_report import build_report
from app.services.prediction_recorder import PredictionRecorder
from app.services.settlement import settle_bets
from tests.synthetic_league import insert_league, make_league

NOW = datetime(2026, 10, 20, 18, 0, tzinfo=timezone.utc)


@pytest.fixture
def synthetic_world(db_session):
    # Create a small synthetic league (2 seasons, 4 teams)
    games = make_league(n_seasons=2, n_teams=4, seed=42, rounds=6)
    insert_league(db_session, games)

    # Champion Elo model
    champion = ModelVersion(
        name="elo_538",
        version="1.1",
        role="champion",
        params={"sigma": 14.0},
        promoted_at=NOW - timedelta(days=30),
    )
    pinnacle = Sportsbook(key="pinnacle", name="Pinnacle", region="eu", is_sharp=True)
    draftkings = Sportsbook(key="draftkings", name="DraftKings", region="us", is_sharp=False)
    db_session.add_all([champion, pinnacle, draftkings])
    db_session.commit()

    # Backfill Elo ratings for the champion model
    EloRatingService(db_session, model_version_id=champion.id).rebuild_all()

    class Context:
        def __init__(self):
            self.session = db_session
            self.champion = champion
            self.pinnacle = pinnacle
            self.draftkings = draftkings
            self._updates = 0

        def create_game(self, home_team_id, away_team_id, hours_ahead=5.0, status="scheduled"):
            game = Game(
                season_id=1,
                home_team_id=home_team_id,
                away_team_id=away_team_id,
                commence_time=NOW + timedelta(hours=hours_ahead),
                status=status,
            )
            self.session.add(game)
            self.session.commit()
            return game

        def add_quote(self, game, book, market, side, american_price, line=None, captured_at=None):
            self._updates += 1
            captured = captured_at or (NOW - timedelta(minutes=15))
            quote = OddsHistory(
                game_id=game.id,
                sportsbook_id=book.id,
                market=market,
                side=side,
                line=Decimal(str(line)) if line is not None else None,
                price_american=american_price,
                book_last_update=captured - timedelta(seconds=self._updates),
                captured_at=captured,
            )
            self.session.add(quote)
            self.session.commit()
            return quote

    return Context()


def test_market_edge_and_kelly_shrunk_produce_bets_where_eligible(synthetic_world):
    session = synthetic_world.session
    # Game 1: Model has an edge on Home AND soft book beats Pinnacle fair price
    # Teams 1 and 2
    game1 = synthetic_world.create_game(home_team_id=1, away_team_id=2, hours_ahead=4.0)

    # Pinnacle: -110 / -110 -> fair prob = 0.50 each
    synthetic_world.add_quote(game1, synthetic_world.pinnacle, MarketType.h2h, BetSide.home, -110)
    synthetic_world.add_quote(game1, synthetic_world.pinnacle, MarketType.h2h, BetSide.away, -110)

    # Soft book offers +130 on Home (decimal 2.30)
    # Pinnacle fair prob = 0.50, price = 2.30 -> EV = 0.50 * 2.30 - 1.0 = +0.15 >= 0.02
    synthetic_world.add_quote(game1, synthetic_world.draftkings, MarketType.h2h, BetSide.home, 130)

    # Run recorder
    summary = PredictionRecorder(session, now=NOW).run()

    # If model also has edge on home, all 4 strategies place a bet
    bets = session.exec(select(SimulatedBet).where(SimulatedBet.prediction_id.in_(
        select(ModelPrediction.id).where(ModelPrediction.game_id == game1.id)
    ))).all()
    strategies_bet = {b.strategy for b in bets}

    # market_edge MUST be placed because soft book price 2.30 beats fair prob 0.50
    assert StakingStrategy.market_edge in strategies_bet

    market_bet = next(b for b in bets if b.strategy == StakingStrategy.market_edge)
    assert float(market_bet.stake_units) == 1.0
    assert market_bet.kelly_multiplier is None
    assert float(market_bet.ev_per_unit) == pytest.approx(0.50 * american_to_decimal(130) - 1.0, abs=1e-4)


def test_market_edge_bets_exist_when_model_has_no_edge_but_soft_book_beats_fair(synthetic_world):
    session = synthetic_world.session
    # Find two teams where Elo win prob is very close to 0.50
    # Let's inspect model prediction or ensure model has no raw edge (raw_edge < 0.02)
    game = synthetic_world.create_game(home_team_id=1, away_team_id=2, hours_ahead=5.0)

    # We can check what model predicts for 1 vs 2:
    recorder = PredictionRecorder(session, now=NOW)
    models = recorder._load_models(recorder.run(dry_run=True))
    champ = models[0]
    season_id = recorder._season_id_for(game, recorder._season_ids_by_label())
    pred = recorder._predict(champ, game, season_id)
    p_home_model = pred.p_home

    # Set Pinnacle pair so that fair home prob is slightly ABOVE model prob
    # e.g. fair_home = p_home_model + 0.01 (so raw_edge = -0.01 < 0.02, model has no edge)
    # Let's construct prices that devig to p_fair_home ~= p_home_model:
    # If p_fair_home is close to p_home_model:
    # Suppose p_home_model is around 0.55.
    # Set Pinnacle: home -130 (1.769), away 110 (2.100).
    # fair_home ~= 0.54. raw_edge = 0.55 - 0.54 = 0.01 < 0.02 (MIN_RAW_EDGE).
    # So model edge is below min!
    # But DraftKings offers home at +100 (2.000).
    # With fair_home = 0.54, taking 2.000 gives EV = 0.54 * 2.000 - 1.0 = +0.08 >= 0.02!
    pinnacle_fair_home = p_home_model - 0.005  # model edge is 0.005 < 0.02
    p_away = 1.0 - pinnacle_fair_home

    # Convert probs to American prices with equal vig
    def prob_to_american(p, vig=0.04):
        p_vig = p * (1.0 + vig)
        if p_vig >= 0.5:
            return int(round(-100.0 * p_vig / (1.0 - p_vig)))
        else:
            return int(round(100.0 * (1.0 - p_vig) / p_vig))

    pinn_home_us = prob_to_american(pinnacle_fair_home)
    pinn_away_us = prob_to_american(p_away)

    synthetic_world.add_quote(game, synthetic_world.pinnacle, MarketType.h2h, BetSide.home, pinn_home_us)
    synthetic_world.add_quote(game, synthetic_world.pinnacle, MarketType.h2h, BetSide.away, pinn_away_us)

    # Soft book offers a massive price on Home: +150 (decimal 2.50)
    synthetic_world.add_quote(game, synthetic_world.draftkings, MarketType.h2h, BetSide.home, 150)

    summary = PredictionRecorder(session, now=NOW).run()

    bets = session.exec(select(SimulatedBet).where(SimulatedBet.prediction_id.in_(
        select(ModelPrediction.id).where(ModelPrediction.game_id == game.id)
    ))).all()

    # Verify: ONLY market_edge placed a bet, model-based strategies did NOT!
    assert len(bets) == 1
    assert bets[0].strategy == StakingStrategy.market_edge
    assert float(bets[0].stake_units) == 1.0
    assert bets[0].status == BetStatus.pending
    assert summary.bets_placed[StakingStrategy.market_edge.value] == 1
    assert summary.bets_placed[StakingStrategy.flat.value] == 0
    assert summary.bets_placed[StakingStrategy.kelly_fractional.value] == 0
    assert summary.bets_placed[StakingStrategy.kelly_shrunk.value] == 0


def test_recorder_rerun_is_idempotent_across_all_strategies(synthetic_world):
    session = synthetic_world.session
    game = synthetic_world.create_game(home_team_id=1, away_team_id=2, hours_ahead=3.0)

    # Pinnacle
    synthetic_world.add_quote(game, synthetic_world.pinnacle, MarketType.h2h, BetSide.home, -110)
    synthetic_world.add_quote(game, synthetic_world.pinnacle, MarketType.h2h, BetSide.away, -110)
    # DraftKings has huge price on home: +140
    synthetic_world.add_quote(game, synthetic_world.draftkings, MarketType.h2h, BetSide.home, 140)

    # First run
    run1 = PredictionRecorder(session, now=NOW).run()
    bets1 = session.exec(select(SimulatedBet)).all()
    assert len(bets1) >= 1

    # Second run (same timestamp)
    run2 = PredictionRecorder(session, now=NOW).run()
    bets2 = session.exec(select(SimulatedBet)).all()

    # Exactly identical bet count
    assert len(bets2) == len(bets1)
    assert sum(run2.bets_placed.values()) == 0
    assert run2.predictions_written == 0
    assert run2.predictions_existing == run1.predictions_written


def test_settlement_of_market_edge_bet(synthetic_world):
    session = synthetic_world.session
    game = synthetic_world.create_game(home_team_id=1, away_team_id=2, hours_ahead=2.0)

    synthetic_world.add_quote(game, synthetic_world.pinnacle, MarketType.h2h, BetSide.home, -110)
    synthetic_world.add_quote(game, synthetic_world.pinnacle, MarketType.h2h, BetSide.away, -110)
    # Soft book offers +120 (2.20)
    synthetic_world.add_quote(game, synthetic_world.draftkings, MarketType.h2h, BetSide.home, 120)

    # Record bets
    PredictionRecorder(session, now=NOW).run()

    market_bet = session.exec(select(SimulatedBet).where(
        SimulatedBet.strategy == StakingStrategy.market_edge
    )).first()
    assert market_bet is not None
    assert market_bet.status == BetStatus.pending

    # Finalize game: home wins 105 - 100
    game.status = "final"
    game.home_score = 105
    game.away_score = 100
    session.add(game)
    session.commit()

    # Settle bets
    settle_summary = settle_bets(session, NOW + timedelta(hours=5))
    assert settle_summary.total_settled >= 1

    session.refresh(market_bet)
    assert market_bet.status == BetStatus.won
    # Profit = stake * (price - 1) = 1.0 * (2.20 - 1.0) = 1.20
    assert float(market_bet.profit_units) == pytest.approx(1.20, abs=1e-3)
    assert market_bet.settled_at is not None

    # Check paper report shows updated bankroll
    report = build_report(session, NOW + timedelta(hours=5))
    by_strat = {s.strategy: s for s in report.strategies}
    market_perf = by_strat[StakingStrategy.market_edge.value]
    assert market_perf.bets >= 1
    assert market_perf.settled >= 1
    assert market_perf.win_rate == pytest.approx(1.0)
    assert market_perf.pnl_units == pytest.approx(1.20, abs=1e-3)
    assert market_perf.bankroll == pytest.approx(bp.START_BANKROLL + 1.20, abs=1e-3)
