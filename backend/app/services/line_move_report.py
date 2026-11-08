"""
The ``line_move`` LIVE TEST in numbers (D-71), read-only: paper bets, ROI with a bootstrap CI, Pinnacle CLV.

Two CLV views, because a strategy that bets where the line is going is penalized by a same-line price comparison:

* Pinnacle price CLV (``clv_report.build_pinnacle_clv_report`` restricted to ``line_move``): per game, price taken
  against Pinnacle's de-vigged close AT THE SAME LINE; a bet whose line moved is excluded (``line_moved``), which for
  this strategy drops the bets that worked best. Captured closes, plus a separate line including OddsPapi-recovered
  closes (``closing_oddspapi``).
* Points CLV: the bet's line against Pinnacle's closing line of the same market (captured close: the sharp book's
  last pre-tip quote of a game with a ``closing`` marker; recovered: the ``op_pinnacle`` path's last pre-tip quote),
  ``line_taken - close`` for a spread side's own line, ``close - line`` for an over and ``line - close`` for an under.
  Positive = the close moved our way. Seeded bootstrap CI over bets; "insufficient" under 30.
"""
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
from sqlalchemy import select
from sqlmodel import Session

from app.models import (
    CAPTURE_CLOSING,
    BetStatus,
    Game,
    MarketType,
    ModelPrediction,
    OddsSnapshotCapture,
    SimulatedBet,
    StakingStrategy,
)
from app.services import market_close
from app.services.clv_report import PinnacleClvReport, _load_pinnacle_quotes, build_pinnacle_clv_report

MIN_N = 30
SEED = 42
N_BOOT = 1000
_SETTLED = (BetStatus.won, BetStatus.lost, BetStatus.push)
_FIRST_SIDE = {MarketType.spreads.value: "home", MarketType.totals.value: "over"}


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _enum(value) -> str:
    return value.value if hasattr(value, "value") else str(value)


def boot_ci(values: Sequence[float], seed: int = SEED, n_boot: int = N_BOOT) -> Optional[Tuple[float, float, float]]:
    v = np.asarray(values, dtype=float)
    if len(v) == 0:
        return None
    idx = np.random.default_rng(seed).integers(0, len(v), size=(n_boot, len(v)))
    means = v[idx].mean(axis=1)
    return float(v.mean()), float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


@dataclass
class MarketLiveTest:
    market: str
    bets: int = 0
    settled: int = 0
    roi: Optional[Tuple[float, float, float]] = None
    points_clv: Optional[Tuple[float, float, float]] = None
    points_n: int = 0
    moved_our_way: Optional[float] = None


@dataclass
class LineMoveLiveTest:
    label: str = "LIVE TEST (paper only): line_move, D-71"
    model: Optional[str] = None  # registered model version, e.g. "line_move 1"
    bets: int = 0
    settled: int = 0
    pending: int = 0
    won: int = 0
    lost: int = 0
    push: int = 0
    pnl_units: float = 0.0
    roi: Optional[Tuple[float, float, float]] = None  # profit per unit staked, bootstrap over settled bets
    points_clv: Optional[Tuple[float, float, float]] = None
    points_n: int = 0
    points_n_recovered: int = 0
    moved_our_way: Optional[float] = None
    pinnacle_clv: Optional[PinnacleClvReport] = None
    markets: List[MarketLiveTest] = field(default_factory=list)


def _close_lines(session: Session, game_ids: List[int]) -> Dict[Tuple[int, str], Tuple[float, bool]]:
    """(game, market) -> (Pinnacle closing line of home/over, recovered?) from captured or recovered closes."""
    out: Dict[Tuple[int, str], Tuple[float, bool]] = {}
    if not game_ids:
        return out
    commence = {gid: _aware(c) for gid, c in session.execute(select(Game.id, Game.commence_time).where(Game.id.in_(game_ids)))}
    captured = {gid for (gid,) in session.execute(
        select(OddsSnapshotCapture.game_id).where(OddsSnapshotCapture.kind == CAPTURE_CLOSING,
                                                  OddsSnapshotCapture.game_id.in_(game_ids))
    )}
    recovered = market_close.recovered_close_game_ids(session) & set(game_ids)
    sources = []
    sharp = list(market_close.sharp_books(session).keys())
    if sharp and captured:
        sources.append((sorted(captured), sharp, False))
    op = list(market_close.oddspapi_pinnacle_book(session) or [])
    if op and recovered - captured:
        sources.append((sorted(recovered - captured), op, True))
    for ids, books, is_recovered in sources:
        for game_id, quotes in _load_pinnacle_quotes(session, ids, books).items():
            tip = commence.get(game_id)
            for market, first in _FIRST_SIDE.items():
                rows = [q for q in quotes if _enum(q.market) == market and _enum(q.side) == first
                        and q.line is not None and tip is not None and _aware(q.captured_at) <= tip]
                if rows:
                    out[(game_id, market)] = (float(rows[-1].line), is_recovered)  # rows are in capture order
    return out


def points_clv(market: str, side: str, line_taken: float, close_first_side_line: float) -> float:
    """Points gained against Pinnacle's close: positive when the close moved toward the bet."""
    if market == MarketType.spreads.value:
        close_own = close_first_side_line if side == "home" else -close_first_side_line
        return line_taken - close_own
    return close_first_side_line - line_taken if side == "over" else line_taken - close_first_side_line


def build_line_move_live_test(session: Session, now: Optional[datetime] = None) -> LineMoveLiveTest:
    from app.services.line_move_strategy import get_line_move_model

    now = _aware(now) if now is not None else datetime.now(timezone.utc)
    out = LineMoveLiveTest()
    row = get_line_move_model(session)
    out.model = f"{row.name} {row.version}" if row is not None else None
    rows = session.execute(
        select(SimulatedBet, ModelPrediction.game_id, ModelPrediction.market, ModelPrediction.side, Game.commence_time)
        .join(ModelPrediction, ModelPrediction.id == SimulatedBet.prediction_id)
        .join(Game, Game.id == ModelPrediction.game_id)
        .where(SimulatedBet.strategy == StakingStrategy.line_move)
        .order_by(SimulatedBet.id)
    ).all()
    out.bets = len(rows)
    if not rows:
        return out
    closes = _close_lines(session, sorted({r[1] for r in rows if _aware(r[4]) <= now}))
    profit: Dict[str, List[float]] = defaultdict(list)
    pts: Dict[str, List[float]] = defaultdict(list)
    by_market: Dict[str, MarketLiveTest] = {}
    n_rec = 0
    for bet, game_id, market, side, commence in rows:
        m, s = _enum(market), _enum(side)
        mk = by_market.setdefault(m, MarketLiveTest(m))
        mk.bets += 1
        if bet.status in _SETTLED:
            out.settled += 1
            mk.settled += 1
            per_unit = float(bet.profit_units or 0) / float(bet.stake_units)
            profit[m].append(per_unit)
            out.pnl_units += float(bet.profit_units or 0)
            out.won += bet.status == BetStatus.won
            out.lost += bet.status == BetStatus.lost
            out.push += bet.status == BetStatus.push
        elif bet.status == BetStatus.pending:
            out.pending += 1
        close = closes.get((game_id, m))
        if close is not None and bet.line_taken is not None:
            pts[m].append(points_clv(m, s, float(bet.line_taken), close[0]))
            n_rec += close[1]
    all_profit = [v for vs in profit.values() for v in vs]
    all_pts = [v for vs in pts.values() for v in vs]
    out.roi = boot_ci(all_profit)
    out.points_clv = boot_ci(all_pts)
    out.points_n, out.points_n_recovered = len(all_pts), n_rec
    out.moved_our_way = float(np.mean(np.asarray(all_pts) > 0)) if all_pts else None
    for m, mk in by_market.items():
        mk.roi = boot_ci(profit[m])
        mk.points_clv = boot_ci(pts[m])
        mk.points_n = len(pts[m])
        mk.moved_our_way = float(np.mean(np.asarray(pts[m]) > 0)) if pts[m] else None
    out.markets = [by_market[m] for m in (MarketType.spreads.value, MarketType.totals.value) if m in by_market]
    out.pinnacle_clv = build_pinnacle_clv_report(session, now, include_recovered=True,
                                                 strategies=(StakingStrategy.line_move.value,))
    return out


def _ci(t: Optional[Tuple[float, float, float]], fmt: str = "{:+.3f}") -> str:
    if t is None:
        return "n/a"
    return f"{fmt.format(t[0])} (95% CI {fmt.format(t[1])} .. {fmt.format(t[2])})"


def _flag(n: int) -> str:
    return f" [n {n} < {MIN_N}: insufficient]" if n < MIN_N else ""


def format_line_move_live_test(t: LineMoveLiveTest) -> List[str]:
    lines = [f"{t.label} ({t.model or 'model not registered'})",
             "  (own bankroll; excluded from the market breakdown, CLV coverage and per-game Pinnacle CLV lines above)"]
    if not t.bets:
        lines.append("  No line_move bets yet.")
        return lines
    lines.append(
        f"  bets {t.bets} (settled {t.settled}: {t.won}W {t.lost}L {t.push}P, pending {t.pending}) | P/L "
        f"{t.pnl_units:+.2f}u | ROI per unit {_ci(t.roi)}{_flag(t.settled)}"
    )
    lines.append(
        f"  points CLV vs Pinnacle's close {_ci(t.points_clv)} over {t.points_n} bets "
        f"({t.points_n_recovered} on recovered closes); close moved our way "
        f"{'n/a' if t.moved_our_way is None else f'{t.moved_our_way:.1%}'}{_flag(t.points_n)}"
    )
    p = t.pinnacle_clv
    if p is not None:
        def stats_line(s, label):
            if s is None or not s.n_games:
                return f"  Pinnacle price CLV, {label}: no game yet"
            lo = None if s.std_err is None else (s.mean_clv - 1.96 * s.std_err, s.mean_clv + 1.96 * s.std_err)
            ci = "n/a" if lo is None else f"{lo[0]:+.2%} .. {lo[1]:+.2%}"
            return f"  Pinnacle price CLV, {label}: games {s.n_games} | mean {s.mean_clv:+.2%} (95% CI {ci}){_flag(s.n_games)}"

        lines.append(stats_line(p.stats, "captured closes, same line only"))
        lines.append(stats_line(p.stats_with_recovered, "incl. OddsPapi-recovered closes"))
        lines.append(f"  (same-line exclusions: line moved {p.exclusions.line_moved}, no closing marker "
                     f"{p.exclusions.no_closing_marker}; a line move is this strategy's goal, see points CLV)")
    for mk in t.markets:
        lines.append(
            f"  {mk.market:<8} bets {mk.bets} (settled {mk.settled}) | ROI {_ci(mk.roi)} | points CLV "
            f"{_ci(mk.points_clv)} n {mk.points_n}{_flag(mk.points_n)}"
        )
    return lines
