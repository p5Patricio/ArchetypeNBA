from dataclasses import replace
from datetime import date, datetime, time, timedelta, timezone
import random
from typing import Dict, List

import numpy as np
import pytest

from app.analytics.features import FEATURE_NAMES, build_feature_set
from app.analytics.totals_model import build_totals_feature_set
from app.services import historical_backtest as bt
from app.services import line_move_report as lmr
from app.services import line_move_strategy as lms
from app.services import line_movement as lm
from app.services.elo_service import HistoricalGame
from app.services.model_registry import ModelRegistryError
from tests.synthetic_league import make_league


def _utc(y: int, m: int, d: int, h: int = 0, minute: int = 0) -> datetime:
    return datetime(y, m, d, h, minute, tzinfo=timezone.utc)


# ------------------------------------------------------------------------------------------------ 1. readiness_times


def test_readiness_times_tips_end_of_day_first_games_and_strict_earlier_dates():
    g1 = HistoricalGame("0022600001", date(2026, 10, 20), 1, 1, 2, 110, 100)
    g2 = HistoricalGame("0022600002", date(2026, 10, 21), 1, 3, 4, 105, 99)
    # Same date as g2: must not count as previous for g2 or g_same_day even with smaller game_id
    g_same_day = HistoricalGame("0022600000", date(2026, 10, 21), 1, 3, 5, 102, 101)
    # Target game where both teams (1 and 3) played on strictly earlier dates
    g3 = HistoricalGame("0022600003", date(2026, 10, 23), 1, 1, 3, 108, 104)
    # One team with a previous game (1) and one playing its first game (6)
    g4 = HistoricalGame("0022600004", date(2026, 10, 25), 1, 1, 6, 100, 95)

    t1 = _utc(2026, 10, 20, 23, 0)
    t2 = _utc(2026, 10, 21, 23, 30)
    t3 = _utc(2026, 10, 23, 22, 0)

    # (a) both previous games with known tips -> ready_at == max(prev tip + 3 h) + 30 min, source "tip"
    tips_all = {g1.game_id: t1, g2.game_id: t2, g_same_day.game_id: _utc(2026, 10, 21, 18, 0), g3.game_id: t3}
    ready = lm.readiness_times([g1, g2, g3, g4], tips_all)

    r3 = ready[g3.game_id]
    expected_ready = max(t1 + timedelta(hours=3), t2 + timedelta(hours=3)) + timedelta(minutes=30)
    assert r3.ready_at == expected_ready
    assert r3.source == "tip"
    assert r3.previous == (g1.game_id, g2.game_id)

    # (b) a previous game without a tip -> final is 07:00 UTC the day after its date, source "end_of_day"
    end_g2, src_g2 = lm.final_time(g2.game_id, g2.game_date, {g1.game_id: t1})
    assert end_g2 == _utc(2026, 10, 22, 7, 0)
    assert src_g2 == "end_of_day"

    ready_missing_tip = lm.readiness_times([g1, g2, g3], {g1.game_id: t1})
    r3_eod = ready_missing_tip[g3.game_id]
    assert r3_eod.ready_at == _utc(2026, 10, 22, 7, 0) + timedelta(minutes=30)
    assert r3_eod.source == "end_of_day"
    assert r3_eod.previous == (g1.game_id, g2.game_id)

    # (c) a team's first game -> no constraint from that team; both first -> ready_at None, source "none"
    r1 = ready[g1.game_id]
    assert r1.ready_at is None
    assert r1.source == "none"
    assert r1.previous == ()

    r4 = ready[g4.game_id]
    assert r4.ready_at == t3 + timedelta(hours=3, minutes=30)
    assert r4.source == "tip"
    assert r4.previous == (g3.game_id,)

    # (d) only strictly earlier DATES count as previous
    ready_same_date = lm.readiness_times([g_same_day, g2], tips_all)
    assert ready_same_date[g2.game_id].ready_at is None
    assert ready_same_date[g2.game_id].source == "none"
    assert ready_same_date[g2.game_id].previous == ()


# ------------------------------------------------------------------------------------------------ 2. entry_quote


def test_entry_quote_rules_and_edge_cases():
    t0 = _utc(2026, 10, 22, 14, 0)
    t1 = _utc(2026, 10, 22, 18, 0)
    t2 = _utc(2026, 10, 22, 22, 0)
    pairs = [
        (t0, -3.0, (1.91, 1.91)),
        (t1, -3.5, (1.95, 1.87)),
        (t2, -4.0, (1.91, 1.91)),
    ]

    # Empty pairs -> None
    assert lm.entry_quote([], t0) is None

    # Ready None or before/at opener -> opener pair at its own time
    assert lm.entry_quote(pairs, None) == (t0, pairs[0])
    assert lm.entry_quote(pairs, t0 - timedelta(hours=2), lm.ENTRY_FIRST_AFTER) == (t0, pairs[0])
    assert lm.entry_quote(pairs, t0 - timedelta(hours=2), lm.ENTRY_IN_FORCE) == (t0, pairs[0])
    assert lm.entry_quote(pairs, t0, lm.ENTRY_FIRST_AFTER) == (t0, pairs[0])

    # first_after -> first pair with time >= ready
    ready_mid = _utc(2026, 10, 22, 16, 0)
    assert lm.entry_quote(pairs, ready_mid, lm.ENTRY_FIRST_AFTER) == (t1, pairs[1])
    assert lm.entry_quote(pairs, t1, lm.ENTRY_FIRST_AFTER) == (t1, pairs[1])

    # no pair at/after ready -> None
    after_close = t2 + timedelta(minutes=1)
    assert lm.entry_quote(pairs, after_close, lm.ENTRY_FIRST_AFTER) is None

    # in_force -> (ready, the last pair at or before ready)
    assert lm.entry_quote(pairs, ready_mid, lm.ENTRY_IN_FORCE) == (ready_mid, pairs[0])
    ready_mid2 = _utc(2026, 10, 22, 20, 0)
    assert lm.entry_quote(pairs, ready_mid2, lm.ENTRY_IN_FORCE) == (ready_mid2, pairs[1])
    assert lm.entry_quote(pairs, t2, lm.ENTRY_IN_FORCE) == (t2, pairs[2])

    # in_force with ready after the last pair -> None
    assert lm.entry_quote(pairs, after_close, lm.ENTRY_IN_FORCE) is None

    # unknown rule -> ValueError
    with pytest.raises(ValueError, match="unknown entry rule"):
        lm.entry_quote(pairs, ready_mid, "bogus_rule")


# ------------------------------------------------------------------------------------------------ 3. entry_paths


def test_entry_paths_invariants_exclusions_and_stats():
    t_open = _utc(2026, 10, 22, 12, 0)
    t_ready = _utc(2026, 10, 22, 15, 0)
    t_mid = _utc(2026, 10, 22, 16, 0)
    t_close = _utc(2026, 10, 22, 22, 50)
    t_tip = _utc(2026, 10, 22, 23, 0)

    spread_pairs = [
        (t_open, -2.5, (1.91, 1.91)),
        (t_mid, -3.5, (1.95, 1.87)),
        (t_close, -4.5, (1.91, 1.91)),
    ]
    total_pairs = [
        (t_open + timedelta(hours=4), 220.5, (1.91, 1.91)),
        (t_close, 222.0, (1.93, 1.89)),
    ]
    h2h_pairs = [
        (t_open, 0.0, (1.60, 2.40)),
        (t_close, 0.0, (1.50, 2.65)),
    ]

    # Path 1: ready_at between t_open and t_mid; spreads enters at t_mid, totals at its opener (t_open + 4h), h2h dropped
    p1 = lm.GamePath(
        key="game:1",
        nba_game_id="0022600001",
        tip=t_tip,
        markets={},
        pairs={"spreads": spread_pairs, "totals": total_pairs, "h2h": h2h_pairs},
    )
    # Path 2: ready_at is None (first game of season) -> enters at opener
    p2 = lm.GamePath(
        key="game:2",
        nba_game_id="0022600002",
        tip=t_tip,
        markets={},
        pairs={"spreads": spread_pairs, "h2h": h2h_pairs},
    )
    # Path 3: ready_at after all quotes -> no entry, counted in stats.no_entry
    p3 = lm.GamePath(
        key="game:3",
        nba_game_id="0022600003",
        tip=t_tip,
        markets={},
        pairs={"spreads": spread_pairs, "totals": total_pairs},
    )
    # Path 4: nba_game_id not in readiness -> excluded
    p4 = lm.GamePath(
        key="game:4",
        nba_game_id="0022600999",
        tip=t_tip,
        markets={},
        pairs={"spreads": spread_pairs},
    )
    # Path 5: nba_game_id is None -> excluded
    p5 = lm.GamePath(
        key="game:5",
        nba_game_id=None,
        tip=t_tip,
        markets={"spreads": None},
        pairs={"spreads": spread_pairs},
    )

    readiness = {
        "0022600001": lm.Readiness("0022600001", t_ready, "tip", ("0022600000",)),
        "0022600002": lm.Readiness("0022600002", None, "none", ()),
        "0022600003": lm.Readiness("0022600003", t_close + timedelta(minutes=5), "tip", ("0022600000",)),
    }

    out, as_of, stats = lm.entry_paths([p1, p2, p3, p4, p5], readiness, lm.ENTRY_FIRST_AFTER)

    assert [p.nba_game_id for p in out] == ["0022600001", "0022600002"]
    assert stats.games == 3
    assert stats.no_entry["spreads"] == 1
    assert stats.no_entry["totals"] == 1
    assert stats.entries["spreads"] == 2
    assert stats.entries["totals"] == 1
    assert stats.at_opener["spreads"] == 1  # p2 only
    assert stats.at_opener["totals"] == 1  # p1 totals opened at 16:00 > ready_at 15:00

    for path in out:
        assert "h2h" not in path.markets
        r = readiness[path.nba_game_id]
        game_as_of = as_of[path.nba_game_id]
        for market, oc in path.markets.items():
            orig_close_at, orig_close_line, orig_close_prices = path.pairs[market][-1]
            if r.ready_at is not None:
                assert oc.open_at >= r.ready_at
            assert oc.open_at <= oc.close_at
            assert (oc.close_at, oc.close_line, oc.close_prices) == (orig_close_at, orig_close_line, orig_close_prices)
            assert game_as_of <= oc.open_at


# ------------------------------------------------------------------------------------------------ 4. features_as_of


def test_features_as_of_leak_safety():
    games = make_league(n_seasons=3, n_teams=8, seed=42)
    fs, _ = build_feature_set(games)
    totals_fs, _ = build_totals_feature_set(games)
    idx_of = {g.game_id: i for i, g in enumerate(games)}

    # Pick a target game G in season 2 where both teams have played multiple games
    season2_games = [g for g in games if g.season_id == 2]
    target = season2_games[20]
    target_idx = idx_of[target.game_id]

    # Default tip: 23:00 UTC on game_date for every game
    tips: Dict[str, datetime] = {
        g.game_id: datetime.combine(g.game_date, time(23, 0), tzinfo=timezone.utc) for g in games
    }
    readiness = lm.readiness_times(games, tips)
    r_target = readiness[target.game_id]
    assert r_target.ready_at is not None and len(r_target.previous) == 2

    # Find another team's game on the same date as the latest previous game of target's teams,
    # and push its tip to 23:45 UTC so its final time (02:45 UTC) is AFTER target's readiness T (02:30 UTC).
    prev_ids = set(r_target.previous)
    prev_dates = {games[idx_of[pid]].game_date for pid in prev_ids}
    latest_prev_date = max(prev_dates)
    same_evening_other = [
        g for g in games
        if g.game_date == latest_prev_date
        and g.game_id not in prev_ids
        and g.home_team_id not in (target.home_team_id, target.away_team_id)
        and g.away_team_id not in (target.home_team_id, target.away_team_id)
    ]
    assert same_evening_other, "expected another game on the same evening"
    late_evening_game = same_evening_other[0]
    tips_with_late = dict(tips)
    tips_with_late[late_evening_game.game_id] = datetime.combine(
        late_evening_game.game_date, time(23, 45), tzinfo=timezone.utc
    )

    T = lm.readiness_times(games, tips_with_late)[target.game_id].ready_at
    assert T is not None
    assert lm.final_time(late_evening_game.game_id, late_evening_game.game_date, tips_with_late)[0] > T

    base_out, refused = lm.features_as_of(games, tips_with_late, {target.game_id: T})
    assert refused == []
    base_vec, base_mu = base_out[target.game_id]

    # (a) Changing the score of ANY game whose final time (tip + 3h) is after T leaves (feature row, totals mu) bit-identical
    perturbed_future = [
        replace(g, home_pts=g.away_pts + 33, away_pts=g.home_pts + 17)
        if lm.final_time(g.game_id, g.game_date, tips_with_late)[0] > T
        else g
        for g in games
    ]
    pert_out, pert_refused = lm.features_as_of(perturbed_future, tips_with_late, {target.game_id: T})
    assert pert_refused == []
    pert_vec, pert_mu = pert_out[target.game_id]
    assert np.array_equal(base_vec, pert_vec)
    assert base_mu == pert_mu

    # (b) Changing the score of a team's previous game (final before T) changes G's feature row
    prev_id = r_target.previous[0]
    assert lm.final_time(prev_id, games[idx_of[prev_id]].game_date, tips_with_late)[0] < T
    perturbed_prev = [
        replace(g, home_pts=g.away_pts + 40, away_pts=max(50, g.home_pts - 20)) if g.game_id == prev_id else g
        for g in games
    ]
    prev_out, _ = lm.features_as_of(perturbed_prev, tips_with_late, {target.game_id: T})
    prev_vec, _ = prev_out[target.game_id]
    assert not np.allclose(base_vec, prev_vec)

    # (c) When the target's instant is after all earlier dates' games are final (and before target's date finishes),
    # the feature row equals build_feature_set(games)[0].X row of G
    T_all_prev_final = r_target.ready_at  # under uniform 23:00 tips, all earlier dates finish at <= T_all_prev_final
    clean_out, clean_refused = lm.features_as_of(games, tips, {target.game_id: T_all_prev_final})
    assert clean_refused == []
    np.testing.assert_allclose(clean_out[target.game_id][0], fs.X[target_idx], rtol=0, atol=1e-12)

    # (d) Totals mu can differ from build_totals_feature_set's mu for G only through games of OTHER teams final after T:
    # With late_evening_game finishing after T, base_mu differs from clean_out[target.game_id][1].
    # And for the first game on target's date (so no game on target's date precedes it in build_totals_feature_set)
    # when all earlier dates' games are final before T, features_as_of's mu equals build_totals_feature_set's mu.
    assert base_mu != pytest.approx(clean_out[target.game_id][1], abs=1e-9)
    first_on_day = min((g for g in games if g.game_date == target.game_date), key=lambda g: g.game_id)
    first_idx = idx_of[first_on_day.game_id]
    first_ready = readiness[first_on_day.game_id].ready_at
    assert first_ready is not None
    first_out, _ = lm.features_as_of(games, tips, {first_on_day.game_id: first_ready})
    assert first_out[first_on_day.game_id][1] == pytest.approx(totals_fs.mu[first_idx], abs=1e-12)


# ------------------------------------------------------------------------------------------------ 5. Backtest export


def _build_export_league(seed: int = 17):
    games = make_league(n_seasons=5, n_teams=8, seed=seed)
    labels = {s: f"{2020 + s}-{(20 + s + 1) % 100:02d}" for s in range(1, 6)}
    fs, _ = build_feature_set(games)
    totals_fs, _ = build_totals_feature_set(games)
    rng = random.Random(seed)
    lines: Dict[str, bt.GameLines] = {}
    for i, g in enumerate(games):
        open_s = float(round(-fs.X[i, 0] / 28.0 * 2.0) / 2.0)
        # Close spread correlated with elo_edge and rest difference
        rest_diff = fs.X[i, 1] - fs.X[i, 2]
        close_s = open_s - 0.15 * rest_diff + rng.gauss(0.0, 0.5)
        open_t = float(round(totals_fs.mu[i] * 2.0) / 2.0)
        close_t = open_t + 0.10 * rest_diff + rng.gauss(0.0, 0.8)
        lines[g.game_id] = bt.GameLines(
            source="sbro",
            open_spread_home=open_s,
            close_spread_home=close_s,
            open_total=open_t,
            close_total=close_t,
            close_moneyline_home=-130 if close_s < 0 else 110,
            close_moneyline_away=110 if close_s < 0 else -130,
        )
    return games, labels, lines, fs, totals_fs


@pytest.fixture(scope="module")
def exported_backtest():
    games, labels, lines, fs, totals_fs = _build_export_league(seed=17)
    export_season = labels[5]
    config = bt.BacktestConfig(seed=17, n_boot=10, min_line_seasons=2, fit_margin_features=True, export_season=export_season)
    result = bt.run_backtest(games, labels, lines, config)
    return games, labels, lines, fs, totals_fs, export_season, result


def test_backtest_exports_reproduce_predictions_and_ridge_round_trip(exported_backtest):
    _, _, _, fs, _, export_season, result = exported_backtest

    for key in ("spreads", "totals", "margin_features", "sigma_spread", "sigma_total"):
        assert key in result.exports
    spreads_fit = result.exports["spreads"]
    totals_fit = result.exports["totals"]
    assert isinstance(spreads_fit, bt.RidgeFit)
    assert isinstance(totals_fit, bt.RidgeFit)
    assert result.exports["sigma_spread"] > 0
    assert result.exports["sigma_total"] > 0

    # Reproduce move_spread and move_total on the export season to 1e-9
    export_idx = result.season_labels.index(export_season)
    te = result.season_of_game == export_idx
    assert te.sum() > 0

    sched = bt.schedule_features(fs.X[te])
    F_s = bt.spread_move_features(
        result.margins["mu_elo"][te],
        result.margins["mu_mf"][te],
        result.lines["open_s"][te],
        sched,
    )
    F_t = bt.total_move_features(
        result.margins["mu_total"][te],
        result.lines["open_t"][te],
        sched,
    )
    np.testing.assert_allclose(spreads_fit.predict(F_s), result.margins["move_spread"][te], rtol=0, atol=1e-9)
    np.testing.assert_allclose(totals_fit.predict(F_t), result.margins["move_total"][te], rtol=0, atol=1e-9)

    # RidgeFit.to_dict / from_dict round trip
    reloaded = bt.RidgeFit.from_dict(spreads_fit.to_dict())
    assert reloaded == spreads_fit
    np.testing.assert_allclose(reloaded.predict(F_s), spreads_fit.predict(F_s), rtol=0, atol=1e-12)

    with pytest.raises(ValueError, match="inconsistent lengths|non-positive scale"):
        bt.RidgeFit.from_dict({"mean": [0.0], "scale": [0.0], "coef": [1.0], "intercept": 0.0, "alpha": 1.0, "n": 10})

    # fit_predict_ridge == fit_ridge_cv(...).predict
    rng = np.random.default_rng(9)
    F_tr = rng.normal(size=(90, 4))
    y_tr = F_tr @ np.array([0.4, -0.2, 0.1, 0.3]) + rng.normal(scale=0.5, size=90)
    s_tr = np.repeat([0, 1, 2], 30)
    F_te = rng.normal(size=(15, 4))
    np.testing.assert_allclose(
        bt.fit_predict_ridge(F_tr, y_tr, s_tr, F_te),
        bt.fit_ridge_cv(F_tr, y_tr, s_tr).predict(F_te),
        rtol=0,
        atol=1e-12,
    )


# ------------------------------------------------------------------------------------------------ 6. LineMoveModel params


def test_build_params_round_trip_and_from_params_validation(exported_backtest):
    _, _, _, fs, _, export_season, result = exported_backtest

    params = lms.build_params(result.exports)
    model = lms.LineMoveModel.from_params(params)
    assert model.spreads == result.exports["spreads"]
    assert model.totals == result.exports["totals"]
    assert model.sigma_spread == pytest.approx(result.exports["sigma_spread"])
    assert model.sigma_total == pytest.approx(result.exports["sigma_total"])

    # Check single-row predict_move matches backtest margins on the export season
    te_indices = np.where(result.season_of_game == result.season_labels.index(export_season))[0]
    i = int(te_indices[0])
    assert model.predict_move("spreads", fs.X[i], float(result.margins["mu_total"][i]), float(result.lines["open_s"][i])) == pytest.approx(
        float(result.margins["move_spread"][i]), abs=1e-9
    )
    assert model.predict_move("totals", fs.X[i], float(result.margins["mu_total"][i]), float(result.lines["open_t"][i])) == pytest.approx(
        float(result.margins["move_total"][i]), abs=1e-9
    )

    # Validation errors on from_params:
    # (1) wrong feature lists
    bad_spread_feats = {**params, "spread_features": ["wrong"]}
    with pytest.raises(ModelRegistryError, match="spread features"):
        lms.LineMoveModel.from_params(bad_spread_feats)

    bad_total_feats = {**params, "total_features": ["wrong"]}
    with pytest.raises(ModelRegistryError, match="total features"):
        lms.LineMoveModel.from_params(bad_total_feats)

    bad_base_feats = {**params, "base_features": ["wrong"]}
    with pytest.raises(ModelRegistryError, match="FEATURE_NAMES"):
        lms.LineMoveModel.from_params(bad_base_feats)

    # (2) wrong coefficient length
    short_ridge = bt.RidgeFit(mean=(0.0, 0.0), scale=(1.0, 1.0), coef=(0.1, 0.2), intercept=0.0, alpha=1.0, n=10).to_dict()
    with pytest.raises(ModelRegistryError, match="coefficients"):
        lms.LineMoveModel.from_params({**params, "spreads": short_ridge})

    # (3) non-positive threshold
    with pytest.raises(ModelRegistryError, match="positive"):
        lms.LineMoveModel.from_params({**params, "thresholds": {"spreads": 0.0, "totals": 0.5}})
    with pytest.raises(ModelRegistryError, match="positive"):
        lms.LineMoveModel.from_params({**params, "thresholds": {"spreads": -0.25, "totals": 0.5}})

    # (4) non-default elo_params
    with pytest.raises(ModelRegistryError, match="default EloParams"):
        lms.LineMoveModel.from_params({**params, "elo_params": {"K": 32.0, "home_advantage": 90.0}})
    with pytest.raises(ModelRegistryError, match="default TotalsParams"):
        lms.LineMoveModel.from_params({**params, "totals_params": {"window": 5}})


# ------------------------------------------------------------------------------------------------ 7. points_clv


def test_points_clv_spreads_and_totals():
    # spreads home bet at -3 with home close -5 -> +2
    assert lmr.points_clv("spreads", "home", -3.0, -5.0) == pytest.approx(2.0)
    # away bet at +3 with home close -5 (away close +5) -> -2
    assert lmr.points_clv("spreads", "away", 3.0, -5.0) == pytest.approx(-2.0)
    # over 220.5 close 223 -> +2.5
    assert lmr.points_clv("totals", "over", 220.5, 223.0) == pytest.approx(2.5)
    # under 220.5 close 223 -> -2.5
    assert lmr.points_clv("totals", "under", 220.5, 223.0) == pytest.approx(-2.5)

    # model_picks and split_results direction and grouping
    t0, t1 = _utc(2026, 10, 22, 12, 0), _utc(2026, 10, 22, 22, 0)
    p = lm.GamePath(
        key="game:1",
        nba_game_id="0022600001",
        tip=_utc(2026, 10, 22, 23, 0),
        markets={
            "spreads": lm.OpenClose("spreads", t0, -3.0, (1.91, 1.91), t1, -5.0, (1.91, 1.91)),
            "totals": lm.OpenClose("totals", t0, 220.5, (1.91, 1.91), t1, 223.0, (1.91, 1.91)),
        },
        home_score=115,
        away_score=108,
    )
    assert lm.model_picks([p], {"game:1": -0.6}, "spreads", 0.5) == [(p, 1)]
    assert lm.model_picks([p], {"game:1": 0.6}, "spreads", 0.5) == [(p, -1)]
    assert lm.model_picks([p], {"game:1": 0.6}, "totals", 0.5) == [(p, 1)]
    splits = lm.split_results(
        [p],
        {"spreads": {"game:1": -0.6}, "totals": {"game:1": 0.6}},
        {"spreads": {"game:1": 12.0}, "totals": {"game:1": 18.0}},
        {"game:1": "2026-27"},
        seed=42,
        n_boot=20,
        thresholds=(0.5,),
    )
    assert [(g, r.market, r.n, r.clv_points[0]) for g, r in splits] == [
        ("2026-27", "spreads", 1, pytest.approx(2.0)),
        ("2026-27", "totals", 1, pytest.approx(2.5)),
    ]
