"""The "Model league" report section, on empty and populated worlds, and its place in the paper report."""
from datetime import timedelta

import pytest

from app.models import ModelVersion
from app.services import model_promotion as promo
from app.services.model_evaluation import EvaluationConfig
from app.services.league_report import build_league, format_league
from app.services.paper_report import build_report, format_report
from tests.test_model_evaluation import NOW, SIGMA, League, simulate


@pytest.fixture
def league(db_session):
    return League(db_session)


def text(league, now=NOW):
    return format_league(build_league(league.session, now))


def test_an_empty_registry_says_so(db_session):
    out = format_league(build_league(db_session, NOW))
    assert "No champion registered" in out


def test_a_champion_alone_is_reported_plainly(db_session):
    db_session.add(ModelVersion(name="elo_538", version="1.1", role="champion", params={"sigma": SIGMA}))
    db_session.commit()
    out = format_league(build_league(db_session, NOW))
    assert "champion    elo_538 1.1: 0 predictions" in out
    assert "No active challengers" in out and "No promotion, rollback or retirement yet" in out
    assert "no candidate proposal has run yet" in out


def test_a_challenger_without_any_paired_game_does_not_print_empty_statistics(league):
    out = text(league)
    assert "challenger  elo_538 lab-x: no predictions yet, paired n=0/150" in out
    assert "no paired games yet: not enough data" in out
    assert "gate        needs 150 more games and 14 more days" in out
    assert "log loss" not in out and "gain" not in out.split("gain = champion")[1].split("\n", 1)[1]


def test_a_young_challenger_shows_how_much_evidence_is_missing(league):
    win, margin, mu_champion, mu_challenger = simulate(12, 3, 6.0, 5.0)
    league.populate(win, margin, mu_champion, mu_challenger, days=5)

    out = text(league)

    assert "paired n=12/150" in out and "5.2 days live" in out
    assert "gate        needs 138 more games and 9 more days" in out
    assert "log loss    champion" in out and "gain " in out and "(95% CI" in out
    assert "vs market   no game with a Pinnacle closing pair yet" in out
    assert "last audit  no evaluation recorded yet; live verdict: insufficient_data" in out


def test_one_paired_game_has_no_interval(league):
    win, margin, mu_champion, mu_challenger = simulate(1, 3, 6.0, 5.0)
    league.populate(win, margin, mu_champion, mu_challenger, days=1)
    out = text(league)
    assert "paired n=1/150" in out and "too few games for a confidence interval" in out


def test_a_strong_challenger_shows_a_passed_gate_and_then_the_cooldown_after_a_promotion(league):
    win, margin, mu_champion, mu_challenger = simulate(400, 21, 7.0, 1.0)
    league.populate(win, margin, mu_champion, mu_challenger, days=40)

    before = text(league)
    assert "paired n=400/150" in before and "gate        gate passed" in before
    assert "live verdict: promote" in before

    league.champion.promoted_at = NOW - timedelta(days=5)
    league.session.commit()
    cooling = text(league)
    assert "gate        cooldown until" in cooling

    league.champion.promoted_at = NOW - timedelta(days=60)
    league.session.commit()
    promo.run_evaluation_pass(league.session, NOW, autopromote=True, config=EvaluationConfig(resamples=300))
    after = text(league)
    assert "champion    elo_538 lab-x" in after  # the promoted model leads the table
    assert "promote  elo_538 lab-x:" in after and "log-loss gain" in after
    assert "challenger  elo_538 1.1" in after  # the ex-champion keeps being watched
    assert "last audit" in after


def test_manual_changes_and_retired_models_appear_in_the_history(league):
    promo.manual_retire(league.session, league.challenger.id, "not useful", NOW)
    out = text(league)
    assert "retire   elo_538 lab-x: manual: not useful" in out
    assert "No active challengers" in out  # a retired model is no longer evaluated


def test_the_paper_report_includes_the_league_section(league):
    win, margin, mu_champion, mu_challenger = simulate(30, 3, 6.0, 5.0)
    league.populate(win, margin, mu_champion, mu_challenger, days=10)

    report = build_report(league.session, NOW)
    out = format_report(report)

    assert report.league is not None and report.league.challengers[0].result.n_games == 30
    assert "Model league (live paired evaluation" in out and "paired n=30/150" in out
    assert out.index("Active models") < out.index("Model league") < out.index("Bankroll")


def test_the_paper_report_still_works_with_an_empty_database(db_session):
    out = format_report(build_report(db_session, NOW))
    assert "No champion registered" in out and "No model registered" in out
