"""
Pinnacle open-to-close movement from OddsPapi price paths, and the D-68 line-move model applied to it (read-only).

Per game (one ``op_pinnacle`` path in ``odds_history`` or one ``pinnacle`` path in ``oddspapi_quote``) the OPEN is
the first stored main-line pair and the CLOSE the last one; stored paths are cut at the real tip-off, so the close is
Pinnacle's last pre-tip quote (granularity: OddsPapi's ``createdAt``, typically seconds to a few minutes before the
tip). Lines are from the home side for spreads (negative = home favoured) and the total for totals.

The line-move model is the D-68 ridge regression of ``close - open`` on (Elo and ``margin_features`` gaps to the open,
the open line, schedule/form features), refitted walk-forward by ``historical_backtest.run_backtest``: a game of season
``T`` is predicted from seasons before ``T`` only (SBRO opens up to 2023-01, plus earlier OddsPapi seasons), so the
prediction for a live game never sees its own close. A strategy bets Pinnacle's OPENER on the side the close is
predicted to move toward when |predicted move| clears a threshold; CLV in points is ``side * (open - close)``
(spreads, home +1) or ``side * (close - open)`` (totals, over +1), and the realized result uses Pinnacle's actual
opening price (no assumed -110).
"""
import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
from sqlalchemy import select
from sqlmodel import Session

from app.analytics.props_engine import devig_two_way
from app.models import Game, OddsHistory, OddsPapiFixture, OddsPapiQuote, Sportsbook
from app.services.oddspapi import OP_PINNACLE, OpenClose, open_close

MIN_GAMES = 30
THRESHOLDS = (0.25, 0.5, 1.0)


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _enum(value) -> str:
    return value.value if hasattr(value, "value") else str(value)


@dataclass
class GamePath:
    key: str  # "game:<id>" or "fixture:<id>"
    nba_game_id: Optional[str]
    tip: Optional[datetime]
    markets: Dict[str, OpenClose]
    home_score: Optional[int] = None
    away_score: Optional[int] = None


def load_pinnacle_paths(session: Session) -> List[GamePath]:
    """Every game with a stored Pinnacle path: ``op_pinnacle`` rows of ``game`` rows plus ``oddspapi_quote`` rows."""
    paths: List[GamePath] = []
    book = session.execute(select(Sportsbook.id).where(Sportsbook.key == OP_PINNACLE)).scalar()
    if book is not None:
        rows: Dict[int, list] = defaultdict(list)
        for game_id, market, side, line, price_american, captured_at in session.execute(
            select(OddsHistory.game_id, OddsHistory.market, OddsHistory.side, OddsHistory.line,
                   OddsHistory.price_american, OddsHistory.captured_at)
            .where(OddsHistory.sportsbook_id == book, OddsHistory.player_id.is_(None))
        ).all():
            price = 1.0 + (price_american / 100.0 if price_american > 0 else 100.0 / abs(price_american))
            rows[game_id].append((_enum(market), _enum(side), None if line is None else float(line), price, captured_at))
        games = {
            g.id: g for g in session.execute(select(Game).where(Game.id.in_(list(rows)))).scalars()
        } if rows else {}
        for game_id, items in rows.items():
            g = games.get(game_id)
            paths.append(GamePath(
                key=f"game:{game_id}", nba_game_id=g.nba_game_id if g else None,
                tip=_aware(g.commence_time) if g else None, markets=open_close(items),
                home_score=g.home_score if g and g.status == "final" else None,
                away_score=g.away_score if g and g.status == "final" else None,
            ))
    rows2: Dict[int, list] = defaultdict(list)
    for fixture_row_id, market, side, line, price, created_at in session.execute(
        select(OddsPapiQuote.fixture_row_id, OddsPapiQuote.market, OddsPapiQuote.side, OddsPapiQuote.line,
               OddsPapiQuote.price_decimal, OddsPapiQuote.created_at).where(OddsPapiQuote.bookmaker == "pinnacle")
    ).all():
        rows2[fixture_row_id].append((_enum(market), _enum(side), None if line is None else float(line), float(price), created_at))
    if rows2:
        fixtures = {
            f.id: f for f in session.execute(select(OddsPapiFixture).where(OddsPapiFixture.id.in_(list(rows2)))).scalars()
        }
        for fixture_row_id, items in rows2.items():
            f = fixtures.get(fixture_row_id)
            paths.append(GamePath(
                key=f"fixture:{fixture_row_id}", nba_game_id=f.nba_game_id if f else None,
                tip=_aware(f.true_start_time or f.start_time) if f else None, markets=open_close(items),
            ))
    return paths


def attach_scores(paths: Sequence[GamePath], scores: Mapping[str, Tuple[int, int]]) -> None:
    """Fills missing final scores from ``player_game_log`` (nba_game_id -> (home pts, away pts))."""
    for p in paths:
        if p.home_score is None and p.nba_game_id in scores:
            p.home_score, p.away_score = scores[p.nba_game_id]


# ------------------------------------------------------------------------------------------------ statistics

def boot_ci(values: Sequence[float], seed: int, n_boot: int) -> Tuple[float, float, float]:
    v = np.asarray(values, dtype=float)
    if len(v) == 0:
        return float("nan"), float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(v), size=(n_boot, len(v)))
    means = v[idx].mean(axis=1)
    return float(v.mean()), float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


@dataclass
class MoveStats:
    market: str
    n: int
    mean: float = float("nan")
    ci: Tuple[float, float] = (float("nan"), float("nan"))
    sd: float = float("nan")
    mean_abs: float = float("nan")
    unchanged_share: float = float("nan")
    quantiles: Tuple[float, ...] = ()
    median_hours_open_to_close: float = float("nan")


def _h2h_home_prob(prices: Tuple[float, float]) -> float:
    return devig_two_way(prices[0], prices[1])[0]


def movement_stats(paths: Sequence[GamePath], seed: int = 42, n_boot: int = 1000) -> List[MoveStats]:
    out: List[MoveStats] = []
    for market in ("spreads", "totals", "h2h"):
        moves, hours = [], []
        for p in paths:
            oc = p.markets.get(market)
            if oc is None:
                continue
            if market == "h2h":
                moves.append(_h2h_home_prob(oc.close_prices) - _h2h_home_prob(oc.open_prices))
            else:
                moves.append(oc.close_line - oc.open_line)
            hours.append((oc.close_at - oc.open_at).total_seconds() / 3600.0)
        stats = MoveStats(market, len(moves))
        if moves:
            v = np.asarray(moves)
            mean, lo, hi = boot_ci(v, seed, n_boot)
            stats.mean, stats.ci = mean, (lo, hi)
            stats.sd = float(v.std(ddof=1)) if len(v) > 1 else float("nan")
            stats.mean_abs = float(np.abs(v).mean())
            stats.unchanged_share = float((np.abs(v) < 1e-9).mean())
            stats.quantiles = tuple(float(q) for q in np.percentile(v, [5, 25, 50, 75, 95]))
            stats.median_hours_open_to_close = float(np.median(hours))
        out.append(stats)
    return out


# ------------------------------------------------------------------------------------------------ strategies

@dataclass
class StrategyResult:
    name: str
    market: str
    n: int
    clv_points: Tuple[float, float, float] = (float("nan"),) * 3
    clv_prob: Tuple[float, float, float] = (float("nan"),) * 3
    beat_close: float = float("nan")
    roi_open_price: Tuple[float, float, float] = (float("nan"),) * 3  # realized at Pinnacle's actual opening price
    same_line_price_clv: Tuple[float, float, float] = (float("nan"),) * 3
    same_line_n: int = 0


def _normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def evaluate_side(
    name: str, market: str, picks: Sequence[Tuple[GamePath, int]], sigma: Mapping[str, float], seed: int, n_boot: int
) -> StrategyResult:
    """CLV and realized result of betting Pinnacle's opener on ``side`` (+1 home/over, -1 away/under) per game."""
    clv, clv_p, profit, price_clv = [], [], [], []
    for path, side in picks:
        oc = path.markets[market]
        if market == "spreads":
            points = side * (oc.open_line - oc.close_line)
        else:
            points = side * (oc.close_line - oc.open_line)
        clv.append(points)
        s = sigma.get(path.key)
        if s and not math.isnan(s):
            clv_p.append(_normal_cdf(points / s) - 0.5)
        price = oc.open_prices[0] if side > 0 else oc.open_prices[1]
        if oc.open_line == oc.close_line:
            fair = devig_two_way(oc.close_prices[0], oc.close_prices[1])
            price_clv.append(price * (fair[0] if side > 0 else fair[1]) - 1.0)
        if path.home_score is not None and path.away_score is not None:
            if market == "spreads":
                margin = (path.home_score - path.away_score) if side > 0 else (path.away_score - path.home_score)
                line = oc.open_line if side > 0 else -oc.open_line
                graded = margin + line
            else:
                total = path.home_score + path.away_score
                graded = (total - oc.open_line) * side
            profit.append(price - 1.0 if graded > 0 else -1.0 if graded < 0 else 0.0)
    res = StrategyResult(name, market, len(picks))
    if clv:
        res.clv_points = boot_ci(clv, seed, n_boot)
        res.beat_close = float(np.mean(np.asarray(clv) > 0))
    if clv_p:
        res.clv_prob = boot_ci(clv_p, seed, n_boot)
    if profit:
        res.roi_open_price = boot_ci(profit, seed, n_boot)
    if price_clv:
        res.same_line_price_clv = boot_ci(price_clv, seed, n_boot)
        res.same_line_n = len(price_clv)
    return res


def naive_strategies(paths: Sequence[GamePath], seed: int, n_boot: int) -> List[StrategyResult]:
    out = []
    for market in ("spreads", "totals"):
        have = [p for p in paths if market in p.markets]
        out.append(evaluate_side(f"naive_always_{'home' if market == 'spreads' else 'over'}", market,
                                 [(p, 1) for p in have], {}, seed, n_boot))
        if market == "spreads":
            fav = [(p, 1 if p.markets[market].open_line < 0 else -1) for p in have if p.markets[market].open_line != 0]
            out.append(evaluate_side("naive_open_favourite", market, fav, {}, seed, n_boot))
    return out


def model_strategies(
    paths: Sequence[GamePath], predicted: Mapping[str, Dict[str, float]], sigma: Mapping[str, Dict[str, float]],
    seed: int, n_boot: int,
) -> List[StrategyResult]:
    """``predicted[market][path.key]`` = predicted close - open; the bet side is where the close is going."""
    out = []
    for market in ("spreads", "totals"):
        pred = predicted.get(market, {})
        for thr in THRESHOLDS:
            picks = []
            for p in paths:
                move = pred.get(p.key)
                if market not in p.markets or move is None or math.isnan(move) or abs(move) < thr:
                    continue
                side = (-1 if move > 0 else 1) if market == "spreads" else (1 if move > 0 else -1)
                picks.append((p, side))
            out.append(evaluate_side(f"line_move_model >= {thr}", market, picks, sigma.get(market, {}), seed, n_boot))
    return out


def _fmt_ci(t: Tuple[float, float, float], fmt: str = "{:+.3f}") -> str:
    if any(math.isnan(x) for x in t):
        return "n/a"
    return f"{fmt.format(t[0])} ({fmt.format(t[1])} .. {fmt.format(t[2])})"


def format_movement(stats: Sequence[MoveStats]) -> List[str]:
    lines = ["Pinnacle open-to-close movement (main line; open = first stored pre-match quote, close = last pre-tip)"]
    for s in stats:
        unit = "prob (home, de-vigged)" if s.market == "h2h" else "points"
        if s.n < MIN_GAMES:
            lines.append(f"  {s.market:<8} n {s.n}: insufficient data (n < {MIN_GAMES})")
            continue
        q = ", ".join(f"{x:+.2f}" for x in s.quantiles)
        lines.append(
            f"  {s.market:<8} n {s.n} | mean move {s.mean:+.3f} {unit} (95% CI {s.ci[0]:+.3f} .. {s.ci[1]:+.3f}) | "
            f"sd {s.sd:.3f} | mean |move| {s.mean_abs:.3f} | unchanged {s.unchanged_share:.1%} | p5..p95 [{q}] | "
            f"median open-to-close {s.median_hours_open_to_close:.1f} h"
        )
    return lines


def format_strategies(results: Sequence[StrategyResult], title: str) -> List[str]:
    lines = [title]
    for r in results:
        if r.n < MIN_GAMES:
            lines.append(f"  {r.market:<8} {r.name:<26} n {r.n}: insufficient data (n < {MIN_GAMES})")
            continue
        lines.append(
            f"  {r.market:<8} {r.name:<26} n {r.n} | CLV points {_fmt_ci(r.clv_points)} | CLV prob "
            f"{_fmt_ci(r.clv_prob, '{:+.4f}')} | close moved our way {r.beat_close:.1%} | ROI at Pinnacle's opening "
            f"price {_fmt_ci(r.roi_open_price)} | price CLV when the line did not move (n {r.same_line_n}) "
            f"{_fmt_ci(r.same_line_price_clv, '{:+.4f}')}"
        )
    return lines
