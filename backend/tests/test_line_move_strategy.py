from contextlib import nullcontext
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import importlib.util
from pathlib import Path

import pytest
from sqlmodel import SQLModel, Session, create_engine, select
from sqlmodel.pool import StaticPool

from app.analytics.features import FEATURE_NAMES
from app.analytics.props_engine import american_to_decimal
from app.models import (
    CAPTURE_CLOSING,
    CAPTURE_OPENING,
    MODEL_ROLE_SHADOW,
    BetSide,
    BetStatus,
    Game,
    MarketType,
    ModelPrediction,
    ModelVersion,
    OddsHistory,
    OddsSnapshotCapture,
    Player,
    PlayerGameLog,
    Season,
    SimulatedBet,
    Sportsbook,
    StakingStrategy,
    Team,
)
from app.services import historical_backtest as bt
from app.services import line_move_strategy as lms
from app.services import tick
from app.services.clv_report import build_pinnacle_clv_report
from app.services.elo_service import EloRatingService
from app.services.paper_report import build_report, format_report
from app.services.prediction_recorder import PredictionRecorder
from tests.test_prediction_recorder import NOW as PR_NOW, World as PrWorld

NOW = datetime(2026, 10, 22, 18, 0, tzinfo=timezone.utc)
PREV_TIP = datetime(2026, 10, 20, 23, 0, tzinfo=timezone.utc)
GAME_TIP = NOW + timedelta(hours=5)  # 2026-10-22 23:00 UTC


def _handmade_exports(spread_intercept: float = -0.8, total_intercept: float = 0.9) -> dict:
    n_s = len(bt.SPREAD_MOVE_FEATURES)
    n_t = len(bt.TOTAL_MOVE_FEATURES)
    n_f = len(FEATURE_NAMES)
    return {
        "spreads": bt.RidgeFit(
            mean=(0.0,) * n_s,
            scale=(1.0,) * n_s,
            coef=(0.0,) * n_s,
            intercept=spread_intercept,
            alpha=100.0,
            n=200,
        ),
        "totals": bt.RidgeFit(
            mean=(0.0,) * n_t,
            scale=(1.0,) * n_t,
            coef=(0.0,) * n_t,
            intercept=total_intercept,
            alpha=100.0,
            n=200,
        ),
        "margin_features": {
            "feature_names": list(FEATURE_NAMES),
            "mean": [0.0] * n_f,
            "scale": [1.0] * n_f,
            "ridge": {"coef": [0.0] * n_f, "intercept": 0.0, "alpha": 100.0},
            "logistic": {"coef": [0.0] * n_f, "intercept": 0.0, "C": 0.1},
            "sigma": 12.0,
            "elo_params": {},
        },
        "sigma_spread": 12.0,
        "sigma_total": 18.0,
    }


def _handmade_params(spread_intercept: float = -0.8, total_intercept: float = 0.9) -> dict:
    return lms.build_params(_handmade_exports(spread_intercept, total_intercept))


class LineMoveWorld:
    def __init__(self, session, spread_intercept: float = -0.8, total_intercept: float = 0.9, register: bool = True):
        self.session = session
        self.old_season = Season(season_label="2025-26", is_active=False)
        self.season = Season(season_label="2026-27", is_active=True)
        session.add_all([self.old_season, self.season])

        self.teams = {}
        self.players = {}
        for abbr in ("BOS", "LAC", "NYK", "LAL"):
            team = Team(abbreviation=abbr, full_name=f"{abbr} Team", city=abbr, conference="E", division="A")
            player = Player(full_name=f"{abbr} Player")
            session.add_all([team, player])
            self.teams[abbr] = team
            self.players[abbr] = player

        self.books = {
            "pinnacle": Sportsbook(key="pinnacle", name="Pinnacle", region="eu", is_sharp=True),
            "draftkings": Sportsbook(key="draftkings", name="DraftKings", region="us", is_sharp=False),
        }
        session.add_all(self.books.values())
        session.flush()

        # Ingested previous final games in 2025-26 and 2026-27
        self.add_ingested_final("0022500001", date(2026, 4, 10), self.old_season, "BOS", "NYK", 112, 104,
                                datetime(2026, 4, 10, 23, 0, tzinfo=timezone.utc), with_game_row=False)
        self.add_ingested_final("0022500002", date(2026, 4, 10), self.old_season, "LAC", "LAL", 108, 101,
                                datetime(2026, 4, 10, 23, 0, tzinfo=timezone.utc), with_game_row=False)
        self.prev_game = self.add_ingested_final(
            "0022600001", date(2026, 10, 20), self.season, "BOS", "LAC", 110, 100, PREV_TIP, with_game_row=True
        )

        # Upcoming scheduled game G
        self.game = Game(
            provider_event_id="evt-bos-lac-upcoming",
            season_id=self.season.id,
            home_team_id=self.teams["BOS"].id,
            away_team_id=self.teams["LAC"].id,
            commence_time=GAME_TIP,
            status="scheduled",
        )
        session.add(self.game)
        session.flush()

        self._seq = 0
        captured_at = NOW - timedelta(minutes=20)
        # Pinnacle main lines: spreads -3.5/+3.5 (-110/-110), totals 220.5 (-110/-110)
        self.pin_spread_home = self.add_quote(self.game, "pinnacle", MarketType.spreads, BetSide.home, -3.5, -110, captured_at)
        self.pin_spread_away = self.add_quote(self.game, "pinnacle", MarketType.spreads, BetSide.away, 3.5, -110, captured_at)
        self.pin_total_over = self.add_quote(self.game, "pinnacle", MarketType.totals, BetSide.over, 220.5, -110, captured_at)
        self.pin_total_under = self.add_quote(self.game, "pinnacle", MarketType.totals, BetSide.under, 220.5, -110, captured_at)

        # DraftKings at the same lines with BETTER prices on home (+100) and over (-105), plus a different line
        self.dk_spread_home = self.add_quote(self.game, "draftkings", MarketType.spreads, BetSide.home, -3.5, 100, captured_at)
        self.dk_spread_away = self.add_quote(self.game, "draftkings", MarketType.spreads, BetSide.away, 3.5, -120, captured_at)
        self.dk_spread_alt_home = self.add_quote(self.game, "draftkings", MarketType.spreads, BetSide.home, -4.5, 150, captured_at)
        self.dk_spread_alt_away = self.add_quote(self.game, "draftkings", MarketType.spreads, BetSide.away, 4.5, -180, captured_at)

        self.dk_total_over = self.add_quote(self.game, "draftkings", MarketType.totals, BetSide.over, 220.5, -105, captured_at)
        self.dk_total_under = self.add_quote(self.game, "draftkings", MarketType.totals, BetSide.under, 220.5, -115, captured_at)
        self.dk_total_alt_over = self.add_quote(self.game, "draftkings", MarketType.totals, BetSide.over, 221.5, 130, captured_at)
        self.dk_total_alt_under = self.add_quote(self.game, "draftkings", MarketType.totals, BetSide.under, 221.5, -160, captured_at)

        self.opening_marker = OddsSnapshotCapture(game_id=self.game.id, kind=CAPTURE_OPENING, captured_at=captured_at)
        session.add(self.opening_marker)

        self.model = None
        if register:
            self.model = ModelVersion(
                name=lms.FAMILY_NAME,
                version="1",
                role=MODEL_ROLE_SHADOW,
                params=_handmade_params(spread_intercept, total_intercept),
            )
            session.add(self.model)
        session.commit()

    def add_ingested_final(self, nba_id: str, game_date: date, season: Season, home: str, away: str,
                           home_pts: int, away_pts: int, commence: datetime, with_game_row: bool = True):
        self.session.add_all([
            PlayerGameLog(
                player_id=self.players[home].id,
                team_id=self.teams[home].id,
                season_id=season.id,
                game_id=nba_id,
                game_date=game_date,
                matchup=f"{home} vs. {away}",
                pts=home_pts,
            ),
            PlayerGameLog(
                player_id=self.players[away].id,
                team_id=self.teams[away].id,
                season_id=season.id,
                game_id=nba_id,
                game_date=game_date,
                matchup=f"{away} @ {home}",
                pts=away_pts,
            ),
        ])
        if not with_game_row:
            return None
        row = Game(
            provider_event_id=f"evt-{nba_id}",
            nba_game_id=nba_id,
            season_id=season.id,
            home_team_id=self.teams[home].id,
            away_team_id=self.teams[away].id,
            commence_time=commence,
            status="final",
            home_score=home_pts,
            away_score=away_pts,
        )
        self.session.add(row)
        self.session.flush()
        return row

    def add_quote(self, game: Game, book: str, market: MarketType, side: BetSide, line: float,
                  american: int, captured_at: datetime) -> OddsHistory:
        self._seq += 1
        row = OddsHistory(
            game_id=game.id,
            sportsbook_id=self.books[book].id,
            market=market,
            side=side,
            line=Decimal(str(line)),
            price_american=american,
            book_last_update=captured_at - timedelta(seconds=self._seq),
            captured_at=captured_at,
        )
        self.session.add(row)
        self.session.flush()
        return row


@pytest.fixture
def lm_world(db_session):
    return LineMoveWorld(db_session)


# ------------------------------------------------------------------------------------------------ 1. Ready game


def test_ready_game_writes_predictions_and_bets_at_best_price_on_pinnacle_line(lm_world, db_session):
    assert len(EloRatingService(db_session).load_games()) == 3

    summary = lms.LineMoveRecorder(db_session, now=NOW).run()

    assert summary.model == "line_move 1"
    assert summary.games_considered == 1
    assert summary.predictions_written == 2
    assert summary.bets_placed == 2

    preds = {p.market: p for p in db_session.exec(select(ModelPrediction)).all()}
    bets = {preds[b.prediction_id].market if b.prediction_id in preds else db_session.get(ModelPrediction, b.prediction_id).market: b
            for b in db_session.exec(select(SimulatedBet)).all()}
    assert set(preds) == {MarketType.spreads, MarketType.totals}
    assert set(bets) == {MarketType.spreads, MarketType.totals}

    # Spreads: intercept -0.8 -> home side at -3.5, takes DraftKings +100 (2.0000), ignores -4.5
    p_spread = preds[MarketType.spreads]
    b_spread = bets[MarketType.spreads]
    assert p_spread.side == BetSide.home
    assert p_spread.line == Decimal("-3.5")
    assert p_spread.projection == Decimal("-0.80")
    assert b_spread.strategy == StakingStrategy.line_move
    assert b_spread.stake_units == Decimal("1.000")
    assert b_spread.line_taken == Decimal("-3.5")
    assert b_spread.price_taken == Decimal("2.0000")
    assert b_spread.odds_taken_id == lm_world.dk_spread_home.id
    assert b_spread.pinnacle_price_at_bet == Decimal(f"{american_to_decimal(-110):.4f}")
    assert b_spread.predicted_move == Decimal("-0.80")
    assert b_spread.fair_prob_at_bet == Decimal("0.50000")
    assert b_spread.placed_at.replace(tzinfo=timezone.utc) == NOW

    # Totals: intercept +0.9 -> over at 220.5, takes DraftKings -105, ignores 221.5
    p_total = preds[MarketType.totals]
    b_total = bets[MarketType.totals]
    assert p_total.side == BetSide.over
    assert p_total.line == Decimal("220.5")
    assert p_total.projection == Decimal("0.90")
    assert b_total.strategy == StakingStrategy.line_move
    assert b_total.stake_units == Decimal("1.000")
    assert b_total.line_taken == Decimal("220.5")
    assert b_total.price_taken == Decimal(f"{american_to_decimal(-105):.4f}")
    assert b_total.odds_taken_id == lm_world.dk_total_over.id
    assert b_total.pinnacle_price_at_bet == Decimal(f"{american_to_decimal(-110):.4f}")
    assert b_total.predicted_move == Decimal("0.90")
    assert b_total.fair_prob_at_bet == Decimal("0.50000")
    assert b_total.placed_at.replace(tzinfo=timezone.utc) == NOW


# ------------------------------------------------------------------------------------------------ 2. Earlier game guards


def test_earlier_game_status_and_ingestion_guards(lm_world, db_session):
    earlier = Game(
        provider_event_id="evt-earlier-bos",
        season_id=lm_world.season.id,
        home_team_id=lm_world.teams["BOS"].id,
        away_team_id=lm_world.teams["NYK"].id,
        commence_time=NOW - timedelta(hours=20),  # within 3 days before G, outside upcoming window
        status="scheduled",
    )
    db_session.add(earlier)
    db_session.commit()

    # Scheduled earlier game -> previous_game_not_final
    s1 = lms.LineMoveRecorder(db_session, now=NOW).run()
    assert s1.skipped["previous_game_not_final"] == 1
    assert db_session.exec(select(ModelPrediction)).all() == []
    assert db_session.exec(select(SimulatedBet)).all() == []

    # Live earlier game -> previous_game_not_final
    earlier.status = "live"
    db_session.add(earlier)
    db_session.commit()
    s2 = lms.LineMoveRecorder(db_session, now=NOW).run()
    assert s2.skipped["previous_game_not_final"] == 1
    assert db_session.exec(select(ModelPrediction)).all() == []

    # Final earlier game not in player_game_log -> previous_game_not_ingested
    earlier.status = "final"
    earlier.nba_game_id = "0022609999"
    db_session.add(earlier)
    db_session.commit()
    s3 = lms.LineMoveRecorder(db_session, now=NOW).run()
    assert s3.skipped["previous_game_not_ingested"] == 1
    assert db_session.exec(select(ModelPrediction)).all() == []

    # Postponed earlier game does not block
    earlier.status = "postponed"
    db_session.add(earlier)
    db_session.commit()
    s4 = lms.LineMoveRecorder(db_session, now=NOW).run()
    assert s4.predictions_written == 2
    assert s4.bets_placed == 2


# ------------------------------------------------------------------------------------------------ 3. Capture before ready_at


def test_capture_before_bettable_instant_skips_until_later_capture_arrives(lm_world, db_session):
    # Move previous game tip to NOW - 5h -> final at NOW - 2h -> bettable instant ready_at = NOW - 1h30m
    lm_world.prev_game.commence_time = NOW - timedelta(hours=5)
    db_session.add(lm_world.prev_game)

    # Move all quotes and capture marker of G to NOW - 2h (before ready_at = NOW - 1h30m)
    early_capture = NOW - timedelta(hours=2)
    for q in db_session.exec(select(OddsHistory).where(OddsHistory.game_id == lm_world.game.id)).all():
        q.captured_at = early_capture
        q.book_last_update = early_capture - timedelta(minutes=1)
        db_session.add(q)
    lm_world.opening_marker.captured_at = early_capture
    db_session.add(lm_world.opening_marker)
    db_session.commit()

    s1 = lms.LineMoveRecorder(db_session, now=NOW).run()
    assert s1.skipped["no_capture_after_bettable_instant"] == 1
    assert db_session.exec(select(ModelPrediction)).all() == []
    assert db_session.exec(select(SimulatedBet)).all() == []

    # Adding a capture marker at NOW - 1h (>= ready_at) allows the decision
    db_session.add(OddsSnapshotCapture(game_id=lm_world.game.id, kind=CAPTURE_CLOSING, captured_at=NOW - timedelta(hours=1)))
    db_session.commit()

    s2 = lms.LineMoveRecorder(db_session, now=NOW).run()
    assert s2.predictions_written == 2
    assert s2.bets_placed == 2


# ------------------------------------------------------------------------------------------------ 4. Below threshold


def test_below_threshold_writes_prediction_only_and_second_run_is_already_decided(db_session):
    w = LineMoveWorld(db_session, spread_intercept=0.1, total_intercept=0.1)

    s1 = lms.LineMoveRecorder(db_session, now=NOW).run()
    assert s1.predictions_written == 2
    assert s1.bets_placed == 0
    assert s1.skipped["spreads_below_threshold"] == 1
    assert s1.skipped["totals_below_threshold"] == 1
    assert len(db_session.exec(select(ModelPrediction)).all()) == 2
    assert db_session.exec(select(SimulatedBet)).all() == []

    # Insert new Pinnacle quotes at different lines and run again
    later = NOW + timedelta(minutes=15)
    w.add_quote(w.game, "pinnacle", MarketType.spreads, BetSide.home, -4.5, -110, later)
    w.add_quote(w.game, "pinnacle", MarketType.spreads, BetSide.away, 4.5, -110, later)
    w.add_quote(w.game, "pinnacle", MarketType.totals, BetSide.over, 222.5, -110, later)
    w.add_quote(w.game, "pinnacle", MarketType.totals, BetSide.under, 222.5, -110, later)
    db_session.commit()

    s2 = lms.LineMoveRecorder(db_session, now=later + timedelta(minutes=1)).run()
    assert s2.predictions_written == 0
    assert s2.bets_placed == 0
    assert s2.skipped["already_decided"] == 1
    assert len(db_session.exec(select(ModelPrediction)).all()) == 2
    assert db_session.exec(select(SimulatedBet)).all() == []


# ------------------------------------------------------------------------------------------------ 5. Uniqueness


def test_uniqueness_across_runs_at_different_now(lm_world, db_session):
    s1 = lms.LineMoveRecorder(db_session, now=NOW).run()
    assert s1.bets_placed == 2

    later = NOW + timedelta(minutes=30)
    lm_world.add_quote(lm_world.game, "pinnacle", MarketType.spreads, BetSide.home, -4.0, -110, later)
    lm_world.add_quote(lm_world.game, "pinnacle", MarketType.spreads, BetSide.away, 4.0, -110, later)
    db_session.commit()

    s2 = lms.LineMoveRecorder(db_session, now=later + timedelta(minutes=5)).run()
    assert s2.bets_placed == 0
    assert s2.skipped["already_decided"] == 1

    bets = db_session.exec(select(SimulatedBet).where(SimulatedBet.strategy == StakingStrategy.line_move)).all()
    assert len(bets) == 2
    by_game_market = {(db_session.get(ModelPrediction, b.prediction_id).game_id,
                       db_session.get(ModelPrediction, b.prediction_id).market) for b in bets}
    assert len(by_game_market) == 2


# ------------------------------------------------------------------------------------------------ 6. Tip guard


def test_tip_guard_ignores_games_at_or_after_commence_time(lm_world, db_session):
    lm_world.game.commence_time = NOW
    db_session.add(lm_world.game)
    db_session.commit()

    s_at = lms.LineMoveRecorder(db_session, now=NOW).run()
    assert s_at.games_considered == 0
    assert db_session.exec(select(ModelPrediction)).all() == []
    assert db_session.exec(select(SimulatedBet)).all() == []

    lm_world.game.commence_time = NOW - timedelta(minutes=5)
    db_session.add(lm_world.game)
    db_session.commit()

    s_after = lms.LineMoveRecorder(db_session, now=NOW).run()
    assert s_after.games_considered == 0
    assert db_session.exec(select(ModelPrediction)).all() == []


# ------------------------------------------------------------------------------------------------ 7. Dry run


def test_dry_run_writes_nothing_and_reports_decisions(lm_world, db_session):
    summary = lms.LineMoveRecorder(db_session, now=NOW).run(dry_run=True)

    assert summary.dry_run is True
    assert summary.predictions_written == 2
    assert summary.bets_placed == 2
    assert len(summary.decisions) == 2
    assert "would write 2 decision(s)" in summary.message()
    assert db_session.exec(select(ModelPrediction)).all() == []
    assert db_session.exec(select(SimulatedBet)).all() == []


# ------------------------------------------------------------------------------------------------ 8. Not registered


def test_unregistered_model_returns_none_and_writes_nothing(db_session):
    LineMoveWorld(db_session, register=False)

    summary = lms.LineMoveRecorder(db_session, now=NOW).run()

    assert summary.model is None
    assert summary.message() == "line_move: not registered"
    assert db_session.exec(select(ModelPrediction)).all() == []
    assert db_session.exec(select(SimulatedBet)).all() == []


# ------------------------------------------------------------------------------------------------ 9. Existing strategies unchanged


def _populate_pr_world(session):
    w = PrWorld(session)
    g1 = w.game(home="AAA", away="BBB", hours=5.0, event="g1")
    w.h2h(g1, "pinnacle", -170, 145)
    w.h2h(g1, "draftkings", -140, 115)
    w.spread(g1, "pinnacle", -3.5, -110, -110)
    w.spread(g1, "fanduel", -3.5, 105, -125)
    w.total(g1, "pinnacle", 220.5, -110, -110)
    w.total(g1, "draftkings", 220.5, 105, -125)
    return w, g1


def _v1_bet_tuples(session):
    rows = []
    for b in session.exec(select(SimulatedBet).where(SimulatedBet.strategy != StakingStrategy.line_move)).all():
        pred = session.get(ModelPrediction, b.prediction_id)
        rows.append((b.strategy, pred.game_id, pred.market, pred.side, float(b.stake_units), float(b.bankroll_before)))
    return set(rows)


def test_existing_strategies_unchanged_by_settled_and_pending_line_move_bets(db_session):
    # Control world without line_move bets in an isolated in-memory engine
    ctrl_engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(ctrl_engine)
    with Session(ctrl_engine) as ctrl_session:
        w_clean, _ = _populate_pr_world(ctrl_session)
        w_clean.recorder(now=PR_NOW).run()
        expected_v1 = _v1_bet_tuples(ctrl_session)
    assert len(expected_v1) >= 4  # flat, kelly_fractional, kelly_shrunk, market_edge all active

    # Identical world on db_session plus a settled + a pending line_move bet on games inside the window
    w_with, g1 = _populate_pr_world(db_session)
    g2 = w_with.game(home="CCC", away="DDD", hours=6.0, event="g2")
    lm_model = ModelVersion(name=lms.FAMILY_NAME, version="1", role=MODEL_ROLE_SHADOW, params=_handmade_params())
    db_session.add(lm_model)
    db_session.commit()

    for game, market, side, line, status, profit in (
        (g1, MarketType.spreads, BetSide.home, Decimal("-3.5"), BetStatus.won, Decimal("25.000")),
        (g2, MarketType.totals, BetSide.over, Decimal("220.5"), BetStatus.pending, None),
    ):
        q = w_with.quote(game, "draftkings", market, side, line, 100, captured=PR_NOW - timedelta(minutes=20))
        pred = ModelPrediction(
            model_version_id=lm_model.id,
            game_id=game.id,
            market=market,
            side=side,
            line=line,
            model_prob=Decimal("0.55000"),
            projection=Decimal("-0.80"),
        )
        db_session.add(pred)
        db_session.flush()
        db_session.add(
            SimulatedBet(
                prediction_id=pred.id,
                odds_taken_id=q.id,
                price_taken=Decimal("2.0000"),
                line_taken=line,
                ev_per_unit=Decimal("0.10000"),
                strategy=StakingStrategy.line_move,
                stake_units=Decimal("3.000"),
                bankroll_before=Decimal("100.000"),
                status=status,
                profit_units=profit,
                placed_at=PR_NOW - timedelta(minutes=15),
                settled_at=PR_NOW - timedelta(minutes=5) if status != BetStatus.pending else None,
            )
        )
    db_session.commit()

    PredictionRecorder(db_session, now=PR_NOW).run()
    actual_v1 = _v1_bet_tuples(db_session)
    assert actual_v1 == expected_v1


# ------------------------------------------------------------------------------------------------ 10. Tick isolation


def test_tick_record_step_isolation_when_line_move_raises_or_unregistered(db_session, monkeypatch):
    w, _ = _populate_pr_world(db_session)
    ctx = tick.TickContext(
        session=db_session,
        service=None,
        now=PR_NOW,
        dry_run=False,
        window_minutes=30,
        props_events=0,
        min_remaining=25,
        local_tz=timezone.utc,
    )

    # Not registered -> step status "ok" and message has no "line_move"
    res_ok = tick.record_step(ctx)
    assert res_ok.status == "ok"
    assert "line_move" not in res_ok.message
    champ_preds = db_session.exec(select(ModelPrediction)).all()
    assert len(champ_preds) > 0

    # Clear predictions and monkeypatch LineMoveRecorder.run to raise -> error, message has "line_move",
    # and champion predictions remain committed after rollback
    for b in db_session.exec(select(SimulatedBet)).all():
        db_session.delete(b)
    for p in db_session.exec(select(ModelPrediction)).all():
        db_session.delete(p)
    db_session.commit()

    def boom(self, dry_run=False):
        raise RuntimeError("line_move exploded")

    monkeypatch.setattr(tick.LineMoveRecorder, "run", boom)
    res_err = tick.record_step(ctx)
    assert res_err.status == "error"
    assert "line_move" in res_err.message
    db_session.rollback()
    assert len(db_session.exec(select(ModelPrediction)).all()) == len(champ_preds)


# ------------------------------------------------------------------------------------------------ 11. Paper report


def test_paper_report_isolates_line_move_and_formats_live_test(lm_world, db_session):
    # Create a tipped-off game with a closing marker, Pinnacle closing quotes, and a flat v1 bet
    tipped = Game(
        provider_event_id="evt-tipped",
        season_id=lm_world.season.id,
        home_team_id=lm_world.teams["NYK"].id,
        away_team_id=lm_world.teams["LAL"].id,
        commence_time=NOW - timedelta(hours=4),
        status="final",
        home_score=105,
        away_score=99,
    )
    db_session.add(tipped)
    db_session.flush()

    placed_at = NOW - timedelta(hours=6)
    close_at = NOW - timedelta(hours=4, minutes=15)
    q_open = lm_world.add_quote(tipped, "pinnacle", MarketType.spreads, BetSide.home, -3.5, 100, placed_at)
    lm_world.add_quote(tipped, "pinnacle", MarketType.spreads, BetSide.home, -3.5, -110, close_at)
    lm_world.add_quote(tipped, "pinnacle", MarketType.spreads, BetSide.away, 3.5, -110, close_at)
    db_session.add(OddsSnapshotCapture(game_id=tipped.id, kind=CAPTURE_CLOSING, captured_at=close_at))

    champ = ModelVersion(name="elo_538", version="1.1", role="champion", params={"sigma": 14.0})
    db_session.add(champ)
    db_session.flush()
    v1_pred = ModelPrediction(
        model_version_id=champ.id,
        game_id=tipped.id,
        market=MarketType.spreads,
        side=BetSide.home,
        line=Decimal("-3.5"),
        model_prob=Decimal("0.55000"),
    )
    db_session.add(v1_pred)
    db_session.flush()
    db_session.add(
        SimulatedBet(
            prediction_id=v1_pred.id,
            odds_taken_id=q_open.id,
            price_taken=Decimal("2.0000"),
            line_taken=Decimal("-3.5"),
            closing_price=Decimal("1.9090"),
            closing_line=Decimal("-3.5"),
            ev_per_unit=Decimal("0.05000"),
            strategy=StakingStrategy.flat,
            stake_units=Decimal("1.000"),
            bankroll_before=Decimal("100.000"),
            status=BetStatus.won,
            profit_units=Decimal("1.000"),
            placed_at=placed_at,
            settled_at=NOW - timedelta(hours=1),
        )
    )
    db_session.commit()

    report_before = build_report(db_session, NOW)

    # Add a line_move bet + prediction on the same game
    lm_pred = ModelPrediction(
        model_version_id=lm_world.model.id,
        game_id=tipped.id,
        market=MarketType.spreads,
        side=BetSide.home,
        line=Decimal("-3.5"),
        model_prob=Decimal("0.54000"),
        projection=Decimal("-0.80"),
    )
    db_session.add(lm_pred)
    db_session.flush()
    db_session.add(
        SimulatedBet(
            prediction_id=lm_pred.id,
            odds_taken_id=q_open.id,
            price_taken=Decimal("2.0000"),
            line_taken=Decimal("-3.5"),
            ev_per_unit=Decimal("0.08000"),
            strategy=StakingStrategy.line_move,
            stake_units=Decimal("1.000"),
            bankroll_before=Decimal("100.000"),
            predicted_move=Decimal("-0.80"),
            pinnacle_price_at_bet=Decimal("2.0000"),
            status=BetStatus.won,
            profit_units=Decimal("1.000"),
            placed_at=placed_at,
            settled_at=NOW - timedelta(hours=1),
        )
    )
    db_session.commit()

    report_after = build_report(db_session, NOW)
    assert report_after.markets == report_before.markets
    assert report_after.clv == report_before.clv
    assert report_after.pinnacle_clv == report_before.pinnacle_clv
    assert report_after.line_move.bets == 1

    text = format_report(report_after)
    assert "LIVE TEST" in text
    assert "line_move (LIVE TEST)" in text

    lm_only_clv = build_pinnacle_clv_report(db_session, NOW, strategies=("line_move",))
    assert lm_only_clv.total_bets == 1
    assert lm_only_clv.games_count == 1


# ------------------------------------------------------------------------------------------------ 12. Paper API


def test_paper_summary_api_includes_line_move_live_test_flag(client, lm_world, db_session):
    lms.LineMoveRecorder(db_session, now=NOW).run()

    resp = client.get("/api/v1/paper/summary")
    assert resp.status_code == 200
    data = resp.json()

    live = data["line_move_live_test"]
    assert live is not None
    assert live["bets"] == 2
    assert "LIVE TEST" in live["label"]

    by_strat = {s["strategy"]: s["live_test"] for s in data["strategies"]}
    assert by_strat["line_move"] is True
    assert all(flag is False for strat, flag in by_strat.items() if strat != "line_move")


# ------------------------------------------------------------------------------------------------ 13. register_line_move CLI


def _load_register_cli():
    path = Path(__file__).resolve().parents[1] / "scripts" / "register_line_move.py"
    spec = importlib.util.spec_from_file_location("register_line_move_cli", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_register_line_move_cli_dry_run_register_and_duplicate_guard(db_session):
    cli = _load_register_cli()
    params = _handmade_params()
    factory = lambda: nullcontext(db_session)  # noqa: E731
    fit_fn = lambda session, args, season: params  # noqa: E731

    # --dry-run writes no model_version
    rc_dry = cli.main(["--dry-run"], session_factory=factory, fit=fit_fn)
    assert rc_dry == 0
    assert db_session.exec(select(ModelVersion)).all() == []

    # real run writes one row name="line_move", version="1", role="shadow" with those params
    rc_ok = cli.main([], session_factory=factory, fit=fit_fn)
    assert rc_ok == 0
    rows = db_session.exec(select(ModelVersion)).all()
    assert len(rows) == 1
    row = rows[0]
    assert (row.name, row.version, row.role) == ("line_move", "1", "shadow")
    assert row.params == params

    # second run returns 1 and writes nothing
    rc_dup = cli.main([], session_factory=factory, fit=fit_fn)
    assert rc_dup == 1
    assert len(db_session.exec(select(ModelVersion)).all()) == 1
