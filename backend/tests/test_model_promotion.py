"""Promotion engine: passes, atomic swaps, retirements, rollbacks, audit rows and the manual overrides."""
import json
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest
from sqlmodel import select

from app.models import ModelEvaluation, ModelVersion
from app.services import model_evaluation as ev
from app.services import model_promotion as promo
from tests.test_model_evaluation import NOW, SIGMA, League, _p_from_mu, simulate

UTC = timezone.utc
CONFIG = ev.EvaluationConfig(resamples=500, decision_resamples=500)


@pytest.fixture
def league(db_session):
    return League(db_session)


def run_pass(league, now=NOW, **kwargs):
    kwargs.setdefault("config", CONFIG)
    kwargs.setdefault("autopromote", True)
    kwargs.setdefault("local_tz", UTC)
    return promo.run_evaluation_pass(league.session, now, **kwargs)


def champions(session):
    return session.exec(select(ModelVersion).where(ModelVersion.role == "champion")).all()


def audit(session):
    return session.exec(select(ModelEvaluation).order_by(ModelEvaluation.id)).all()


def add_model(league, version, mus, role="challenger", **fields):
    """A model that predicted every existing game with the given expected margins."""
    model = ModelVersion(name="elo_538", version=version, role=role, params={"sigma": SIGMA}, **fields)
    league.session.add(model)
    league.session.commit()
    predict_all(league, model, mus)
    return model


def predict_all(league, model, mus):
    for game, mu in zip(league.games, mus):
        league.predict(model, game, _p_from_mu(mu), mu)


def better_league(league, n=400, days=40, seed=21):
    win, margin, mu_champion, mu_challenger = simulate(n, seed, 7.0, 1.0)
    league.populate(win, margin, mu_champion, mu_challenger, days)
    return win, margin, mu_champion, mu_challenger


# ------------------------------------------------------------------------------------------- promotion

def test_a_pass_promotes_a_clearly_better_challenger_and_writes_the_audit_row(league):
    better_league(league)
    session = league.session
    old_id, new_id = league.champion.id, league.challenger.id

    outcome = run_pass(league)

    (entry,) = outcome.entries
    assert entry.action == promo.ACTION_PROMOTED and outcome.promoted == [entry]
    session.expire_all()
    (champion,) = champions(session)
    assert champion.id == new_id
    old = session.get(ModelVersion, old_id)
    assert old.role == "challenger" and old.retired_at is None  # the ex-champion stays on watch
    assert champion.promoted_at is not None and champion.parent_id == old_id
    promotion = json.loads(champion.notes)["promotion"]
    assert promotion["decision"] == "promote" and promotion["champion_id"] == old_id

    (row,) = audit(session)
    assert (row.decision, row.champion_id, row.challenger_id, row.n_games) == ("promote", old_id, new_id, 400)
    assert promotion["evaluation_id"] == row.id
    assert row.metrics["seed"] == ev.SEED and row.metrics["k"] == 1 and row.metrics["applied"] is True
    assert row.metrics["thresholds"]["min_games"] == 150 and row.metrics["log_loss_gain"]["bound_low"] > 0
    assert row.metrics["challenger"]["log_loss"] < row.metrics["champion"]["log_loss"]
    assert row.reason.startswith("log-loss gain")


def test_the_notes_of_a_lab_candidate_are_extended_not_overwritten(league):
    better_league(league)
    league.challenger.notes = json.dumps({"source": "model_lab", "seed": 42})
    league.session.commit()

    run_pass(league)

    league.session.expire_all()
    notes = json.loads(league.session.get(ModelVersion, league.challenger.id).notes)
    assert notes["source"] == "model_lab" and notes["promotion"]["decision"] == "promote"


def test_at_most_one_promotion_per_pass_and_the_best_evidence_wins(league):
    win, margin, mu_champion, mu_challenger = better_league(league)
    session = league.session
    # a second challenger that is also better than the champion, but less so than the first
    rng = np.random.default_rng(3)
    second = add_model(league, "lab-2", [m + rng.normal(0, 0.1) for m in mu_challenger * 0.0 + (mu_champion + mu_challenger) / 2])
    first_id = league.challenger.id

    outcome = run_pass(league)

    assert [e.action for e in outcome.entries].count(promo.ACTION_PROMOTED) == 1
    qualified = [e for e in outcome.entries if e.result.decision == "promote"]
    assert {e.model_id for e in qualified} == {first_id, second.id}  # both pass the gate
    best = max(qualified, key=lambda e: e.result.log_loss_gain.bound_low)  # the rule: the largest lower bound wins
    session.expire_all()
    (champion,) = champions(session)
    assert champion.id == best.model_id
    loser = next(e for e in outcome.entries if e.model_id != best.model_id)
    assert loser.action == promo.ACTION_RECORDED and loser.decision == "keep"
    assert "another challenger" in loser.note
    assert sorted(r.decision for r in audit(session)) == ["keep", "promote"]
    assert session.get(ModelVersion, loser.model_id).role == "challenger"


def test_a_failure_in_the_middle_of_a_swap_leaves_exactly_the_old_champion(league, monkeypatch):
    better_league(league)
    session = league.session
    old_id, new_id = league.champion.id, league.challenger.id

    def explode(*args, **kwargs):
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(promo, "_promote_row", explode)  # runs after the old champion was demoted and flushed

    outcome = run_pass(league)

    (entry,) = outcome.entries
    assert entry.action == promo.ACTION_FAILED and "disk on fire" in entry.note
    session.expire_all()
    (champion,) = champions(session)
    assert champion.id == old_id and session.get(ModelVersion, new_id).role == "challenger"
    (row,) = audit(session)  # the audit row of the failed promotion rolled back with it; the failure is recorded
    assert row.decision == "keep" and "failed and was rolled back" in row.reason and row.metrics["failed"] is True
    assert session.get(ModelVersion, old_id).promoted_at is not None  # untouched


def test_the_single_champion_index_makes_a_double_champion_impossible(league):
    session = league.session
    league.challenger.role = "champion"
    with pytest.raises(Exception):
        session.commit()
    session.rollback()


def test_a_cooldown_blocks_promotion_and_is_recorded_as_keep(league):
    better_league(league)
    league.champion.promoted_at = NOW - timedelta(days=10)
    league.session.commit()

    run_pass(league)

    league.session.expire_all()
    assert champions(league.session)[0].id == league.champion.id
    (row,) = audit(league.session)
    assert row.decision == "keep" and "cooldown until" in row.reason


def test_nothing_is_promoted_below_the_sample_gates(league):
    win, margin, mu_champion, mu_challenger = simulate(120, 21, 7.0, 1.0)
    league.populate(win, margin, mu_champion, mu_challenger, days=20)

    run_pass(league)

    league.session.expire_all()
    assert champions(league.session)[0].id == league.champion.id
    (row,) = audit(league.session)
    assert row.decision == "insufficient_data" and row.n_games == 120


# ---------------------------------------------------------------------------------- retire and rollback

def test_a_significantly_worse_challenger_is_retired(league):
    win, margin, mu_champion, mu_challenger = simulate(130, 8, 1.0, 25.0)
    league.populate(win, margin, mu_champion, mu_challenger, days=20)

    outcome = run_pass(league)

    assert outcome.retired and outcome.entries[0].action == promo.ACTION_RETIRED
    league.session.expire_all()
    challenger = league.session.get(ModelVersion, league.challenger.id)
    assert challenger.role == "retired" and challenger.retired_at is not None
    assert json.loads(challenger.notes)["retirement"]["decision"] == "retire"
    assert champions(league.session)[0].id == league.champion.id
    (row,) = audit(league.session)
    assert row.decision == "retire" and "significantly worse" in row.reason
    # a retired model is no longer evaluated
    assert run_pass(league, now=NOW + timedelta(days=1)).entries == []


def test_the_previous_champion_returns_through_a_rollback(league):
    better_league(league)
    session = league.session
    # the "challenger" is the ex-champion of the current champion and is clearly better: it must pass the same gate
    league.champion.parent_id = league.challenger.id
    league.champion.promoted_at = NOW - timedelta(days=45)
    session.commit()
    old_id, back_id = league.champion.id, league.challenger.id

    outcome = run_pass(league)

    (entry,) = outcome.entries
    assert entry.action == promo.ACTION_ROLLED_BACK
    session.expire_all()
    (champion,) = champions(session)
    assert champion.id == back_id and champion.parent_id == old_id
    (row,) = audit(session)
    assert row.decision == "rollback" and row.metrics["previous_champion"] is True


def test_a_rollback_candidate_faces_the_same_cooldown(league):
    better_league(league)
    league.champion.parent_id = league.challenger.id
    league.champion.promoted_at = NOW - timedelta(days=45)
    league.session.commit()

    run_pass(league, config=ev.EvaluationConfig(resamples=500, decision_resamples=500, cooldown_days=60))  # 45 days since the promotion < 60

    league.session.expire_all()
    assert champions(league.session)[0].id == league.champion.id
    (row,) = audit(league.session)
    assert row.decision == "keep" and "cooldown until" in row.reason


def test_the_ex_champion_is_judged_on_games_since_its_demotion_and_is_not_retired_the_next_day(league):
    better_league(league)
    session = league.session
    old_id = league.champion.id
    run_pass(league)  # promotes the challenger; the ex-champion is far worse on the games that dethroned it
    session.expire_all()
    assert champions(session)[0].id == league.challenger.id

    next_day = run_pass(league, now=NOW + timedelta(days=1))

    (entry,) = next_day.entries
    assert entry.model_id == old_id and entry.action == promo.ACTION_SKIPPED
    assert "no new paired games" in entry.note  # nothing since the demotion yet: the old evidence does not count
    assert session.get(ModelVersion, old_id).role == "challenger"

    # fresh games after the demotion where the ex-champion is clearly worse: now it is retired
    win, margin, mu_a, mu_b = simulate(130, 99, 14.0, 1.0)  # a = ex-champion (worse), b = new champion
    for i in range(130):
        game = league.game(-(30.0 + i), home_score=110 if win[i] else 100, away_score=100 if win[i] else 110)
        league.predict(session.get(ModelVersion, old_id), game, _p_from_mu(mu_a[i]), mu_a[i], at=NOW)
        league.predict(session.get(ModelVersion, league.challenger.id), game, _p_from_mu(mu_b[i]), mu_b[i], at=NOW)
    later = run_pass(league, now=NOW + timedelta(days=200))
    assert [e.action for e in later.entries] == [promo.ACTION_RETIRED]
    assert later.entries[0].result.evidence_since is not None and later.entries[0].result.n_games == 130


# ----------------------------------------------------------------------------------- kill switch / dry

def test_with_autopromote_off_the_decision_is_recorded_and_nothing_changes(league):
    better_league(league)

    outcome = run_pass(league, autopromote=False)

    league.session.expire_all()
    assert champions(league.session)[0].id == league.champion.id
    assert league.session.get(ModelVersion, league.challenger.id).role == "challenger"
    (row,) = audit(league.session)
    assert row.decision == "dry_run" and row.reason == "autopromote disabled (would promote)"
    assert row.metrics["proposed_decision"] == "promote" and row.metrics["applied"] is False
    assert outcome.entries[0].action == promo.ACTION_RECORDED and not outcome.autopromote


def test_with_autopromote_off_a_retirement_is_not_applied_either(league):
    win, margin, mu_champion, mu_challenger = simulate(130, 8, 1.0, 25.0)
    league.populate(win, margin, mu_champion, mu_challenger, days=20)

    run_pass(league, autopromote=False)

    league.session.expire_all()
    assert league.session.get(ModelVersion, league.challenger.id).role == "challenger"
    assert audit(league.session)[0].reason == "autopromote disabled (would retire)"


def test_the_kill_switch_defaults_to_the_setting(league, monkeypatch):
    better_league(league)
    from app.config import settings

    monkeypatch.setattr(settings, "LEARNING_AUTOPROMOTE", False)
    run_pass(league, autopromote=None)
    league.session.expire_all()
    assert champions(league.session)[0].id == league.champion.id
    assert audit(league.session)[0].decision == "dry_run"


def test_a_preview_pass_writes_nothing_at_all(league):
    better_league(league)

    outcome = run_pass(league, apply=False)

    assert outcome.entries[0].action == promo.ACTION_PREVIEW and outcome.entries[0].result.decision == "promote"
    assert audit(league.session) == []
    league.session.expire_all()
    assert champions(league.session)[0].id == league.champion.id
    assert "would promote" in promo.format_pass(outcome)


# ----------------------------------------------------------------------------------- audit row cadence

def test_a_row_is_written_only_for_new_paired_games_and_once_per_local_day(league):
    session = league.session
    win, margin, mu_champion, mu_challenger = simulate(60, 5, 6.0, 5.0)
    league.populate(win, margin, mu_champion, mu_challenger, days=20)
    morning = datetime(2026, 12, 1, 9, 0, tzinfo=UTC)

    first = run_pass(league, now=morning)
    assert first.rows_written == 1 and len(audit(session)) == 1

    again = run_pass(league, now=morning + timedelta(hours=1))
    assert again.entries[0].action == promo.ACTION_SKIPPED and "no new paired games" in again.entries[0].note
    assert len(audit(session)) == 1

    for index in range(10):  # new evidence arrives
        game = league.game(1 + index)
        league.predict(league.champion, game, 0.6, 3.0)
        league.predict(league.challenger, game, 0.6, 3.0)
    same_day = run_pass(league, now=morning + timedelta(hours=3))
    assert same_day.entries[0].action == promo.ACTION_SKIPPED and "already evaluated today" in same_day.entries[0].note
    assert len(audit(session)) == 1

    next_day = run_pass(league, now=morning + timedelta(days=1))
    assert next_day.rows_written == 1 and len(audit(session)) == 2
    assert [r.n_games for r in audit(session)] == [60, 70]


def test_a_new_champion_means_a_fresh_evaluation_even_without_new_games(league):
    session = league.session
    win, margin, mu_champion, mu_challenger = simulate(60, 5, 6.0, 5.0)
    league.populate(win, margin, mu_champion, mu_challenger, days=20)
    bystander = add_model(league, "lab-3", mu_challenger)
    first = run_pass(league, now=datetime(2026, 12, 1, 9, 0, tzinfo=UTC))
    assert first.rows_written == 2

    promo.manual_promote(session, league.challenger.id, "swap for the test", NOW, force=True)
    outcome = run_pass(league, now=NOW + timedelta(days=2))

    by_model = {e.model_id: e for e in outcome.entries}
    # the bystander's last row compared it with the old champion: it is evaluated again against the new one
    assert by_model[bystander.id].action == promo.ACTION_RECORDED
    # the ex-champion has no game since its demotion
    assert by_model[league.champion.id].action == promo.ACTION_SKIPPED


def test_with_no_champion_or_no_challengers_a_pass_is_a_harmless_no_op(db_session):
    outcome = promo.run_evaluation_pass(db_session, NOW, autopromote=True)
    assert outcome.entries == [] and "no champion" in outcome.message
    db_session.add(ModelVersion(name="elo_538", version="1.1", role="champion", params={"sigma": SIGMA}))
    db_session.commit()
    outcome = promo.run_evaluation_pass(db_session, NOW, autopromote=True)
    assert outcome.entries == [] and "no active challengers" in promo.format_pass(outcome)


# ------------------------------------------------------------------------------------------- manual

def test_a_manual_promotion_swaps_atomically_and_always_writes_an_audit_row(league):
    session = league.session
    old_id, new_id = league.champion.id, league.challenger.id
    league.champion.promoted_at = NOW - timedelta(days=3)  # inside the cooldown
    session.commit()

    with pytest.raises(promo.ManualOverrideRefused, match="cooldown"):
        promo.manual_promote(session, new_id, "because", NOW)
    assert audit(session) == [] and champions(session)[0].id == old_id

    row = promo.manual_promote(session, new_id, "operator decision", NOW, force=True)

    session.expire_all()
    (champion,) = champions(session)
    assert champion.id == new_id and champion.parent_id == old_id and session.get(ModelVersion, old_id).role == "challenger"
    assert (row.decision, row.reason) == ("promote", "manual: operator decision")
    assert (row.champion_id, row.challenger_id) == (old_id, new_id)
    assert row.metrics["manual"] is True and row.metrics["force"] is True and row.metrics["previous_champion_id"] == old_id
    assert promo.last_evaluation(session, new_id) is None  # a manual row is not an evaluation


def test_manual_promotion_refuses_the_champion_a_retired_model_and_a_missing_reason(league):
    session = league.session
    retired = ModelVersion(name="elo_538", version="old", role="retired", params={"sigma": SIGMA})
    session.add(retired)
    session.commit()
    with pytest.raises(promo.ManualOverrideRefused, match="already the champion"):
        promo.manual_promote(session, league.champion.id, "x", NOW, force=True)
    with pytest.raises(promo.ManualOverrideRefused, match="retired"):
        promo.manual_promote(session, retired.id, "x", NOW)
    with pytest.raises(promo.ManualOverrideRefused, match="reason"):
        promo.manual_promote(session, league.challenger.id, "  ", NOW)
    with pytest.raises(promo.ManualOverrideRefused, match="does not exist"):
        promo.manual_promote(session, 999, "x", NOW)
    assert audit(session) == [] and len(champions(session)) == 1

    promo.manual_promote(session, retired.id, "bring it back", NOW, force=True)  # --force lifts the retirement
    session.expire_all()
    (champion,) = champions(session)
    assert champion.id == retired.id and champion.retired_at is None


def test_manual_retirement_never_retires_the_champion(league):
    session = league.session
    with pytest.raises(promo.ManualOverrideRefused, match="champion"):
        promo.manual_retire(session, league.champion.id, "x", NOW)
    row = promo.manual_retire(session, league.challenger.id, "not worth the compute", NOW)
    session.expire_all()
    challenger = session.get(ModelVersion, league.challenger.id)
    assert challenger.role == "retired" and challenger.retired_at is not None
    assert (row.decision, row.reason) == ("retire", "manual: not worth the compute")
    with pytest.raises(promo.ManualOverrideRefused, match="already retired"):
        promo.manual_retire(session, league.challenger.id, "again", NOW)
    assert len(champions(session)) == 1


def test_a_failing_manual_swap_rolls_back_completely(league, monkeypatch):
    session = league.session
    monkeypatch.setattr(promo, "_promote_row", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError):
        promo.manual_promote(session, league.challenger.id, "x", NOW, force=True)
    session.expire_all()
    assert [c.id for c in champions(session)] == [league.champion.id] and audit(session) == []


# --------------------------------------------------------------------------------------- the league view

def test_the_league_rows_and_role_changes_describe_the_registry(league):
    better_league(league, n=200)
    promo.manual_promote(league.session, league.challenger.id, "swap", NOW, force=True)

    rows = promo.league_rows(league.session)

    assert [r.role for r in rows] == ["champion", "challenger"]
    assert rows[0].model_id == league.challenger.id and rows[0].predictions == 200 and rows[0].final_games == 200
    assert promo.league_rows(league.session)[1].last_decision is None
    assert [c.decision for c in promo.role_changes(league.session)] == ["promote"]


# ------------------------------------------------------------------------------------------ look budget

def equal_league(league, n=120, days=20, seed=5):
    """Both models predict identically: no gain, no loss, so only the look rules decide what a row is."""
    win, margin, mu_champion, _ = simulate(n, seed, 5.0, 5.0)
    league.populate(win, margin, mu_champion, mu_champion, days)


def add_equal_games(league, count, start_hours):
    """New final games (after the existing ones) that both models predicted identically before tip-off."""
    for i in range(count):
        game = league.game(-(start_hours + i))
        league.predict(league.champion, game, 0.6, 3.0)
        league.predict(league.challenger, game, 0.6, 3.0)


def test_the_engine_spends_a_look_at_most_once_a_week_and_never_beyond_the_budget(league):
    equal_league(league)
    config = ev.EvaluationConfig(resamples=300, decision_resamples=300, max_looks=2)
    session = league.session
    steps = [(0, "look"), (1, "monitor"), (7, "look"), (8, "monitor"), (14, "spent")]
    for index, (day, kind) in enumerate(steps):
        if index:
            add_equal_games(league, 6, 24.0 * day)
        run_pass(league, now=NOW + timedelta(days=day), config=config)
        row = audit(session)[-1]
        if kind == "look":
            assert row.metrics["decision_grade"] is True and row.metrics["look_spent"] is True
            assert not row.reason.startswith("monitor:")
        else:
            assert row.metrics["decision_grade"] is False and row.metrics["look_spent"] is False
            assert row.decision in ("keep", "insufficient_data") and row.reason.startswith("monitor:")

    rows = audit(session)
    assert [r.metrics["look_number"] for r in rows] == [1, 1, 2, 2, 2]  # a monitor row carries the looks already spent
    assert [r.metrics["look_spent"] for r in rows] == [True, False, True, False, False]
    assert all(r.metrics["look_budget"] == 2 for r in rows)
    assert rows[0].metrics["confidence"] == pytest.approx(1 - 0.05 / (1 * 2))
    assert "spent (2 of 2)" in rows[-1].reason
    assert ev.look_history(session, league.champion, league.challenger.id)[0] == 2


def test_a_monitoring_row_cannot_promote_even_a_clearly_better_challenger(league):
    better_league(league)
    session = league.session
    session.add(  # a look was spent yesterday: today is inside the week
        ModelEvaluation(
            evaluated_at=NOW - timedelta(days=1), champion_id=league.champion.id, challenger_id=league.challenger.id,
            n_games=10, metrics={"look_spent": True}, decision="keep", reason="earlier look",
        )
    )
    session.commit()

    outcome = run_pass(league)

    session.expire_all()
    assert champions(session)[0].id == league.champion.id
    row = audit(session)[-1]
    assert row.decision == "keep" and row.reason.startswith("monitor: would promote")
    assert outcome.entries[0].action == promo.ACTION_RECORDED and not outcome.promoted

    # a week after that look the very same evidence is a decision-grade look and promotes
    add_equal_games(league, 6, 24.0 * 8)  # new paired games, so the pass evaluates again
    run_pass(league, now=NOW + timedelta(days=7))
    session.expire_all()
    assert champions(session)[0].id == league.challenger.id


def test_with_autopromote_off_no_look_is_spent(league):
    better_league(league)
    run_pass(league, autopromote=False)
    row = audit(league.session)[-1]
    assert row.decision == "dry_run" and row.metrics["decision_grade"] is True and row.metrics["look_spent"] is False
    assert ev.look_history(league.session, league.champion, league.challenger.id)[0] == 0


# --------------------------------------------------------------------- a failed swap leaves truthful rows

def two_qualified(league):
    win, margin, mu_champion, mu_challenger = better_league(league)
    add_model(league, "lab-2", (mu_champion + mu_challenger) / 2)
    return league.challenger.id


def test_a_failed_swap_leaves_no_row_that_claims_a_promotion(league, monkeypatch):
    two_qualified(league)
    session = league.session
    old_id = league.champion.id
    monkeypatch.setattr(promo, "_promote_row", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("disk on fire")))

    outcome = run_pass(league)

    session.expire_all()
    assert champions(session)[0].id == old_id
    rows = audit(session)
    assert len(rows) == 1  # the failure is recorded once
    (row,) = rows
    assert row.decision == "keep" and row.metrics["failed"] is True and row.metrics["applied"] is False
    assert "failed and was rolled back" in row.reason and "roles unchanged" in row.reason and "disk on fire" in row.reason
    assert not any("was promoted" in (r.reason or "") for r in rows)
    actions = sorted(e.action for e in outcome.entries)
    assert actions == [promo.ACTION_FAILED, promo.ACTION_SKIPPED]  # the other qualified challenger is simply not recorded
    assert not outcome.promoted


def test_the_rows_of_the_other_challengers_are_written_after_the_swap_committed(league, monkeypatch):
    two_qualified(league)
    session = league.session
    seen = []
    original = promo.swap_champion

    def spy(session_, new, old, now, note):
        original(session_, new, old, now, note)
        seen.append(len(audit(session_)))  # inside the swap transaction: rows already committed by this pass

    monkeypatch.setattr(promo, "swap_champion", spy)

    run_pass(league)

    rows = audit(session)
    assert seen == [1]  # only the winner's own audit row existed when the swap ran: nothing else was written before
    winner_row = next(r for r in rows if r.decision == "promote")
    loser_row = next(r for r in rows if r.decision == "keep")
    assert winner_row.id < loser_row.id and "was promoted in this pass" in loser_row.reason


def test_a_promotion_ends_the_pass_and_other_decisions_are_not_applied(league):
    win, margin, mu_champion, mu_challenger = better_league(league)
    rng = np.random.default_rng(9)
    bad = add_model(league, "lab-bad", list(rng.normal(0, 25, len(mu_champion))))  # significantly worse than the champion
    session = league.session
    first = run_pass(league)  # no prior look rows: everything is a decision-grade look

    by_model = {e.model_id: e for e in first.entries}
    assert by_model[bad.id].result.decision == ev.DECISION_RETIRE  # decided against the OLD champion
    assert by_model[league.challenger.id].action == promo.ACTION_PROMOTED
    session.expire_all()
    assert session.get(ModelVersion, bad.id).role == "challenger"  # not retired: the champion changed under it
    bad_row = next(r for r in audit(session) if r.challenger_id == bad.id)
    assert bad_row.decision == "keep" and "was promoted in this pass" in bad_row.reason and bad_row.metrics["proposed_decision"] == "retire"


# ------------------------------------------------------------------------ the last Elo model is protected

def non_elo_champion(league):
    league.champion.name = "margin_features"
    league.session.commit()


def test_the_last_elo_model_is_never_retired_automatically(league):
    non_elo_champion(league)
    win, margin, mu_champion, mu_challenger = simulate(130, 8, 1.0, 25.0)
    league.populate(win, margin, mu_champion, mu_challenger, days=20)

    outcome = run_pass(league)

    assert outcome.entries[0].result.decision == ev.DECISION_RETIRE and not outcome.retired
    league.session.expire_all()
    assert league.session.get(ModelVersion, league.challenger.id).role == "challenger"
    (row,) = audit(league.session)
    assert row.decision == "keep" and row.reason.startswith("last Elo model is protected")
    assert row.metrics["protected"] is True and row.metrics["proposed_decision"] == "retire"
    # also with the kill switch off: the row says keep, not "would retire"
    add_equal_games(league, 6, 24.0 * 9)  # new paired games, so the next pass evaluates again
    run_pass(league, autopromote=False, now=NOW + timedelta(days=8))  # a week after the first look: decision-grade again
    assert audit(league.session)[-1].reason.startswith("last Elo model is protected")


def test_the_elo_reference_is_protected_but_another_elo_model_may_be_retired(league):
    non_elo_champion(league)
    win, margin, mu_champion, mu_challenger = simulate(130, 8, 1.0, 25.0)
    league.populate(win, margin, mu_champion, mu_challenger, days=20)
    second = add_model(league, "lab-second", mu_challenger)  # a second Elo, also far worse

    outcome = run_pass(league)

    by_model = {e.model_id: e for e in outcome.entries}
    league.session.expire_all()
    assert league.session.get(ModelVersion, league.challenger.id).role == "challenger"  # lowest id: the reference
    assert by_model[league.challenger.id].decision == "keep"
    assert league.session.get(ModelVersion, second.id).role == "retired"
    assert by_model[second.id].action == promo.ACTION_RETIRED


def test_a_manual_retirement_of_the_last_elo_model_needs_force(league):
    non_elo_champion(league)
    session = league.session
    with pytest.raises(promo.ManualOverrideRefused, match="last Elo model is protected"):
        promo.manual_retire(session, league.challenger.id, "x", NOW)
    session.expire_all()
    assert session.get(ModelVersion, league.challenger.id).role == "challenger" and audit(session) == []

    row = promo.manual_retire(session, league.challenger.id, "x", NOW, force=True)
    session.expire_all()
    assert session.get(ModelVersion, league.challenger.id).role == "retired" and row.metrics["force"] is True
