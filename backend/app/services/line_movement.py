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
import bisect
import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
from sqlalchemy import select
from sqlmodel import Session

from app.analytics.props_engine import devig_two_way
from app.models import Game, OddsHistory, OddsPapiFixture, OddsPapiQuote, Sportsbook
from app.services.oddspapi import (
    OP_PINNACLE, OpenClose, PathPair, close_cutoff, main_line_pairs, open_close_from_pairs,
)

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
    pairs: Dict[str, List[PathPair]] = field(default_factory=dict)  # every stored main-line pair, chronological


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
            pairs = main_line_pairs(items)
            paths.append(GamePath(
                key=f"game:{game_id}", nba_game_id=g.nba_game_id if g else None,
                tip=_aware(g.commence_time) if g else None, markets=open_close_from_pairs(pairs), pairs=pairs,
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
            pairs = main_line_pairs(items)
            paths.append(GamePath(
                key=f"fixture:{fixture_row_id}", nba_game_id=f.nba_game_id if f else None,
                tip=_aware(f.true_start_time or f.start_time) if f else None, markets=open_close_from_pairs(pairs),
                pairs=pairs,
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


# ------------------------------------------------------------------------------------------------ leak-safe entry
#
# The features of a game (Elo, margin_features, rolling totals) include each team's PREVIOUS game, but Pinnacle's
# opener is typically ~22 h before the tip, often before last night's game ended. A bet is only honest at an
# instant when everything the features use is known: the BETTABLE instant. ``readiness_times`` gives, per game, the
# time both teams' previous games are final plus a safety margin; ``entry_quote`` the Pinnacle pair we could take
# then; ``features_as_of`` the features computed from games final by that instant only.

GAME_DURATION = timedelta(hours=3)  # tip to final, conservatively (overtime included); same as the results grace
SAFETY_MARGIN = timedelta(minutes=30)
END_OF_DAY_FINAL = time(7, 0)  # UTC, the day after the game: ~2-3 AM Eastern, after the latest NBA finish
ENTRY_FIRST_AFTER = "first_after"  # the first stored pair at or after the instant (conservative, the default)
ENTRY_IN_FORCE = "in_force"  # the pair in force at the instant (sensitivity)
ENTRY_RULES = (ENTRY_FIRST_AFTER, ENTRY_IN_FORCE)


def final_time(game_id: str, game_date: date, tips: Mapping[str, datetime]) -> Tuple[datetime, str]:
    """When a game is surely final: its tip + ``GAME_DURATION``, else the end-of-day rule. (time, source)."""
    tip = tips.get(game_id)
    if tip is not None:
        return _aware(tip) + GAME_DURATION, "tip"
    return datetime.combine(game_date + timedelta(days=1), END_OF_DAY_FINAL, tzinfo=timezone.utc), "end_of_day"


@dataclass(frozen=True)
class Readiness:
    """When the inputs of a game's features are all known: ``ready_at`` (None = no previous game in the data)."""

    game_id: str
    ready_at: Optional[datetime]
    source: str  # "tip", "end_of_day" (at least one previous game without a tip time) or "none"
    previous: Tuple[str, ...] = ()


def readiness_times(games: Sequence, tips: Mapping[str, datetime], margin: timedelta = SAFETY_MARGIN) -> Dict[str, Readiness]:
    """
    ``game_id`` -> Readiness for every game of ``games`` (objects with game_id, game_date, home/away_team_id, e.g.
    ``HistoricalGame``): the latest final time of the two teams' previous games (strictly earlier dates) plus
    ``margin``.
    """
    by_team: Dict[int, List[Tuple[date, str]]] = defaultdict(list)
    for g in games:
        by_team[g.home_team_id].append((g.game_date, g.game_id))
        by_team[g.away_team_id].append((g.game_date, g.game_id))
    for team in by_team.values():
        team.sort()
    dates = {g.game_id: g.game_date for g in games}
    out: Dict[str, Readiness] = {}
    for g in games:
        ends, sources, previous = [], [], []
        for team_id in (g.home_team_id, g.away_team_id):
            team = by_team[team_id]
            i = bisect.bisect_left(team, (g.game_date, ""))
            if i == 0:
                continue
            prev_id = team[i - 1][1]
            end, source = final_time(prev_id, dates[prev_id], tips)
            ends.append(end)
            sources.append(source)
            previous.append(prev_id)
        if not ends:
            out[g.game_id] = Readiness(g.game_id, None, "none")
            continue
        out[g.game_id] = Readiness(
            g.game_id, max(ends) + margin, "end_of_day" if "end_of_day" in sources else "tip", tuple(previous)
        )
    return out


def entry_quote(
    pairs: Sequence[PathPair], ready_at: Optional[datetime], rule: str = ENTRY_FIRST_AFTER
) -> Optional[Tuple[datetime, PathPair]]:
    """
    (bet instant, Pinnacle pair) for a bet placed at the bettable instant, or None when no pair qualifies.
    ``first_after``: the first stored pair at or after max(opener, ready_at); ``in_force``: the pair in force at that
    instant. ``pairs`` are pre-tip (stored paths are cut at the tip), so the entry is always before the tip.
    """
    if not pairs:
        return None
    if ready_at is None or _aware(ready_at) <= pairs[0][0]:
        return pairs[0][0], pairs[0]
    ready_at = _aware(ready_at)
    if rule == ENTRY_IN_FORCE:
        if ready_at > pairs[-1][0]:
            return None  # the last pre-tip quote is the close; nothing proves the market was still open after it
        in_force = [p for p in pairs if p[0] <= ready_at][-1]
        return ready_at, in_force
    if rule != ENTRY_FIRST_AFTER:
        raise ValueError(f"unknown entry rule {rule!r}")
    for p in pairs:
        if p[0] >= ready_at:
            return p[0], p
    return None


@dataclass
class EntryStats:
    games: int = 0
    with_readiness: Counter = field(default_factory=Counter)  # source -> games
    entries: Counter = field(default_factory=Counter)  # market -> games with an entry
    at_opener: Counter = field(default_factory=Counter)  # market -> entries that are the opener itself
    no_entry: Counter = field(default_factory=Counter)  # market -> no pair between the instant and the tip
    hours_before_tip: Dict[str, List[float]] = field(default_factory=lambda: defaultdict(list))
    hours_after_open: Dict[str, List[float]] = field(default_factory=lambda: defaultdict(list))


def entry_paths(
    paths: Sequence[GamePath], readiness: Mapping[str, Readiness], rule: str = ENTRY_FIRST_AFTER
) -> Tuple[List[GamePath], Dict[str, datetime], EntryStats]:
    """
    Copies of ``paths`` whose "open" is the entry at the bettable instant (close unchanged), the instant as of which
    the features of each game must be computed (``nba_game_id`` -> instant; never after any of its entries), and
    counts. Games without an ``nba_game_id`` or a readiness record are left out: their safety cannot be shown.
    """
    stats = EntryStats()
    out: List[GamePath] = []
    as_of: Dict[str, datetime] = {}
    for p in paths:
        r = readiness.get(p.nba_game_id) if p.nba_game_id else None
        if r is None or not p.pairs:
            continue
        stats.games += 1
        stats.with_readiness[r.source] += 1
        markets: Dict[str, OpenClose] = {}
        for market, pairs in p.pairs.items():
            if market == "h2h":
                continue
            hit = entry_quote(pairs, r.ready_at, rule)
            if hit is None:
                stats.no_entry[market] += 1
                continue
            at, (_, line, prices) = hit
            close_at, close_line, close_prices = pairs[-1]
            markets[market] = OpenClose(market, at, line, prices, close_at, close_line, close_prices)
            stats.entries[market] += 1
            if at == pairs[0][0]:
                stats.at_opener[market] += 1
            stats.hours_after_open[market].append((at - pairs[0][0]).total_seconds() / 3600.0)
            if p.tip is not None:
                stats.hours_before_tip[market].append((p.tip - at).total_seconds() / 3600.0)
        if not markets:
            continue
        opens = [pairs[0][0] for m, pairs in p.pairs.items() if m != "h2h" and pairs]
        as_of[p.nba_game_id] = max(r.ready_at, min(opens)) if r.ready_at is not None else min(opens)
        out.append(GamePath(p.key, p.nba_game_id, p.tip, markets, p.home_score, p.away_score, p.pairs))
    return out, as_of, stats


def features_as_of(
    games: Sequence, tips: Mapping[str, datetime], instants: Mapping[str, datetime]
) -> Tuple[Dict[str, Tuple[np.ndarray, float]], List[str]]:
    """
    ``game_id`` -> (``FEATURE_NAMES`` row, totals mu) of each target game, computed by ``FeatureState`` /
    ``TotalsState`` fed ONLY with games final (``final_time``) at or before the target's instant, in order of final
    time (a team's own games stay chronological, so its Elo chain is the date-based one). Second value: targets
    refused because a game of one of their teams on or after their date would have been fed (data inconsistency).
    """
    from app.analytics.elo import EloParams
    from app.analytics.features import FeatureState
    from app.analytics.totals_model import TotalsState

    finals = [final_time(g.game_id, g.game_date, tips)[0] for g in games]
    order = sorted(range(len(games)), key=lambda i: (finals[i], games[i].game_date, games[i].game_id))
    by_id = {g.game_id: g for g in games}
    state, totals = FeatureState(EloParams()), TotalsState()
    out: Dict[str, Tuple[np.ndarray, float]] = {}
    refused: List[str] = []
    ptr = 0
    for game_id, instant in sorted(instants.items(), key=lambda kv: (_aware(kv[1]), kv[0])):
        g = by_id.get(game_id)
        if g is None:
            continue
        instant = _aware(instant)
        while ptr < len(order) and finals[order[ptr]] <= instant:
            fed = games[order[ptr]]
            state.update(fed)
            totals.update(fed)
            ptr += 1
        last = [state.team_last_game_date(t) for t in (g.home_team_id, g.away_team_id)]
        if any(d is not None and d >= g.game_date for d in last):
            refused.append(game_id)
            continue
        out[game_id] = (
            state.vector(g.home_team_id, g.away_team_id, g.season_id, g.game_date),
            totals.predict_mu(g.home_team_id, g.away_team_id, g.season_id),
        )
    return out, refused


def load_tip_times(session: Session) -> Dict[str, datetime]:
    """``nba_game_id`` -> the LATEST known tip (``game.commence_time``, OddsPapi listed start and plausible real tip)."""
    tips: Dict[str, datetime] = {}

    def put(nba_id: Optional[str], value: Optional[datetime]) -> None:
        if nba_id and value is not None:
            value = _aware(value)
            if nba_id not in tips or value > tips[nba_id]:
                tips[nba_id] = value

    game_nba: Dict[int, str] = {}
    for gid, nba_id, commence in session.execute(select(Game.id, Game.nba_game_id, Game.commence_time)).all():
        if nba_id:
            game_nba[gid] = nba_id
        put(nba_id, commence)
    for game_id, nba_id, start, true_start in session.execute(
        select(OddsPapiFixture.game_id, OddsPapiFixture.nba_game_id, OddsPapiFixture.start_time,
               OddsPapiFixture.true_start_time)
    ).all():
        target = nba_id or game_nba.get(game_id)
        put(target, start)
        if true_start is not None and close_cutoff(_aware(start), _aware(true_start)) == _aware(true_start):
            put(target, true_start)
    return tips


# ------------------------------------------------------------------------------------------------ breakdowns

def is_small(result: StrategyResult) -> bool:
    return result.n < MIN_GAMES


def model_picks(
    paths: Sequence[GamePath], predicted: Mapping[str, float], market: str, threshold: float
) -> List[Tuple[GamePath, int]]:
    picks = []
    for p in paths:
        move = predicted.get(p.key)
        if market not in p.markets or move is None or math.isnan(move) or abs(move) < threshold:
            continue
        picks.append((p, (-1 if move > 0 else 1) if market == "spreads" else (1 if move > 0 else -1)))
    return picks


def split_results(
    paths: Sequence[GamePath], predicted: Mapping[str, Dict[str, float]], sigma: Mapping[str, Dict[str, float]],
    group_of: Mapping[str, str], seed: int, n_boot: int, thresholds: Sequence[float] = THRESHOLDS,
) -> List[Tuple[str, StrategyResult]]:
    """(group, result) of the model strategy per market and threshold within each group (``group_of[path.key]``)."""
    out = []
    groups = sorted({g for g in group_of.values()})
    for market in ("spreads", "totals"):
        for thr in thresholds:
            picks = model_picks(paths, predicted.get(market, {}), market, thr)
            for group in groups:
                sub = [(p, s) for p, s in picks if group_of.get(p.key) == group]
                out.append((group, evaluate_side(f"line_move_model >= {thr}", market, sub, sigma.get(market, {}), seed, n_boot)))
    return out


def format_rows(results: Sequence[Tuple[str, StrategyResult]], title: str) -> List[str]:
    """Every row with its n; rows under ``MIN_GAMES`` are printed but flagged ``[n < 30: insufficient]``."""
    lines = [title]
    for group, r in results:
        flag = f"  [n < {MIN_GAMES}: insufficient]" if is_small(r) else ""
        if r.n == 0:
            lines.append(f"  {group:<12} {r.market:<8} {r.name:<24} n 0")
            continue
        lines.append(
            f"  {group:<12} {r.market:<8} {r.name:<24} n {r.n:>4} | CLV points {_fmt_ci(r.clv_points)} | CLV prob "
            f"{_fmt_ci(r.clv_prob, '{:+.4f}')} | moved our way {r.beat_close:.1%} | ROI at Pinnacle's entry price "
            f"{_fmt_ci(r.roi_open_price)}{flag}"
        )
    return lines


def format_entry_stats(stats: EntryStats, rule: str) -> List[str]:
    lines = [
        f"Bettable instant: max(opener, previous games final + {int(SAFETY_MARGIN.total_seconds() // 60)} min), final = "
        f"tip + {GAME_DURATION.total_seconds() / 3600:g} h or {END_OF_DAY_FINAL.strftime('%H:%M')} UTC the next day "
        f"without a tip time; entry rule {rule}",
        f"  games {stats.games}; readiness from tip times {stats.with_readiness.get('tip', 0)}, end-of-day rule "
        f"{stats.with_readiness.get('end_of_day', 0)}, no previous game in the data {stats.with_readiness.get('none', 0)}",
    ]
    for market in ("spreads", "totals"):
        hb, ha = stats.hours_before_tip.get(market, []), stats.hours_after_open.get(market, [])
        lines.append(
            f"  {market:<8} entries {stats.entries.get(market, 0)} (at the opener {stats.at_opener.get(market, 0)}), "
            f"no quote between the instant and the tip {stats.no_entry.get(market, 0)}; median hours after the opener "
            f"{np.median(ha) if ha else float('nan'):.1f}, before the tip {np.median(hb) if hb else float('nan'):.1f}"
        )
    return lines
