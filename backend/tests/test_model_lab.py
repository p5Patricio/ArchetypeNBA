"""Historical candidate lab: time split, search, paired statistics, gate, registration guard and the CLI."""
import importlib.util
import json
from contextlib import nullcontext
from pathlib import Path

import numpy as np
import pytest
from sqlalchemy.engine import make_url
from sqlmodel import select

from app.analytics.elo import EloParams
from app.models import ModelVersion, TeamEloRating
from app.services import margin_features_model as mfm
from app.services import model_lab as lab
from app.services import model_registry
from tests.synthetic_league import insert_league, make_league
from tests.test_elo_backfill_service import populate_three_seasons, world  # noqa: F401


@pytest.fixture(scope="module")
def synthetic():
    games = make_league(n_seasons=12, n_teams=12, seed=3)
    return lab.prepare_lab_data(games, {i: f"S{i:02d}" for i in range(1, 13)})


def _run(data, **kwargs):
    kwargs = {"seed": 42, "n_configs": 8, "resamples": 300, **kwargs}
    return lab.run_lab(data, EloParams(), **kwargs)


# ----------------------------------------------------------------------------------------- split

def test_the_split_selects_t_minus_9_to_t_minus_2_and_holds_out_the_last_two_seasons():
    split = lab.make_split(list(range(23)))  # T = 22

    assert split.selection == tuple(range(13, 21))  # T-9 .. T-2
    assert split.holdout == (21, 22)  # T-1, T
    assert split.fit_through == 20  # margin_features trains on seasons <= T-2


def test_the_split_needs_enough_completed_seasons_and_skips_the_burn_in_season():
    with pytest.raises(lab.LabError):
        lab.make_split([0, 1, 2, 3])
    assert 0 not in lab.make_split(list(range(8))).selection


def test_a_partial_current_season_is_not_completed_and_never_becomes_t():
    games = make_league(n_seasons=6, n_teams=8, seed=2)
    last = max(g.season_id for g in games)
    kept = [g for g in games if g.season_id < last] + [g for g in games if g.season_id == last][:15]
    data = lab.prepare_lab_data(kept, {})
    assert data.completed_ranks == list(range(5))
    assert max(lab.make_split(data.completed_ranks).holdout) == 4


def test_margin_features_never_trains_on_or_after_its_test_season(synthetic, monkeypatch):
    calls = []
    original = mfm.fit_on_feature_set

    def spy(feature_set, train_mask, **kwargs):
        calls.append(set(feature_set.season_rank[train_mask].tolist()))
        return original(feature_set, train_mask, **kwargs)

    monkeypatch.setattr(mfm, "fit_on_feature_set", spy)
    split = lab.make_split(synthetic.completed_ranks)
    plan = [([r for r in synthetic.completed_ranks if 1 <= r < test], [test]) for test in split.selection[2:]]
    lab.run_margin_features(synthetic, plan, seed=1)
    assert len(calls) == len(plan)
    for trained, (_, tests) in zip(calls, plan):
        assert trained and max(trained) < min(tests)

    calls.clear()
    report = _run(synthetic)
    seasons = sorted(set(synthetic.completed_ranks))
    hold = split.holdout
    assert [max(c) for c in calls[:1]] == [split.fit_through]  # the hold-out fit stops at T-2
    assert all(max(c) < min(hold) for c in calls[:-1])  # only the deployed (gate-passing) refit may include them
    assert report.split["holdout"] == [synthetic.rank_labels[r] for r in hold] and seasons


# ------------------------------------------------------------------------------------ statistics

def test_metrics_on_a_hand_checked_example():
    p = np.array([0.8, 0.4])
    win = np.array([1.0, 0.0])
    metrics = lab.compute_metrics(p, np.array([6.0, -2.0]), np.array([10.0, 10.0]), win, np.array([8.0, -4.0]))
    assert metrics.n == 2
    assert metrics.log_loss == pytest.approx((-np.log(0.8) - np.log(0.6)) / 2)
    assert metrics.brier == pytest.approx((0.04 + 0.16) / 2)
    assert metrics.accuracy == 1.0
    assert metrics.mae_margin == pytest.approx((2 + 2) / 2)
    assert metrics.margin_nll == pytest.approx(0.5 * np.log(2 * np.pi * 100) + (4 + 4) / 2 / 200)


def test_calibration_slope_is_one_for_calibrated_probabilities_and_below_one_for_overconfident_ones():
    rng = np.random.default_rng(0)
    true_p = rng.uniform(0.15, 0.85, size=20000)
    win = (rng.random(20000) < true_p).astype(float)
    slope, intercept = lab.calibration_fit(true_p, win)
    assert slope == pytest.approx(1.0, abs=0.08) and intercept == pytest.approx(0.0, abs=0.05)

    logit = np.log(true_p / (1 - true_p))
    overconfident = 1 / (1 + np.exp(-2.0 * logit))
    assert lab.calibration_fit(overconfident, win)[0] == pytest.approx(0.5, abs=0.06)


def test_the_bootstrap_interval_covers_a_known_difference_and_is_reproducible():
    rng = np.random.default_rng(1)
    gains = rng.normal(0.01, 0.1, size=4000)

    delta = lab.paired_bootstrap(gains, seed=7, resamples=2000)

    assert delta.ci_low < 0.01 < delta.ci_high
    assert delta.ci_low > 0.0  # 0.01 +- 2 * 0.1 / sqrt(4000) excludes zero
    assert delta.n == 4000 and delta.mean == pytest.approx(gains.mean())
    assert lab.paired_bootstrap(gains, seed=7, resamples=2000) == delta
    assert lab.paired_bootstrap(gains, seed=8, resamples=2000) != delta
    zero = lab.paired_bootstrap(rng.normal(0.0, 0.1, size=4000), seed=7)
    assert zero.ci_low < 0.0 < zero.ci_high


def test_trailing_sigma_uses_only_earlier_seasons():
    ranks = np.array([0, 0, 1, 1, 2, 2])
    residuals = np.array([3.0, -3.0, 5.0, -5.0, 100.0, -100.0])
    sigma = lab.trailing_sigma(residuals, ranks, default=12.0)
    assert list(sigma[:2]) == [12.0, 12.0]  # nothing before the first season
    assert sigma[2] == pytest.approx(3.0)  # season 1 sees season 0 only
    assert sigma[4] == pytest.approx(np.sqrt((9 + 9 + 25 + 25) / 4))  # season 2 never sees itself


# ------------------------------------------------------------------------------------------ search

def test_the_elo_search_is_seeded_and_stays_inside_the_ranges():
    configs = lab.search_elo_params(40, seed=42)
    assert configs == lab.search_elo_params(40, seed=42) and len(configs) == 40
    assert configs != lab.search_elo_params(40, seed=43)
    for params in configs:
        for name, (low, high) in lab.ELO_SEARCH_RANGES.items():
            assert low <= getattr(params, name) <= high
        assert params.mean_rating == EloParams().mean_rating and params.elo_per_point == EloParams().elo_per_point


def test_the_search_finds_a_better_k_than_a_deliberately_bad_baseline(synthetic):
    bad = EloParams(k=1.0)
    report = lab.run_lab(synthetic, bad, seed=5, n_configs=12, resamples=300)

    best = report.elo_top[0]
    assert best.selection.log_loss < report.champion_selection.log_loss
    assert best.params["K"] > 3.0
    assert best.selection_gain.mean > 0 and best.selection_gain.ci_low > 0
    assert report.candidates[0].holdout_gain.mean > 0 and report.candidates[0].gate.passed


def test_the_top_configurations_are_ranked_by_selection_log_loss(synthetic):
    report = _run(synthetic, n_configs=10, top_n=4)
    losses = [r.selection.log_loss for r in report.elo_top]
    assert losses == sorted(losses) and len(losses) == 4


def test_margin_features_beats_a_coin_flip_on_the_hold_out(synthetic):
    report = _run(synthetic)
    margin = next(c for c in report.candidates if c.kind == mfm.FAMILY_NAME)
    assert margin.holdout.log_loss < np.log(2) - 0.02
    assert margin.holdout.accuracy > 0.58
    assert margin.selection is not None and margin.selection.log_loss < np.log(2)


# ---------------------------------------------------------------------------------------------- gate

def test_the_gate_needs_the_gain_and_a_material_difference():
    assert lab.evaluate_gate(0.0006, True).passed
    assert lab.evaluate_gate(0.0005, True).passed  # exactly the threshold
    assert not lab.evaluate_gate(0.0004, True).passed
    assert not lab.evaluate_gate(0.01, False).passed
    verdict = lab.evaluate_gate(-0.002, False)
    assert not verdict.passed and len(verdict.reasons) == 2


def test_elo_parameters_differ_materially_from_every_active_model():
    base = EloParams()  # K 20, HA 60, carryover 0.75, mov 0.8
    assert not lab.elo_materially_differs(base, EloParams(k=21.0))  # exactly 5% of the range is not enough
    assert lab.elo_materially_differs(base, EloParams(k=21.01))
    assert lab.elo_materially_differs(base, EloParams(home_advantage=64.5))
    assert not lab.elo_materially_differs(base, EloParams(carryover=0.77))
    assert lab.elo_materially_differs(base, EloParams(carryover=0.7701))
    assert lab.elo_materially_differs(base, EloParams(mov_exponent=0.83))

    champion = ModelVersion(name="elo_538", version="1.1", params={}, role="champion")
    near = ModelVersion(name="elo_538", version="2.0", params={"K": 25.0}, role="challenger")
    assert lab.differs_from_active("elo_538", EloParams(k=25.5), [champion, near]) is False  # too close to #2
    assert lab.differs_from_active("elo_538", EloParams(k=25.5), [champion]) is True
    assert lab.differs_from_active("margin_features", None, [champion, near]) is True  # another family
    other = ModelVersion(name="margin_features", version="x", params={}, role="challenger")
    assert lab.differs_from_active("margin_features", None, [champion, other]) is False
    assert lab.differs_from_active("elo_538", EloParams(k=30.0), [champion, other]) is True


def test_a_candidate_equal_to_the_champion_never_passes(synthetic):
    champion = ModelVersion(name="elo_538", version="1.1", params={}, role="champion")
    report = lab.run_lab(synthetic, EloParams(), [champion], seed=1, n_configs=3, resamples=200)
    # the search may find a better config, but a margin_features candidate is a different family
    assert all(c.gate.differs for c in report.candidates if c.kind == mfm.FAMILY_NAME)
    same = lab.differs_from_active("elo_538", EloParams(), [champion])
    assert same is False


# ---------------------------------------------------------------------------- reproducibility, budget

def _stable(report):
    data = report.to_dict()
    data.pop("elapsed_seconds")
    return json.dumps(data, sort_keys=True, default=str)


def test_the_same_seed_and_data_give_identical_numbers(synthetic):
    first, second = _run(synthetic), _run(synthetic)
    assert _stable(first) == _stable(second)
    assert _stable(_run(synthetic, seed=43)) != _stable(first)


def test_an_expired_budget_gives_a_partial_report_with_the_champion_and_one_configuration(synthetic):
    report = lab.run_lab(synthetic, EloParams(), seed=1, n_configs=8, resamples=200, deadline=-1.0, clock=lambda: 0.0)

    assert report.partial and report.configs_evaluated == 1 and report.configs_requested == 8
    assert [c.kind for c in report.candidates] == ["elo_538"]
    assert any("time budget" in note for note in report.notes)
    assert report.champion_holdout.n > 0


# --------------------------------------------------------------------------- registration and guard

def _metrics():
    return lab.Metrics(n=10, log_loss=0.6, brier=0.21, accuracy=0.6, mae_margin=9.0, margin_nll=3.8,
                       calibration_slope=1.0, calibration_intercept=0.0)


def _fake_report(candidates):
    delta = lab.PairedDelta(0.002, 0.0005, 0.0035, 10)
    return lab.LabReport(
        seed=42, n_games=24, split={"selection": ["a"], "holdout": ["b", "c"]}, champion_params=EloParams().to_dict(),
        champion_selection=_metrics(), champion_holdout=_metrics(), configs_requested=1, configs_evaluated=1,
        elo_top=[], candidates=candidates,
    )


def _elo_candidate(passed=True, **overrides):
    params = {**EloParams(k=26.0, home_advantage=80.0).to_dict(), "sigma": 13.0, "trained_through": "2006-01-01",
              "seasons_evaluated": ["2003-04"], "seed": 42, "source": "model_lab", **overrides}
    gate = lab.evaluate_gate(0.002 if passed else 0.0, True)
    return lab.CandidateResult("elo_538", "elo_538 search #3", _metrics(), lab.PairedDelta(0.002, 0.0, 0.004, 10), gate,
                               deploy_params=params if passed else None)


def _setup_models(session, challengers=0):
    champion = ModelVersion(name="elo_538", version="1.1", params={"sigma": 14.0}, role="champion")
    session.add(champion)
    session.add_all([ModelVersion(name="elo_538", version=f"c{i}", params={"sigma": 13.0}, role="challenger") for i in range(challengers)])
    session.commit()
    return champion


def test_registration_needs_a_typed_confirmation_outside_sqlite():
    postgres = make_url("postgresql+psycopg://user:secret@localhost:5432/nba_platform")
    with pytest.raises(lab.RegistrationRefused, match="--confirm-database nba_platform"):
        lab.check_registration_target(postgres, None)
    with pytest.raises(lab.RegistrationRefused):
        lab.check_registration_target(postgres, "other_db")
    lab.check_registration_target(postgres, "nba_platform")
    lab.check_registration_target(make_url("sqlite:///:memory:"), None)


def test_registration_refuses_when_three_challengers_are_already_active(world):
    session = world["session"]
    _setup_models(session, challengers=3)

    with pytest.raises(lab.RegistrationRefused, match="3 challengers"):
        lab.register_candidates(session, _fake_report([_elo_candidate()]))
    assert len(session.exec(select(ModelVersion)).all()) == 4


def test_registration_inserts_a_challenger_and_backfills_its_ratings(world):
    session = world["session"]
    champion = _setup_models(session)
    populate_three_seasons(world)

    result = lab.register_candidates(session, _fake_report([_elo_candidate()]))

    (row,) = result.registered
    stored = session.get(ModelVersion, row.id)
    assert (stored.name, stored.role, stored.parent_id) == ("elo_538", "challenger", champion.id)
    assert stored.version.startswith("lab-20060101-") and stored.params["K"] == 26.0 and stored.params["seed"] == 42
    notes = json.loads(stored.notes)
    assert notes["seed"] == 42 and notes["parent"] == "elo_538 1.1" and "holdout" in notes
    assert float(stored.brier_oos) == pytest.approx(0.21)
    rating_rows = session.exec(select(TeamEloRating).where(TeamEloRating.model_version_id == row.id)).all()
    assert len(rating_rows) == 24 and result.backfilled_rows == {row.id: 24}
    assert {r.k_factor for r in rating_rows} == {26.0}  # the candidate's own hyperparameters drove the replay
    assert [m.id for m in model_registry.list_active(session)] == [champion.id, row.id]


def test_registration_dry_run_writes_nothing_and_a_second_run_is_idempotent(world):
    session = world["session"]
    _setup_models(session)
    populate_three_seasons(world)
    report = _fake_report([_elo_candidate()])

    planned = lab.register_candidates(session, report, dry_run=True)
    assert len(planned.planned) == 1 and planned.dry_run and planned.registered == []
    assert len(session.exec(select(ModelVersion)).all()) == 1 and session.exec(select(TeamEloRating)).all() == []

    lab.register_candidates(session, report)
    again = lab.register_candidates(session, report)
    assert again.registered == [] and "already registered" in again.skipped[0]
    assert len(session.exec(select(ModelVersion)).all()) == 2


def test_registration_stops_at_the_free_slots_best_gain_first(world):
    session = world["session"]
    _setup_models(session, challengers=2)
    populate_three_seasons(world)
    weaker = _elo_candidate(K=15.0)
    weaker.gate = lab.evaluate_gate(0.001, True)
    stronger = _elo_candidate(K=28.0)
    stronger.gate = lab.evaluate_gate(0.004, True)

    result = lab.register_candidates(session, _fake_report([weaker, stronger]))

    assert [r.params["K"] for r in result.registered] == [28.0]  # one free slot goes to the larger gain
    assert any("no free challenger slot" in s for s in result.skipped)


def test_nothing_is_registered_when_no_candidate_passes(world):
    session = world["session"]
    _setup_models(session)

    result = lab.register_candidates(session, _fake_report([_elo_candidate(passed=False)]))

    assert result.registered == [] and result.skipped == ["no candidate passed the historical gate"]
    assert len(session.exec(select(ModelVersion)).all()) == 1


def test_a_margin_features_candidate_registers_without_a_backfill_and_is_loadable(world, synthetic):
    session = world["session"]
    _setup_models(session)
    params = lab.fit_margin_model(synthetic, synthetic.completed_ranks, seed=42)
    gate = lab.evaluate_gate(0.002, True)
    candidate = lab.CandidateResult("margin_features", "margin_features", _metrics(), lab.PairedDelta(0.002, 0.0, 0.004, 10),
                                    gate, deploy_params=params)

    result = lab.register_candidates(session, _fake_report([candidate]))

    (row,) = result.registered
    assert result.backfilled_rows == {} and session.exec(select(TeamEloRating)).all() == []
    assert row.name == "margin_features" and model_registry.load_model(session, row).version == row.version


# ------------------------------------------------------------------------------------------- the CLI

def _load_cli():
    path = Path(__file__).resolve().parents[1] / "scripts" / "model_lab.py"
    spec = importlib.util.spec_from_file_location("model_lab_cli", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def league_db(db_session):
    insert_league(db_session, make_league(n_seasons=9, n_teams=8, seed=4, rounds=14))
    db_session.add(ModelVersion(name="elo_538", version="1.1", params={"sigma": 14.0}, role="champion"))
    db_session.commit()
    return db_session


def test_the_cli_prints_the_report_and_writes_json_without_touching_the_database(league_db, capsys, tmp_path):
    cli = _load_cli()
    out_file = tmp_path / "lab.json"

    code = cli.main(["--seed", "42", "--configs", "4", "--json", str(out_file)], session_factory=lambda: nullcontext(league_db))

    assert code == 0
    out = capsys.readouterr().out
    for expected in ("Model lab: seed 42", "Selection window", "Hold-out", "Verdicts", "margin_features", "runtime:"):
        assert expected in out
    data = json.loads(out_file.read_text(encoding="utf-8"))
    assert data["seed"] == 42 and data["configs_evaluated"] == 4 and len(data["candidates"]) == 2
    assert len(league_db.exec(select(ModelVersion)).all()) == 1  # nothing was registered
    assert league_db.exec(select(TeamEloRating)).all() == []


def test_the_cli_register_dry_run_plans_but_never_writes(league_db, capsys):
    cli = _load_cli()

    code = cli.main(["--configs", "6", "--register", "--dry-run"], session_factory=lambda: nullcontext(league_db))

    assert code == 0
    out = capsys.readouterr().out
    assert "Registration (dry run)" in out
    assert len(league_db.exec(select(ModelVersion)).all()) == 1


def test_the_cli_reports_a_missing_champion_instead_of_crashing(db_session, capsys):
    cli = _load_cli()
    insert_league(db_session, make_league(n_seasons=9, n_teams=8, seed=4, rounds=14))

    code = cli.main(["--configs", "2"], session_factory=lambda: nullcontext(db_session))

    assert code == 1
    assert "model lab cannot run" in capsys.readouterr().err
