"""
The league with a champion that is NOT an Elo model, the weekly proposal, the lab baseline fallback and the CLI.

The end-to-end scenario promotes ``margin_features`` to champion and checks that everything that used to assume an Elo
champion (the recorder, the Elo updates, the results catch-up, the report, the lab baseline) keeps working, that the
new champion's predictions drive the bets (policy unchanged), that the ex-champion keeps recording as a challenger and
that bets already placed keep their original model attribution.
"""
import importlib.util
from collections import Counter
from contextlib import nullcontext
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy.engine import make_url
from sqlmodel import select

from app.analytics.features import build_feature_set
from app.models import (
    BetSide,
    BetStatus,
    Game,
    MarketType,
    ModelEvaluation,
    ModelPrediction,
    ModelVersion,
    OddsHistory,
    SimulatedBet,
    Sportsbook,
    StakingStrategy,
    TeamEloRating,
)
from app.repositories.historical import HistoricalRepository
from app.services import model_lab as lab
from app.services import model_promotion as promo
from app.services import model_registry
from app.services.elo_service import EloRatingService, update_active_models
from app.services.margin_features_model import FAMILY_NAME as MF, fit_on_feature_set
from app.services.paper_report import build_report, format_report
from app.services.prediction_recorder import PredictionRecorder
from app.services.results_sync import count_final_games_without_ratings
from tests.synthetic_league import insert_league, make_league
from tests.test_elo_backfill_service import populate_three_seasons, world  # noqa: F401
from tests.test_model_evaluation import NOW, League, simulate

UTC = timezone.utc


# ---------------------------------------------------------------------------------------------- the world

def margin_features_params():
    """Params of a real fitted margin_features model, made bullish on the home side so it always finds an edge."""
    games = make_league(n_seasons=7, n_teams=10, seed=5)
    features, _ = build_feature_set(games)
    params = fit_on_feature_set(features, features.season_rank < 5, seed=42, trained_through=games[0].game_date, seasons=["s"])
    params["logistic"]["intercept"] += 4.0
    return params


class E2E:
    def __init__(self, world):
        self.session = session = world["session"]
        self.teams, self.seasons = world["teams"], world["seasons"]
        populate_three_seasons(world)  # the rating history of ATL, BOS, BKN and NOP
        self.elo = ModelVersion(
            name="elo_538", version="1.1", role="champion", params={"sigma": 14.0}, promoted_at=NOW - timedelta(days=100)
        )
        self.mf = ModelVersion(name=MF, version="lab-e2e", role="challenger", params=margin_features_params())
        self.pinnacle = Sportsbook(key="pinnacle", name="Pinnacle", region="eu", is_sharp=True)
        self.draftkings = Sportsbook(key="draftkings", name="DraftKings", region="us", is_sharp=False)
        session.add_all([self.elo, self.mf, self.pinnacle, self.draftkings])
        session.commit()
        self.mf.parent_id = self.elo.id
        session.commit()
        EloRatingService(session, model_version_id=self.elo.id).rebuild_all()
        self._updates = 0

    def game(self, home, away, hours, status="scheduled", nba_game_id=None):
        game = Game(
            provider_event_id=f"evt-{home}-{away}-{hours}",
            nba_game_id=nba_game_id,
            season_id=self.seasons["2005-06"],
            home_team_id=self.teams[home],
            away_team_id=self.teams[away],
            commence_time=NOW + timedelta(hours=hours),
            status=status,
            home_score=100 if status == "final" else None,
            away_score=90 if status == "final" else None,
        )
        self.session.add(game)
        self.session.commit()
        return game

    def quote(self, game, book, side, price, captured=None):
        captured = captured or NOW - timedelta(minutes=10)
        self._updates += 1
        row = OddsHistory(
            game_id=game.id, sportsbook_id=book.id, market=MarketType.h2h, side=side, price_american=price,
            book_last_update=captured - timedelta(minutes=1, seconds=self._updates), captured_at=captured,
        )
        self.session.add(row)
        self.session.commit()
        return row

    def market(self, game):
        """Pinnacle -110/-110 (fair 50%) and a DraftKings home price of +120: any bullish model has an edge."""
        self.quote(game, self.pinnacle, BetSide.home, -110)
        self.quote(game, self.pinnacle, BetSide.away, -110)
        self.quote(game, self.draftkings, BetSide.home, 120)

    def earlier_bet(self, game):
        """A settled bet of the Elo champion on a game that is already final (the history that must stay put)."""
        odds = self.quote(game, self.draftkings, BetSide.home, 150, captured=NOW - timedelta(days=4))
        prediction = ModelPrediction(
            model_version_id=self.elo.id, game_id=game.id, market=MarketType.h2h, side=BetSide.home,
            model_prob=Decimal("0.60"), projection=Decimal("3.00"), predicted_at=NOW - timedelta(days=4),
        )
        self.session.add(prediction)
        self.session.commit()
        bet = SimulatedBet(
            prediction_id=prediction.id, odds_taken_id=odds.id, price_taken=Decimal("2.5"), ev_per_unit=Decimal("0.1"),
            strategy=StakingStrategy.flat, stake_units=Decimal("1"), bankroll_before=Decimal("100"),
            status=BetStatus.won, profit_units=Decimal("1.5"), placed_at=NOW - timedelta(days=4), settled_at=NOW - timedelta(days=3),
        )
        self.session.add(bet)
        self.session.commit()
        return bet

    def record(self):
        return PredictionRecorder(self.session, now=NOW).run()

    def predictions_of(self, model):
        return self.session.exec(select(ModelPrediction).where(ModelPrediction.model_version_id == model.id)).all()

    def bets_by_model(self):
        counts = Counter()
        for bet in self.session.exec(select(SimulatedBet)).all():
            counts[self.session.get(ModelPrediction, bet.prediction_id).model_version_id] += 1
        return counts


@pytest.fixture
def e2e(world):  # noqa: F811
    return E2E(world)


def test_promoting_margin_features_keeps_the_whole_pipeline_working(e2e):
    session = e2e.session
    finished = e2e.game("ATL", "BOS", -72.0, status="final", nba_game_id="0020300001")  # a game Elo has rated
    old_bet = e2e.earlier_bet(finished)
    g2 = e2e.game("ATL", "BOS", 5.0)

    # ---- before: the Elo champion and the shadow margin_features model predict; no quotes, so no bets
    before = e2e.record()
    assert before.models[e2e.elo.id].role == "champion" and before.models[e2e.mf.id].role == "challenger"
    assert len(e2e.predictions_of(e2e.mf)) == 2 and not before.bets_placed
    assert e2e.bets_by_model() == Counter({e2e.elo.id: 1})  # only the earlier bet exists

    # ---- the promotion
    e2e.market(g2)
    promo.manual_promote(session, e2e.mf.id, "end-to-end", NOW, force=True)
    session.expire_all()
    assert [m.id for m in model_registry.list_active(session)] == [e2e.mf.id, e2e.elo.id]
    assert model_registry.get_champion(session).id == e2e.mf.id

    # ---- after: a new game appears, the recorder runs under the new champion
    g3 = e2e.game("BKN", "NOP", 6.0)
    e2e.market(g3)
    after = e2e.record()

    assert after.models[e2e.mf.id].role == "champion" and after.models[e2e.elo.id].role == "challenger"
    assert after.bets_placed[StakingStrategy.flat.value] >= 1
    counts = e2e.bets_by_model()
    assert counts[e2e.elo.id] == 1 and counts[e2e.mf.id] >= 2  # the new champion bets; the ex-champion never does
    assert session.get(SimulatedBet, old_bet.id).prediction_id == old_bet.prediction_id  # attribution untouched
    assert session.get(ModelPrediction, old_bet.prediction_id).model_version_id == e2e.elo.id
    new_bets = [b for b in session.exec(select(SimulatedBet)).all() if b.id != old_bet.id]
    assert all(session.get(ModelPrediction, b.prediction_id).model_version_id == e2e.mf.id for b in new_bets)
    # the ex-champion keeps recording its own predictions, including on the game that appeared after the promotion
    assert {p.game_id for p in e2e.predictions_of(e2e.elo)} >= {g2.id, g3.id}
    assert {p.game_id for p in e2e.predictions_of(e2e.mf)} >= {g2.id, g3.id}

    # ---- everything that used to take the champion for an Elo model
    assert model_registry.get_elo_reference(session).id == e2e.elo.id
    assert EloRatingService(session).model_version_id == e2e.elo.id
    assert [row.id for row, _ in update_active_models(session)] == [e2e.elo.id]
    assert count_final_games_without_ratings(session) == 0  # counted against the Elo reference, not margin_features
    ratings = session.exec(select(TeamEloRating).where(TeamEloRating.model_version_id == e2e.mf.id)).all()
    assert ratings == []  # margin_features never gets Elo rows of its own
    team = e2e.teams["ATL"]
    season = e2e.seasons["2003-04"]
    assert HistoricalRepository(session).list_team_elo(team, season)  # the timeline is the Elo reference's

    report = build_report(session, NOW)
    assert report.skill.model == f"{MF} lab-e2e"
    assert [(m.name, m.role) for m in report.models] == [(MF, "champion"), ("elo_538", "challenger")]
    assert "margin_features lab-e2e" in format_report(report)

    # ---- the lab keeps an Elo baseline and says so
    baseline, params, note = lab.lab_baseline(session)
    assert baseline.id == e2e.elo.id and note and "margin_features lab-e2e" in note and "elo_538 1.1" in note
    assert lab.champion_elo_params(session)[0].id == e2e.elo.id


def test_the_lab_needs_some_active_elo_model_when_the_champion_is_not_one(e2e):
    promo.manual_promote(e2e.session, e2e.mf.id, "switch", NOW, force=True)
    promo.manual_retire(e2e.session, e2e.elo.id, "retire the Elo", NOW)
    with pytest.raises(lab.LabError, match="no elo_538 model is active"):
        lab.lab_baseline(e2e.session)
    # the retired Elo row is still the last-resort reference for rating queries
    assert model_registry.get_elo_reference(e2e.session).id == e2e.elo.id


def test_the_baseline_is_the_best_active_elo_model(e2e):
    session = e2e.session
    better = ModelVersion(name="elo_538", version="c-better", role="challenger", params={"sigma": 13.0}, brier_oos=Decimal("0.20000"))
    worse = ModelVersion(name="elo_538", version="c-worse", role="challenger", params={"sigma": 13.0}, brier_oos=Decimal("0.22000"))
    session.add_all([better, worse])
    session.commit()
    promo.manual_promote(session, e2e.mf.id, "switch", NOW, force=True)

    baseline, _, note = lab.lab_baseline(session)

    assert baseline.id == better.id and "c-better" in note


def test_an_elo_champion_is_its_own_lab_baseline_without_a_note(e2e):
    baseline, params, note = lab.lab_baseline(e2e.session)
    assert baseline.id == e2e.elo.id and note is None and params.k == 20.0


def test_the_elo_reference_falls_back_to_a_default_when_nothing_is_registered(db_session):
    assert model_registry.get_elo_reference(db_session) is None
    row = model_registry.ensure_elo_reference(db_session)
    assert (row.name, row.version, row.role) == ("elo_538", "1.1", "champion")
    db_session.commit()
    other = ModelVersion(name="margin_features", version="x", role="champion", params={})
    db_session.delete(row)
    db_session.commit()
    db_session.add(other)
    db_session.commit()
    created = model_registry.ensure_elo_reference(db_session)
    assert created.role == "challenger"  # the registry already has a champion: the default Elo stays a challenger


# ------------------------------------------------------------------------------------------ the proposal

@pytest.fixture
def lab_world(db_session):
    insert_league(db_session, make_league(n_seasons=9, n_teams=8, seed=4, rounds=14))
    champion = ModelVersion(name="elo_538", version="1.1", params={"sigma": 14.0}, role="champion")
    db_session.add(champion)
    db_session.commit()
    return db_session


def _count(session, model):
    return len(session.exec(select(model)).all())


def test_a_dry_run_proposal_writes_nothing(lab_world):
    outcome = promo.run_proposal(lab_world, NOW, dry_run=True, n_configs=4)

    assert outcome.evaluation_id is None and outcome.registration.dry_run
    assert _count(lab_world, ModelEvaluation) == 0 and _count(lab_world, ModelVersion) == 1
    assert "would be registered" in outcome.summary


def test_a_proposal_writes_one_audit_row_with_the_verdicts_also_when_nothing_passes(lab_world):
    outcome = promo.run_proposal(lab_world, NOW, n_configs=4, seed=7)

    (row,) = lab_world.exec(select(ModelEvaluation)).all()
    assert row.decision == "proposal" and row.id == outcome.evaluation_id and row.reason == outcome.summary
    assert row.metrics["seed"] == 7 and len(row.metrics["verdicts"]) == 2 and row.n_games == outcome.report.n_games
    assert row.metrics["registered"] == [f"{r.name} {r.version}" for r in outcome.registration.registered]
    assert promo.last_proposal(lab_world).id == row.id
    assert _count(lab_world, ModelVersion) == 1 + len(outcome.registration.registered)
    assert promo.last_evaluation(lab_world, row.challenger_id) is None  # a proposal row is not an evaluation


def test_a_proposal_without_registration_only_plans_and_records(lab_world):
    outcome = promo.run_proposal(lab_world, NOW, register=False, n_configs=4)

    assert outcome.registration.registered == [] and _count(lab_world, ModelVersion) == 1
    (row,) = lab_world.exec(select(ModelEvaluation)).all()
    assert row.metrics["registered"] == [] and "would be registered" in row.reason


def test_a_proposal_with_full_challenger_slots_records_the_refusal(lab_world):
    for index in range(3):
        lab_world.add(ModelVersion(name="elo_538", version=f"c{index}", role="challenger", params={"sigma": 13.0}))
    lab_world.commit()

    outcome = promo.run_proposal(lab_world, NOW, n_configs=4)

    assert outcome.registration.registered == [] and any("3 challengers" in s for s in outcome.registration.skipped)
    assert _count(lab_world, ModelVersion) == 4 and outcome.evaluation_id is not None


def test_a_proposal_respects_a_lower_challenger_cap(lab_world):
    lab_world.add(ModelVersion(name="elo_538", version="c0", role="challenger", params={"sigma": 13.0}))
    lab_world.commit()
    outcome = promo.run_proposal(lab_world, NOW, n_configs=4, max_challengers=1)
    assert outcome.registration.registered == [] and any("maximum 1" in s for s in outcome.registration.skipped)


def test_a_proposal_cannot_run_without_a_champion(db_session):
    with pytest.raises(lab.LabError):
        promo.run_proposal(db_session, NOW)


# --------------------------------------------------------------------------------------------- the CLI

def _load_cli():
    path = Path(__file__).resolve().parents[1] / "scripts" / "model_league.py"
    spec = importlib.util.spec_from_file_location("model_league_cli", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def cli():
    return _load_cli()


@pytest.fixture
def league(db_session):
    return League(db_session)


def run_cli(cli, session, *argv):
    return cli.main([*argv], session_factory=lambda: nullcontext(session))


def test_status_prints_the_league_and_the_role_changes(cli, league, capsys):
    assert run_cli(cli, league.session, "status") == 0
    out = capsys.readouterr().out
    assert "Model league" in out and "champion" in out and "lab-x" in out and "No promotion, rollback or retirement yet" in out


def test_evaluate_defaults_to_a_dry_run_and_apply_promotes(cli, league, capsys):
    win, margin, mu_champion, mu_challenger = simulate(400, 21, 7.0, 1.0)
    league.populate(win, margin, mu_champion, mu_challenger, days=40)
    now = ["--now", NOW.isoformat()]

    assert run_cli(cli, league.session, "evaluate", *now) == 0
    assert "dry run (nothing written)" in capsys.readouterr().out and _count(league.session, ModelEvaluation) == 0

    assert run_cli(cli, league.session, "evaluate", "--apply", *now) == 0
    out = capsys.readouterr().out
    assert "promoted" in out and "applied" in out
    league.session.expire_all()
    assert model_registry.get_champion(league.session).id == league.challenger.id

    assert run_cli(cli, league.session, "status", *now) == 0
    status = capsys.readouterr().out
    assert "promote" in status and "Promotion and retirement history" in status


def test_manual_promote_and_retire_through_the_cli(cli, league, capsys):
    other = ModelVersion(name="elo_538", version="spare", role="challenger", params={"sigma": 12.0})
    league.session.add(other)
    league.session.commit()

    assert run_cli(cli, league.session, "retire", str(other.id), "--reason", "spare", "--now", NOW.isoformat()) == 0
    assert run_cli(cli, league.session, "promote", str(league.challenger.id), "--reason", "operator", "--now", NOW.isoformat()) == 0
    out = capsys.readouterr().out
    assert "retired" in out and "is now the champion" in out
    rows = league.session.exec(select(ModelEvaluation).order_by(ModelEvaluation.id)).all()
    assert [r.reason for r in rows] == ["manual: spare", "manual: operator"]
    league.session.expire_all()
    assert model_registry.get_champion(league.session).id == league.challenger.id

    # promoting the champion again is refused (exit code 2) and writes nothing
    assert run_cli(cli, league.session, "promote", str(league.challenger.id), "--reason", "again", "--force") == 2
    assert "already the champion" in capsys.readouterr().err and _count(league.session, ModelEvaluation) == 2


def test_the_cli_requires_the_database_name_before_writing_outside_sqlite(cli, capsys):
    postgres = SimpleNamespace(get_bind=lambda: SimpleNamespace(url=make_url("postgresql+psycopg://u:p@localhost:5432/nba_platform")))
    for argv in (("evaluate", "--apply"), ("promote", "1", "--reason", "x"), ("retire", "1", "--reason", "x"), ("propose",)):
        assert run_cli(cli, postgres, *argv) == 2
        assert "--confirm-database nba_platform" in capsys.readouterr().err


def test_the_cli_propose_dry_run_reports_without_writing(cli, lab_world, capsys):
    assert run_cli(cli, lab_world, "propose", "--dry-run", "--configs", "4", "--now", NOW.isoformat()) == 0
    out = capsys.readouterr().out
    assert "Proposal (dry run)" in out and "hold-out gain" in out
    assert _count(lab_world, ModelEvaluation) == 0 and _count(lab_world, ModelVersion) == 1


def test_the_cli_propose_reports_a_lab_that_cannot_run(cli, db_session, capsys):
    db_session.add(ModelVersion(name="elo_538", version="1.1", role="champion", params={"sigma": 14.0}))
    db_session.commit()
    assert run_cli(cli, db_session, "propose", "--dry-run") == 1
    assert "the lab cannot run" in capsys.readouterr().err
