"""The ``learn`` tick step: ordering, isolation, the time budget, the weekly cadence, dry run and the kill switch."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlmodel import select

from app.config import settings
from app.models import ModelEvaluation, ModelVersion
from app.services import model_promotion, model_registry, tick
from app.services.prediction_recorder import RecorderSummary
from tests.test_model_evaluation import NOW, League, simulate
from tests.test_model_league_e2e import lab_world  # noqa: F401

UTC = timezone.utc


class Clock:
    """A clock the test moves by hand (seconds)."""

    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now


def make_ctx(session, *, dry_run=False, clock=None, budget=tick.LEARN_BUDGET_SECONDS, now=NOW):
    return tick.TickContext(session, None, now, dry_run, 30, 1, 25, UTC, None, clock or Clock(), budget)


@pytest.fixture
def league(db_session):
    return League(db_session)


@pytest.fixture
def better(league):
    win, margin, mu_champion, mu_challenger = simulate(400, 21, 7.0, 1.0)
    league.populate(win, margin, mu_champion, mu_challenger, days=40)
    return league


@pytest.fixture
def spy(monkeypatch):
    """Replaces the weekly proposal by a recorder of its calls (the lab itself is tested elsewhere)."""
    calls = []

    def fake(session, now, **kwargs):
        calls.append(kwargs)
        raise model_promotion.model_lab.LabError("spy")

    monkeypatch.setattr(model_promotion, "run_proposal", fake)
    return calls


def audit(session):
    return session.exec(select(ModelEvaluation).order_by(ModelEvaluation.id)).all()


def proposal_row(session, model, days_ago):
    session.add(
        ModelEvaluation(
            evaluated_at=NOW - timedelta(days=days_ago), champion_id=model.id, challenger_id=model.id, n_games=1,
            metrics={}, decision="proposal", reason="earlier proposal",
        )
    )
    session.commit()


# ------------------------------------------------------------------------------------------------ order

def test_learn_sits_between_results_and_record():
    assert [name for name, _ in tick.DEFAULT_STEPS] == ["opening", "closing", "results", "learn", "record"]
    assert [name for name, _ in tick.default_steps(skip=["learn"])] == ["opening", "closing", "results", "record"]


def test_a_promotion_takes_effect_for_the_predictions_of_the_same_tick(better, monkeypatch, tmp_path, spy):
    seen = []

    class SpyRecorder:
        def __init__(self, session, now=None, **kwargs):
            self.session = session

        def run(self, dry_run=False):
            seen.append(model_registry.get_champion(self.session).id)
            return RecorderSummary(now=NOW)

    monkeypatch.setattr(tick, "PredictionRecorder", SpyRecorder)
    steps = tick.default_steps(skip=["opening", "closing", "results"])

    summary = tick.run_tick(better.session, None, NOW, steps=steps, lock_path=tmp_path / "tick.lock", local_tz=UTC)

    assert [s.name for s in summary.steps] == ["learn", "record"]
    assert summary.steps[0].status == "ok" and "promoted" in summary.steps[0].message
    assert seen == [better.challenger.id]  # record saw the new champion


# -------------------------------------------------------------------------------------------- isolation

def test_a_learn_failure_never_blocks_the_recorder(better, monkeypatch, tmp_path):
    order = []

    class SpyRecorder:
        def __init__(self, session, now=None, **kwargs):
            pass

        def run(self, dry_run=False):
            order.append("record")
            return RecorderSummary(now=NOW)

    def boom(*args, **kwargs):
        raise RuntimeError("evaluation exploded")

    monkeypatch.setattr(tick, "PredictionRecorder", SpyRecorder)
    monkeypatch.setattr(model_promotion, "run_evaluation_pass", boom)
    monkeypatch.setattr(model_promotion, "last_proposal", boom)

    summary = tick.run_tick(
        better.session, None, NOW, steps=tick.default_steps(skip=["opening", "closing", "results"]),
        lock_path=tmp_path / "tick.lock",
    )

    assert {s.name: s.status for s in summary.steps} == {"learn": "error", "record": "ok"}
    assert order == ["record"] and summary.exit_code == 1
    assert "evaluation exploded" in summary.steps[0].detail


def test_the_two_stages_are_isolated_from_each_other(better, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("lab exploded")

    monkeypatch.setattr(model_promotion, "run_proposal", boom)

    result = tick.learn_step(make_ctx(better.session))

    assert result.status == "error" and "lab exploded" in result.detail
    assert "promoted" in result.message  # the evaluation stage still did its work
    better.session.expire_all()
    assert model_registry.get_champion(better.session).id == better.challenger.id


def test_a_lab_that_cannot_run_yet_is_a_note_not_an_error(better, spy):
    result = tick.learn_step(make_ctx(better.session))
    assert result.status == "ok" and "the candidate lab cannot run yet: spy" in result.message
    assert audit(better.session)[-1].decision == "promote"  # and no proposal marker, so the next tick retries


def test_with_nothing_to_do_the_step_is_skipped(league, spy):
    proposal_row(league.session, league.champion, days_ago=1)
    result = tick.learn_step(make_ctx(league.session))
    assert result.status == "skipped" and "proposal not due" in result.message
    assert spy == []


# ------------------------------------------------------------------------------------ the time budget

def test_the_lab_gets_a_deadline_that_leaves_a_reserve_inside_the_budget(league, spy):
    clock = Clock(1000.0)

    tick.learn_step(make_ctx(league.session, clock=clock, budget=240.0))

    (call,) = spy
    assert call["deadline"] == 1000.0 + 240.0 - tick.LEARN_PROPOSAL_RESERVE_SECONDS
    assert call["clock"] is clock
    assert call["register"] is True and call["max_challengers"] == 3 and call["confirm_database"] is None
    assert call["seed"] == int(NOW.strftime("%G%V"))


def test_a_proposal_is_postponed_without_a_marker_when_the_budget_is_nearly_spent(league, spy, monkeypatch):
    clock = Clock(1000.0)
    original = model_promotion.run_evaluation_pass

    def slow_pass(*args, **kwargs):
        outcome = original(*args, **kwargs)
        clock.now += 200.0  # the evaluation ate most of the 240 s
        return outcome

    monkeypatch.setattr(model_promotion, "run_evaluation_pass", slow_pass)

    result = tick.learn_step(make_ctx(league.session, clock=clock, budget=240.0))

    assert spy == []
    assert "proposal postponed: 40s of the learn budget left" in result.message
    assert [r for r in audit(league.session) if r.decision == "proposal"] == []


def test_a_custom_budget_is_honoured(league, spy):
    tick.learn_step(make_ctx(league.session, budget=30.0))  # below the minimum a proposal needs
    assert spy == []
    tick.learn_step(make_ctx(league.session, budget=400.0))
    assert spy[0]["deadline"] == 1000.0 + 400.0 - tick.LEARN_PROPOSAL_RESERVE_SECONDS


# ------------------------------------------------------------------------------------------- cadence

def test_the_proposal_runs_at_most_once_per_cadence(league, spy):
    proposal_row(league.session, league.champion, days_ago=3)
    assert "proposal not due (last one 3.0 day(s) ago)" in tick.learn_step(make_ctx(league.session)).message
    assert spy == []

    proposal_row(league.session, league.champion, days_ago=8)  # the newest row decides, not the oldest
    tick.learn_step(make_ctx(league.session))
    assert spy == []

    league.session.execute(ModelEvaluation.__table__.delete())
    league.session.commit()
    proposal_row(league.session, league.champion, days_ago=8)
    tick.learn_step(make_ctx(league.session))
    assert len(spy) == 1


def test_the_cadence_follows_the_setting(league, spy, monkeypatch):
    proposal_row(league.session, league.champion, days_ago=3)
    monkeypatch.setattr(settings, "LEARNING_PROPOSAL_DAYS", 2)
    tick.learn_step(make_ctx(league.session))
    assert len(spy) == 1


def test_the_first_ever_tick_proposes(league, spy):
    tick.learn_step(make_ctx(league.session))
    assert len(spy) == 1


# ---------------------------------------------------------------------------------- dry run / kill switch

def test_a_dry_run_reports_and_writes_nothing(better, spy):
    result = tick.learn_step(make_ctx(better.session, dry_run=True))

    assert result.status == "ok"
    assert "would evaluate 1 challenger(s), 1 with new paired games" in result.message
    assert "would run the candidate lab" in result.message
    assert audit(better.session) == [] and spy == []
    better.session.expire_all()
    assert model_registry.get_champion(better.session).id == better.champion.id
    assert not better.session.new and not better.session.dirty


def test_with_autopromote_off_the_step_records_but_changes_and_registers_nothing(better, spy, monkeypatch):
    monkeypatch.setattr(settings, "LEARNING_AUTOPROMOTE", False)

    result = tick.learn_step(make_ctx(better.session))

    better.session.expire_all()
    assert model_registry.get_champion(better.session).id == better.champion.id
    assert [r.decision for r in audit(better.session)] == ["dry_run"]
    assert spy[0]["register"] is False
    assert result.status == "ok"


# ---------------------------------------------------------------------------------- the real proposal

def test_the_real_proposal_runs_once_and_holds_the_weekly_cadence(lab_world):  # noqa: F811
    first = tick.learn_step(make_ctx(lab_world))

    assert first.status == "ok" and "proposal:" in first.message and "candidate(s) evaluated" in first.message
    rows = [r for r in lab_world.exec(select(ModelEvaluation)).all() if r.decision == "proposal"]
    assert len(rows) == 1 and rows[0].metrics["seed"] == int(NOW.strftime("%G%V"))
    registered = len(lab_world.exec(select(ModelVersion)).all()) - 1
    assert rows[0].metrics["registered"].__len__() == registered

    again = tick.learn_step(make_ctx(lab_world, now=NOW + timedelta(hours=1)))
    assert again.status == "skipped" and "proposal not due" in again.message
    assert len([r for r in lab_world.exec(select(ModelEvaluation)).all() if r.decision == "proposal"]) == 1
