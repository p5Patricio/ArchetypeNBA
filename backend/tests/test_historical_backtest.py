from dataclasses import replace
from datetime import date, timedelta
import random
from typing import Dict, List, Tuple

import numpy as np
import pytest

from app.services import historical_backtest as bt
from app.services.elo_service import HistoricalGame
from tests.synthetic_league import make_league


def _build_synthetic_setup(
    seed: int = 11,
) -> Tuple[List[HistoricalGame], Dict[int, str], Dict[str, bt.GameLines], bt.BacktestConfig]:
    games = make_league(n_seasons=6, n_teams=8, seed=seed)
    labels = {s: f"{2000+s}-{(s+1)%100:02d}" for s in range(1, 7)}
    rng = random.Random(seed)
    lines: Dict[str, bt.GameLines] = {}
    for g in games:
        if g.season_id >= 2:
            close_s = float(-round(2 * (g.home_pts - g.away_pts) * 0.3) / 2)
            open_s = close_s + rng.choice((-1.0, -0.5, 0.0, 0.5, 1.0))
            tot = g.home_pts + g.away_pts
            close_t = float(round(200.0 + (tot - 200.0) * 0.2))
            open_t = close_t + rng.choice((-1.0, -0.5, 0.0, 0.5, 1.0))
            if close_s < 0:
                ml_home, ml_away = -150, 130
            elif close_s > 0:
                ml_home, ml_away = 130, -150
            else:
                ml_home, ml_away = -110, -110
            lines[g.game_id] = bt.GameLines(
                source="sbro",
                close_spread_home=close_s,
                open_spread_home=open_s,
                close_total=close_t,
                open_total=open_t,
                close_moneyline_home=ml_home,
                close_moneyline_away=ml_away,
            )
    config = bt.BacktestConfig(seed=1, n_boot=50, min_line_seasons=2)
    return games, labels, lines, config


def test_run_backtest_shapes_and_evaluated_seasons():
    games, labels, lines, config = _build_synthetic_setup(seed=11)
    res = bt.run_backtest(games, labels, lines, config)

    n = len(games)
    assert len(res.margin) == n
    assert len(res.home_win) == n
    assert len(res.game_total) == n
    assert len(res.eval_mask) == n
    assert len(res.sigma_spread) == n
    assert len(res.sigma_total) == n

    for arr in res.lines.values():
        assert len(arr) == n

    for arr in res.probs.values():
        assert len(arr) == n

    for arr in res.margins.values():
        assert len(arr) == n

    # evaluated_seasons is non-empty and starts after two seasons with lines (lines begin in season 2 -> starts season 4)
    assert len(res.evaluated_seasons) > 0
    assert res.evaluated_seasons[0] == labels[4]
    assert res.evaluated_seasons == [labels[4], labels[5], labels[6]]

    # every probability in res.probs["market_close"] on res.eval_mask is in (0,1)
    assert res.eval_mask.sum() > 0
    p_close = res.probs["market_close"][res.eval_mask]
    assert np.all((p_close > 0.0) & (p_close < 1.0))


def test_backtest_leak_freeness():
    games, labels, lines, config = _build_synthetic_setup(seed=11)
    res1 = bt.run_backtest(games, labels, lines, config)

    # perturbed copy where every game of the LAST season gets different scores and lines
    perturbed_games = []
    perturbed_lines = dict(lines)
    for g in games:
        if g.season_id == 6:
            p_g = replace(g, home_pts=g.away_pts + 20, away_pts=g.home_pts)
            perturbed_games.append(p_g)
            if g.game_id in perturbed_lines:
                old_l = perturbed_lines[g.game_id]
                perturbed_lines[g.game_id] = replace(
                    old_l,
                    close_spread_home=old_l.close_spread_home + 5.0,
                    open_spread_home=(old_l.open_spread_home + 5.0) if old_l.open_spread_home is not None else None,
                )
        else:
            perturbed_games.append(g)

    res2 = bt.run_backtest(perturbed_games, labels, perturbed_lines, config)

    # for every index of games in seasons < last season, every array in res.probs and res.margins is identical
    # and sigma_spread/sigma_total too.
    mask_earlier = np.array([g.season_id < 6 for g in games])
    # not vacuous: the walk-forward models do predict earlier evaluated seasons (season 5 is trained on 1..4)
    season5 = np.array([g.season_id == 5 for g in games])
    for key in ("mkt_offset", "mkt_offset_fixed", "elo_blend", "margin_features"):
        assert not np.isnan(res1.probs[key][season5]).any(), key
    assert not np.isnan(res1.margins["move_spread"][season5]).any()
    assert not np.isnan(res1.margins["move_total"][season5]).any()

    for k, p1 in res1.probs.items():
        p2 = res2.probs[k]
        np.testing.assert_array_equal(p1[mask_earlier], p2[mask_earlier])

    for k, m1 in res1.margins.items():
        m2 = res2.margins[k]
        np.testing.assert_array_equal(m1[mask_earlier], m2[mask_earlier])

    np.testing.assert_array_equal(res1.sigma_spread[mask_earlier], res2.sigma_spread[mask_earlier])
    np.testing.assert_array_equal(res1.sigma_total[mask_earlier], res2.sigma_total[mask_earlier])


def test_clv_rows_spread_handmade():
    side = np.array([1.0, -1.0, 1.0])
    strength = np.ones(3)
    open_l = np.array([-3.0, -3.0, 2.0])
    close_l = np.array([-5.0, -5.0, 2.0])
    outcome_margin = np.array([10.0, 10.0, -1.0])
    sigma = np.full(3, 12.0)
    edges = (0.0,)
    rng = np.random.default_rng(0)

    rows = bt.clv_rows(
        "spread_test",
        side,
        strength,
        open_l,
        close_l,
        outcome_margin,
        sigma,
        edges,
        kind="spread",
        rng=rng,
        n_boot=20,
        cumulative=False,
    )

    assert len(rows) == 1
    r = rows[0]
    assert r.n == 3
    assert r.clv_pts[0] == pytest.approx(0.0)
    assert r.toward == pytest.approx(1 / 3)
    assert r.against == pytest.approx(1 / 3)
    assert r.unchanged == pytest.approx(1 / 3)
    assert r.ats_win == pytest.approx(2 / 3)
    assert r.roi[0] == pytest.approx((2 * (100 / 110) - 1) / 3)


def test_clv_rows_totals():
    side = np.array([1.0])
    strength = np.ones(1)
    open_l = np.array([210.0])
    close_l = np.array([212.0])
    outcome_total = np.array([215.0])
    sigma = np.full(1, 12.0)
    edges = (0.0,)
    rng = np.random.default_rng(0)

    rows = bt.clv_rows(
        "total_test",
        side,
        strength,
        open_l,
        close_l,
        outcome_total,
        sigma,
        edges,
        kind="total",
        rng=rng,
        n_boot=20,
        cumulative=False,
    )

    assert len(rows) == 1
    assert rows[0].clv_pts[0] == pytest.approx(2.0)


def test_fit_logistic():
    rng = np.random.default_rng(0)
    n = 4000
    x = rng.normal(0, 1, size=n)
    true_logit = 0.5 + 1.2 * x
    p = 1.0 / (1.0 + np.exp(-true_logit))
    y = rng.binomial(1, p)

    # fitted coef close to 1.2 (abs tol 0.15) with l2=0.0
    coef, _ = bt.fit_logistic(x[:, None], y, offset=None, l2=0.0)
    assert coef[0] == pytest.approx(1.2, abs=0.15)

    # with offset equal to the true logit and the same x, the fitted coef is near 0 (abs tol 0.15)
    coef_off, _ = bt.fit_logistic(x[:, None], y, offset=true_logit, l2=0.0)
    assert coef_off[0] == pytest.approx(0.0, abs=0.15)


def test_boot_mean_ci():
    rng = np.random.default_rng(42)
    ci = bt.boot_mean_ci(np.ones(10), rng, n_boot=50)
    assert ci == (1.0, 1.0, 1.0)

    arr = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    ci1 = bt.boot_mean_ci(arr, np.random.default_rng(123), n_boot=50)
    ci2 = bt.boot_mean_ci(arr, np.random.default_rng(123), n_boot=50)
    assert ci1 == ci2


def test_availability_upper_bound():
    games = [
        HistoricalGame(
            game_id=f"002010000{day}",
            game_date=date(2001, 10, 20) + timedelta(days=day),
            season_id=1,
            home_team_id=1,
            away_team_id=2,
            home_pts=100,
            away_pts=95,
        )
        for day in range(1, 8)
    ]

    player_lines = []
    # player 10 (team 1) plays 30 minutes with score 20 in games 1-6 and does not play game 7
    for day in range(1, 7):
        player_lines.append(
            bt.PlayerLine(
                game_id=f"002010000{day}",
                team_id=1,
                player_id=10,
                minutes=30.0,
                score=20.0,
            )
        )
    # player 20 (team 2) plays every game
    for day in range(1, 8):
        player_lines.append(
            bt.PlayerLine(
                game_id=f"002010000{day}",
                team_id=2,
                player_id=20,
                minutes=30.0,
                score=20.0,
            )
        )

    # a player who appears for team 2 after leaving team 1 is not counted as missing for team 1
    # player 30 plays games 1-5 for team 1, then game 6 for team 2
    for day in range(1, 6):
        player_lines.append(
            bt.PlayerLine(
                game_id=f"002010000{day}",
                team_id=1,
                player_id=30,
                minutes=25.0,
                score=15.0,
            )
        )
    player_lines.append(
        bt.PlayerLine(
            game_id="0020100006",
            team_id=2,
            player_id=30,
            minutes=25.0,
            score=15.0,
        )
    )

    result = bt.availability_upper_bound(games, player_lines)

    # result for games 1-6 has 0.0 for team 1 before player 10 reached 5 games (and when playing)
    for g in games[:6]:
        assert result[g.game_id][0] == 0.0

    # result[game7 id][0] (home side of team 1) > 0
    game7_id = games[6].game_id
    assert result[game7_id][0] > 0.0

    # impact is strictly from player 10 (30 * (20/30 - 0.2) = 14.0), player 30 is not counted for team 1
    assert result[game7_id][0] == pytest.approx(14.0)


def test_format_report():
    games, labels, lines, config = _build_synthetic_setup(seed=11)
    res = bt.run_backtest(games, labels, lines, config)
    report = bt.format_report(res, config)

    assert "Skill against the closing market" in report
    assert "Opening-line value: spreads" in report
