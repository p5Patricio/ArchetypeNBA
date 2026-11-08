"""
Walk-forward backtest of the game models against free historical market lines (read-only).

Question 1 (skill vs the close): does any model, or any model combined with the market, beat the de-vigged closing
market on the h2h outcome? Question 2 (the bettable one): can a model predict the move from the OPENING line to the
CLOSING line, i.e. earn closing-line value (CLV) by betting the open?

Everything is walk-forward by season: season ``T`` is predicted by models fitted only on seasons before ``T``
(Elo, the ``margin_features`` features and the totals model are leak-free single passes). Inputs are plain
objects (``HistoricalGame`` list from ``player_game_log``, lines keyed by ``nba_game_id``), so the run needs no
database write and the leak test can perturb a future season and check that earlier predictions do not move.

Models (h2h probability of a home win):

* ``market_close``  de-vigged close moneyline (proportional); spread-implied ``Phi(-close / sigma)`` when the game has
  no moneyline, sigma = std of (home margin + close spread) over past seasons.
* ``market_open``   spread-implied probability of the OPENING spread with the same sigma (sanity: the close should win).
* ``elo``           the champion's Elo (default ``EloParams``: home edge 60, tuned in-sample on 2021-22..2025-26).
* ``margin_features`` the challenger family refitted every season on all past seasons (first season = burn-in).
* ``elo_blend``     ``logit_blend(elo, market, w)`` with ``w`` from ``fit_blend_weight`` on past seasons.
* ``mkt_offset``    L2 logistic regression on ``logit(p_market)`` (free coefficient) plus the 12 standardized
  features; ``mkt_offset_fixed`` keeps the market as an offset (coefficient 1). Penalty by expanding-window CV.
* ``*_avail_ub``    the same plus missing-rotation impact from ``player_game_log`` (who actually played): post-game
  knowledge, an UPPER BOUND, never deployable (train/serve skew; see ``app.analytics.availability``).

Opening-line value (spreads, and totals with ``totals_pace``): a strategy picks a side per game from information
known at the open; CLV in points is ``side * (open - close)`` for spreads (home +1) and ``side * (close - open)``
for totals (over +1); its probability equivalent uses the normal margin model around the close. Realized results
at the opening number are priced at an ASSUMED -110 (the archives carry no spread or total prices). Naive
strategies (always home, open favourite, open underdog, a seeded coin flip, always over/under) show what noise
looks like.
"""
import math
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np

from app.analytics import historical_lines as hl
from app.analytics.betting_policy import fit_blend_weight, logit_blend
from app.analytics.elo import EloParams
from app.analytics.features import FEATURE_NAMES, build_feature_set
from app.analytics.multiple_testing import dm_hln_test
from app.analytics.totals_model import build_totals_feature_set
from app.services.elo_service import HistoricalGame
from app.services.margin_features_model import MarginFeaturesModel, fit_margin_features

PROB_EPS = 1e-6
L2_GRID = (0.1, 1.0, 10.0, 100.0, 1000.0)
RIDGE_GRID = (0.1, 1.0, 10.0, 100.0, 1000.0, 10000.0)
INNER_CV_SEASONS = 3
SPREAD_GAP_EDGES = (0.0, 1.0, 2.0, 3.0, 5.0)
MOVE_EDGES = (0.0, 0.25, 0.5, 1.0)
TOTAL_GAP_EDGES = (0.0, 2.0, 4.0, 6.0, 10.0)
MAX_ABS_SPREAD = 30.0  # a larger NBA spread is a typo
TOTAL_RANGE = (150.0, 300.0)  # NBA totals 2007-2026 sit well inside this range
ROBUST_MOVE = {"spread": 4.0, "total": 8.0}  # sensitivity: drop games whose line moved more (news or data errors)
_IDX = {name: i for i, name in enumerate(FEATURE_NAMES)}


@dataclass(frozen=True)
class GameLines:
    """The market lines of one game, from the home side (spread < 0: home favoured). NaN-free: None = missing."""

    source: str
    open_spread_home: Optional[float] = None
    close_spread_home: Optional[float] = None
    open_total: Optional[float] = None
    close_total: Optional[float] = None
    close_moneyline_home: Optional[int] = None
    close_moneyline_away: Optional[int] = None


@dataclass
class BacktestConfig:
    seed: int = 42
    n_boot: int = 1000
    min_line_seasons: int = 2  # past seasons with lines needed before a season is evaluated
    fit_margin_features: bool = True
    export_season: Optional[str] = None  # season label whose walk-forward fits are exported (``BacktestResult.exports``)


@dataclass
class BacktestResult:
    """Per-game arrays (index = position in ``games``) plus the season bookkeeping. NaN = no prediction."""

    game_ids: Tuple[str, ...]
    season_labels: List[str]
    season_of_game: np.ndarray  # index into season_labels
    eval_mask: np.ndarray  # games of evaluated seasons with a market probability
    margin: np.ndarray
    home_win: np.ndarray
    game_total: np.ndarray
    lines: Dict[str, np.ndarray]  # open_s, close_s, open_t, close_t
    probs: Dict[str, np.ndarray]  # model name -> P(home win)
    margins: Dict[str, np.ndarray]  # mu_elo, mu_mf, mu_total, pred_move_spread, pred_move_total, ...
    sigma_spread: np.ndarray  # per game: the walk-forward sigma of its season (margin around the close)
    sigma_total: np.ndarray
    blend_weights: Dict[str, float] = field(default_factory=dict)
    evaluated_seasons: List[str] = field(default_factory=list)
    implausible_values: int = 0
    b2b_any: Optional[np.ndarray] = None  # either team played the day before
    exports: Dict[str, object] = field(default_factory=dict)  # fits used to predict ``config.export_season``


# ------------------------------------------------------------------------------------------------ small fitters

def _logit(p: np.ndarray) -> np.ndarray:
    p = np.clip(p, PROB_EPS, 1.0 - PROB_EPS)
    return np.log(p / (1.0 - p))


def _sigmoid(z: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-z))


def fit_logistic(F: np.ndarray, y: np.ndarray, offset: Optional[np.ndarray] = None, l2: float = 1.0,
                 max_iter: int = 50) -> Tuple[np.ndarray, float]:
    """L2 logistic regression by Newton's method (deterministic): (coef, intercept); the intercept is not penalized."""
    n, k = F.shape
    off = np.zeros(n) if offset is None else offset
    A = np.hstack([np.ones((n, 1)), F])
    beta = np.zeros(k + 1)
    penalty = np.full(k + 1, l2)
    penalty[0] = 0.0
    for _ in range(max_iter):
        p = _sigmoid(A @ beta + off)
        grad = A.T @ (y - p) - penalty * beta
        w = p * (1.0 - p)
        hess = (A * w[:, None]).T @ A + np.diag(penalty) + 1e-9 * np.eye(k + 1)
        step = np.linalg.solve(hess, grad)
        beta = beta + step
        if np.max(np.abs(step)) < 1e-8:
            break
    return beta[1:], float(beta[0])


def fit_ridge(F: np.ndarray, y: np.ndarray, alpha: float) -> Tuple[np.ndarray, float]:
    """Closed-form ridge on centered columns (the intercept is not penalized)."""
    mean_f, mean_y = F.mean(axis=0), float(y.mean())
    Fc = F - mean_f
    coef = np.linalg.solve(Fc.T @ Fc + alpha * np.eye(F.shape[1]), Fc.T @ (y - mean_y))
    return coef, mean_y - float(mean_f @ coef)


def _standardize(train: np.ndarray, *others: np.ndarray) -> List[np.ndarray]:
    mean, scale = train.mean(axis=0), train.std(axis=0)
    scale[scale < 1e-12] = 1.0
    return [(m - mean) / scale for m in (train, *others)]


def _inner_folds(season_idx: np.ndarray, n_folds: int = INNER_CV_SEASONS) -> List[Tuple[np.ndarray, np.ndarray]]:
    seasons = sorted(set(season_idx.tolist()))
    return [(season_idx < s, season_idx == s) for s in seasons[1:][-n_folds:]]


def _select(grid: Sequence[float], folds, score: Callable[[float, np.ndarray, np.ndarray], float], default: float) -> float:
    if not folds:
        return default
    totals = {g: sum(score(g, tr, va) for tr, va in folds) for g in grid}
    return min(grid, key=lambda g: (totals[g], g))


def _log_loss_sum(p: np.ndarray, y: np.ndarray) -> float:
    p = np.clip(p, PROB_EPS, 1.0 - PROB_EPS)
    return float(-np.sum(y * np.log(p) + (1.0 - y) * np.log(1.0 - p)))


def fit_predict_logistic(F_tr, y_tr, off_tr, s_tr, F_te, off_te) -> np.ndarray:
    """Standardize, choose the L2 penalty by expanding-window CV over past seasons, refit, predict."""
    def score(l2, tr, va):
        Ztr, Zva = _standardize(F_tr[tr], F_tr[va])
        coef, b = fit_logistic(Ztr, y_tr[tr], None if off_tr is None else off_tr[tr], l2)
        return _log_loss_sum(_sigmoid(Zva @ coef + b + (0 if off_tr is None else off_tr[va])), y_tr[va])

    l2 = _select(L2_GRID, _inner_folds(s_tr), score, 1.0)
    Ztr, Zte = _standardize(F_tr, F_te)
    coef, b = fit_logistic(Ztr, y_tr, off_tr, l2)
    return _sigmoid(Zte @ coef + b + (0 if off_te is None else off_te))


@dataclass(frozen=True)
class RidgeFit:
    """A standardized ridge fit, exportable as JSON: ``predict(F) = ((F - mean) / scale) @ coef + intercept``."""

    mean: Tuple[float, ...]
    scale: Tuple[float, ...]
    coef: Tuple[float, ...]
    intercept: float
    alpha: float
    n: int

    def predict(self, F: np.ndarray) -> np.ndarray:
        Z = (np.atleast_2d(np.asarray(F, dtype=float)) - np.asarray(self.mean)) / np.asarray(self.scale)
        return Z @ np.asarray(self.coef) + self.intercept

    def to_dict(self) -> Dict[str, object]:
        return {"mean": list(self.mean), "scale": list(self.scale), "coef": list(self.coef),
                "intercept": self.intercept, "alpha": self.alpha, "n": self.n}

    @classmethod
    def from_dict(cls, d: Mapping[str, object]) -> "RidgeFit":
        fit = cls(tuple(float(v) for v in d["mean"]), tuple(float(v) for v in d["scale"]),
                  tuple(float(v) for v in d["coef"]), float(d["intercept"]), float(d["alpha"]), int(d.get("n", 0)))
        if not (len(fit.mean) == len(fit.scale) == len(fit.coef)) or any(v <= 0 for v in fit.scale):
            raise ValueError("ridge params have inconsistent lengths or a non-positive scale")
        return fit


def fit_ridge_cv(F_tr, y_tr, s_tr) -> RidgeFit:
    """Standardize, choose the ridge penalty by expanding-window CV over past seasons, refit on everything."""
    def score(alpha, tr, va):
        Ztr, Zva = _standardize(F_tr[tr], F_tr[va])
        coef, b = fit_ridge(Ztr, y_tr[tr], alpha)
        r = y_tr[va] - (Zva @ coef + b)
        return float(r @ r)

    alpha = _select(RIDGE_GRID, _inner_folds(s_tr), score, 100.0)
    mean, scale = F_tr.mean(axis=0), F_tr.std(axis=0)
    scale[scale < 1e-12] = 1.0
    coef, b = fit_ridge((F_tr - mean) / scale, y_tr, alpha)
    return RidgeFit(tuple(mean.tolist()), tuple(scale.tolist()), tuple(coef.tolist()), float(b), float(alpha), len(y_tr))


def fit_predict_ridge(F_tr, y_tr, s_tr, F_te) -> np.ndarray:
    return fit_ridge_cv(F_tr, y_tr, s_tr).predict(F_te)


# ------------------------------------------------------------------------------------------------ move features
# One definition for the backtest, the registration script and live inference (no train/serve skew).

SCHEDULE_FEATURES = ("rest_diff", "b2b_home", "b2b_away", "games7_diff", "margin10_diff", "winpct_diff", "season_progress")
SPREAD_MOVE_FEATURES = ("mu_elo_plus_line", "mu_mf_plus_line", "line") + SCHEDULE_FEATURES
TOTAL_MOVE_FEATURES = ("mu_total_minus_line", "line", "rest_diff", "b2b_home", "b2b_away", "games7_diff", "season_progress")


def schedule_features(X: np.ndarray) -> np.ndarray:
    """Schedule/form columns (``SCHEDULE_FEATURES``) from rows of the ``FEATURE_NAMES`` matrix."""
    X = np.atleast_2d(X)
    return np.column_stack([
        X[:, _IDX["rest_home"]] - X[:, _IDX["rest_away"]],
        X[:, _IDX["b2b_home"]], X[:, _IDX["b2b_away"]],
        X[:, _IDX["games7_home"]] - X[:, _IDX["games7_away"]],
        X[:, _IDX["margin10_home"]] - X[:, _IDX["margin10_away"]],
        X[:, _IDX["winpct_home"]] - X[:, _IDX["winpct_away"]],
        X[:, _IDX["season_progress"]],
    ])


def spread_move_features(mu_elo, mu_mf, line, sched: np.ndarray) -> np.ndarray:
    """``SPREAD_MOVE_FEATURES``: model margins vs the (home) line we would bet, the line, schedule/form."""
    mu_elo, mu_mf, line = (np.atleast_1d(np.asarray(v, dtype=float)) for v in (mu_elo, mu_mf, line))
    return np.column_stack([mu_elo + line, mu_mf + line, line, np.atleast_2d(sched)])


def total_move_features(mu_total, line, sched: np.ndarray) -> np.ndarray:
    """``TOTAL_MOVE_FEATURES``: totals model vs the total we would bet, the total, schedule (no form diffs)."""
    mu_total, line = (np.atleast_1d(np.asarray(v, dtype=float)) for v in (mu_total, line))
    sched = np.atleast_2d(sched)
    return np.column_stack([mu_total - line, line, sched[:, :4], sched[:, [6]]])


# ------------------------------------------------------------------------------------------------ the run

def _arr(values) -> np.ndarray:
    return np.array([np.nan if v is None else float(v) for v in values], dtype=float)


def _plausible(values: np.ndarray, lo: float, hi: float) -> np.ndarray:
    """Values outside [lo, hi] (archive typos such as a total of 1955.5) become missing; counted by the caller."""
    out = values.copy()
    out[(out < lo) | (out > hi)] = np.nan
    return out


def run_backtest(
    games: Sequence[HistoricalGame],
    season_label_of: Mapping[int, str],
    lines: Mapping[str, GameLines],
    config: Optional[BacktestConfig] = None,
    availability: Optional[Mapping[str, Tuple[float, float]]] = None,
    feature_overrides: Optional[Mapping[str, Tuple[np.ndarray, float]]] = None,
) -> BacktestResult:
    """
    Walk-forward predictions for every game. ``games`` must be chronological (``EloRatingService.load_games``);
    ``lines`` maps ``nba_game_id`` to the market lines; ``availability`` (optional, UPPER BOUND) maps
    ``nba_game_id`` to (missing impact home, missing impact away). ``feature_overrides`` maps ``nba_game_id`` to
    (``FEATURE_NAMES`` row, totals mu) computed as of an instant (``line_movement.features_as_of``); those rows
    replace the date-based pass everywhere (training and test).
    """
    config = config or BacktestConfig()
    n = len(games)
    fs, _ = build_feature_set(games, EloParams())
    totals_fs, _ = build_totals_feature_set(games)
    X = fs.X.copy()
    mu_total = totals_fs.mu.copy()
    if feature_overrides:
        for i, g in enumerate(games):
            override = feature_overrides.get(g.game_id)
            if override is not None:
                X[i] = override[0]
                mu_total[i] = override[1]
    labels = sorted({season_label_of[g.season_id] for g in games})
    s_index = {label: i for i, label in enumerate(labels)}
    season = np.array([s_index[season_label_of[g.season_id]] for g in games], dtype=int)
    margin, home_win = fs.margin, fs.home_win
    game_total = np.array([g.home_pts + g.away_pts for g in games], dtype=float)

    gl = [lines.get(g.game_id) for g in games]
    open_s = _plausible(_arr(l.open_spread_home if l else None for l in gl), -MAX_ABS_SPREAD, MAX_ABS_SPREAD)
    close_s = _plausible(_arr(l.close_spread_home if l else None for l in gl), -MAX_ABS_SPREAD, MAX_ABS_SPREAD)
    open_t = _plausible(_arr(l.open_total if l else None for l in gl), *TOTAL_RANGE)
    close_t = _plausible(_arr(l.close_total if l else None for l in gl), *TOTAL_RANGE)
    implausible = int(sum(np.isnan(a).sum() for a in (open_s, close_s, open_t, close_t))) - int(sum(
        sum(1 for l in gl if l is None or getattr(l, attr) is None)
        for attr in ("open_spread_home", "close_spread_home", "open_total", "close_total")
    ))
    p_ml = _arr(hl.devig_moneyline(l.close_moneyline_home, l.close_moneyline_away) if l else None for l in gl)

    edge = X[:, _IDX["elo_edge"]]
    p_elo = 1.0 / (1.0 + 10.0 ** (-edge / 400.0))
    mu_elo = edge / EloParams().elo_per_point

    nan = lambda: np.full(n, np.nan)  # noqa: E731
    p_mf, mu_mf, sig_s, sig_t = nan(), nan(), nan(), nan()
    p_close, p_open = nan(), nan()
    p_blend, p_off, p_off_fixed, p_off_av = nan(), nan(), nan(), nan()
    move_s, move_s_av, move_s_nomodel, move_t = nan(), nan(), nan(), nan()
    has_av = availability is not None
    miss = np.array([availability.get(g.game_id, (np.nan, np.nan)) if has_av else (np.nan, np.nan) for g in games], dtype=float)

    has_lines = np.array([l is not None for l in gl])
    line_seasons = sorted({season[i] for i in range(n) if has_lines[i]})
    result = BacktestResult(
        game_ids=fs.game_ids, season_labels=labels, season_of_game=season, eval_mask=np.zeros(n, dtype=bool),
        margin=margin, home_win=home_win, game_total=game_total,
        lines={"open_s": open_s, "close_s": close_s, "open_t": open_t, "close_t": close_t},
        probs={}, margins={}, sigma_spread=sig_s, sigma_total=sig_t, implausible_values=implausible,
        b2b_any=(X[:, _IDX["b2b_home"]] + X[:, _IDX["b2b_away"]]) > 0,
    )

    sched = schedule_features(X)

    for k in line_seasons:
        test = season == k
        past = season < k
        # --- margin_features, refit on every past season but the first (burn-in), as deployed
        train_mf = past & (season > 0)
        exporting = config.export_season is not None and labels[k] == config.export_season
        if config.fit_margin_features and len(set(season[train_mf].tolist())) >= 1:
            params = fit_margin_features(X[train_mf], margin[train_mf], home_win[train_mf], season[train_mf], seed=config.seed)
            p, mu = MarginFeaturesModel(params).predict_matrix(X[test])
            p_mf[test], mu_mf[test] = p, mu
            if exporting:
                result.exports["margin_features"] = params
        # --- market sigmas from past seasons only
        ok_s = past & ~np.isnan(close_s)
        if ok_s.sum() >= 30:
            sig_s[test] = float(np.std(margin[ok_s] + close_s[ok_s]))
        ok_t = past & ~np.isnan(close_t)
        if ok_t.sum() >= 30:
            sig_t[test] = float(np.std(game_total[ok_t] - close_t[ok_t]))
        if exporting:
            result.exports["sigma_spread"] = float(sig_s[test][0]) if test.any() else float("nan")
            result.exports["sigma_total"] = float(sig_t[test][0]) if test.any() else float("nan")
        if not np.isnan(sig_s[test]).all():
            sigma = sig_s[test][0]
            from_spread = np.array([hl.spread_implied_prob(v, sigma) if not np.isnan(v) else np.nan for v in close_s[test]])
            p_close[test] = np.where(np.isnan(p_ml[test]), from_spread, p_ml[test])
            p_open[test] = np.array([hl.spread_implied_prob(v, sigma) if not np.isnan(v) else np.nan for v in open_s[test]])
        else:
            p_close[test] = p_ml[test]

        past_line_seasons = sorted({int(s) for s in season[past & ~np.isnan(p_close)]})
        if len(past_line_seasons) < config.min_line_seasons:
            continue
        result.evaluated_seasons.append(labels[k])

        # --- models that need the market, trained on past seasons with a market probability
        tr = past & ~np.isnan(p_close)
        w_used, _, _ = fit_blend_weight(p_elo[tr].tolist(), p_close[tr].tolist(), home_win[tr].tolist())
        result.blend_weights[labels[k]] = w_used
        te = test & ~np.isnan(p_close)
        p_blend[te] = [logit_blend(a, b, w_used) for a, b in zip(p_elo[te], p_close[te])]
        lm_tr, lm_te = _logit(p_close[tr]), _logit(p_close[te])
        F_tr = np.column_stack([lm_tr, X[tr]])
        F_te = np.column_stack([lm_te, X[te]])
        p_off[te] = fit_predict_logistic(F_tr, home_win[tr], None, season[tr], F_te, None)
        p_off_fixed[te] = fit_predict_logistic(X[tr], home_win[tr], lm_tr, season[tr], X[te], lm_te)
        if has_av:
            tr_av, te_av = tr & ~np.isnan(miss[:, 0]), te & ~np.isnan(miss[:, 0])
            if tr_av.sum() and te_av.sum():
                p_off_av[te_av] = fit_predict_logistic(
                    np.column_stack([_logit(p_close[tr_av]), X[tr_av], miss[tr_av]]), home_win[tr_av], None, season[tr_av],
                    np.column_stack([_logit(p_close[te_av]), X[te_av], miss[te_av]]), None,
                )

        # --- line-move models: target close - open, trained on past seasons with walk-forward model margins
        def move_features(mask, with_av=False):
            F = spread_move_features(mu_elo[mask], mu_mf[mask], open_s[mask], sched[mask])
            return np.column_stack([F, miss[mask]]) if with_av else F

        base_ok = ~np.isnan(open_s) & ~np.isnan(close_s) & ~np.isnan(mu_mf)
        tr_m, te_m = past & base_ok, test & ~np.isnan(open_s) & ~np.isnan(mu_mf)
        if exporting and tr_m.sum() >= 100:
            result.exports["spreads"] = fit_ridge_cv(move_features(tr_m), close_s[tr_m] - open_s[tr_m], season[tr_m])
            result.exports["spreads_train_seasons"] = sorted({labels[int(v)] for v in season[tr_m]})
        if tr_m.sum() >= 100 and te_m.sum():
            move_s[te_m] = fit_predict_ridge(move_features(tr_m), close_s[tr_m] - open_s[tr_m], season[tr_m], move_features(te_m))
            # ablation: the same regression without the two model-vs-open gaps (open line and schedule only)
            move_s_nomodel[te_m] = fit_predict_ridge(
                move_features(tr_m)[:, 2:], close_s[tr_m] - open_s[tr_m], season[tr_m], move_features(te_m)[:, 2:]
            )
            if has_av:
                av_ok = ~np.isnan(miss[:, 0])
                tr_a, te_a = tr_m & av_ok, te_m & av_ok
                if tr_a.sum() >= 100 and te_a.sum():
                    move_s_av[te_a] = fit_predict_ridge(
                        move_features(tr_a, True), close_s[tr_a] - open_s[tr_a], season[tr_a], move_features(te_a, True)
                    )
        tot_ok = ~np.isnan(open_t) & ~np.isnan(close_t)
        tr_t, te_t = past & tot_ok, test & ~np.isnan(open_t)

        def tot_features(mask):
            return total_move_features(mu_total[mask], open_t[mask], sched[mask])

        if exporting and tr_t.sum() >= 100:
            result.exports["totals"] = fit_ridge_cv(tot_features(tr_t), close_t[tr_t] - open_t[tr_t], season[tr_t])
            result.exports["totals_train_seasons"] = sorted({labels[int(v)] for v in season[tr_t]})
        if tr_t.sum() >= 100 and te_t.sum():
            move_t[te_t] = fit_predict_ridge(tot_features(tr_t), close_t[tr_t] - open_t[tr_t], season[tr_t], tot_features(te_t))

        result.eval_mask |= te

    result.probs = {
        "market_close": p_close, "market_open": p_open, "elo": p_elo, "margin_features": p_mf,
        "elo_blend": p_blend, "mkt_offset": p_off, "mkt_offset_fixed": p_off_fixed,
    }
    if has_av:
        result.probs["mkt_offset_avail_ub"] = p_off_av
    result.margins = {
        "mu_elo": mu_elo, "mu_mf": mu_mf, "mu_total": mu_total, "move_spread": move_s, "move_total": move_t,
        "move_spread_no_model": move_s_nomodel,
    }
    if has_av:
        result.margins["move_spread_avail_ub"] = move_s_av
    return result


# ------------------------------------------------------------------------------------------------ statistics

def boot_mean_ci(values: np.ndarray, rng: np.random.Generator, n_boot: int) -> Tuple[float, float, float]:
    """Mean and a percentile 95% interval from a seeded iid bootstrap over games."""
    v = np.asarray(values, dtype=float)
    if len(v) == 0:
        return float("nan"), float("nan"), float("nan")
    means = np.empty(n_boot)
    chunk = max(1, min(n_boot, 2_000_000 // max(1, len(v))))
    done = 0
    while done < n_boot:
        m = min(chunk, n_boot - done)
        idx = rng.integers(0, len(v), size=(m, len(v)))
        means[done:done + m] = v[idx].mean(axis=1)
        done += m
    return float(v.mean()), float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def calibration(p: np.ndarray, y: np.ndarray) -> Tuple[float, float]:
    """(slope, intercept) of a logistic regression of the outcome on logit(p); (1, 0) is perfect calibration."""
    coef, b = fit_logistic(_logit(p)[:, None], y, None, 0.0)
    return float(coef[0]), b


@dataclass
class ProbRow:
    model: str
    n: int
    brier: float
    log_loss: float
    gap: Tuple[float, float, float]  # Brier(model) - Brier(market close): mean, lo, hi
    ll_gap: Tuple[float, float, float]
    dm_p: Optional[float]
    slope: float
    intercept: float


def probability_table(res: BacktestResult, rng: np.random.Generator, n_boot: int,
                      season_mask: Optional[np.ndarray] = None) -> List[ProbRow]:
    # common games: every model except the opening-line market (no open after 2022-23) and upper bounds
    mask = res.eval_mask & np.all(
        [~np.isnan(p) for name, p in res.probs.items() if not name.endswith("_ub") and name != "market_open"], axis=0
    )
    if season_mask is not None:
        mask &= season_mask
    y = res.home_win
    base = res.probs["market_close"]
    rows = []
    for name, p in res.probs.items():
        m = mask & ~np.isnan(p)
        if m.sum() < 30:
            continue
        b_model, b_mkt = (p[m] - y[m]) ** 2, (base[m] - y[m]) ** 2
        pc, bc = np.clip(p[m], PROB_EPS, 1 - PROB_EPS), np.clip(base[m], PROB_EPS, 1 - PROB_EPS)
        ll_model = -(y[m] * np.log(pc) + (1 - y[m]) * np.log(1 - pc))
        ll_mkt = -(y[m] * np.log(bc) + (1 - y[m]) * np.log(1 - bc))
        dm = dm_hln_test(b_mkt - b_model) if name != "market_close" else None
        slope, intercept = calibration(p[m], y[m])
        rows.append(ProbRow(
            name, int(m.sum()), float(b_model.mean()), float(ll_model.mean()),
            boot_mean_ci(b_model - b_mkt, rng, n_boot), boot_mean_ci(ll_model - ll_mkt, rng, n_boot),
            None if dm is None else dm.p_value, slope, intercept,
        ))
    return rows


@dataclass
class ClvRow:
    strategy: str
    bucket: str
    n: int
    clv_pts: Tuple[float, float, float]
    clv_prob: Tuple[float, float, float]
    toward: float
    against: float
    unchanged: float
    ats_win: float  # share of decided bets won at the opening number
    roi: Tuple[float, float, float]  # profit per unit at an ASSUMED -110


def clv_rows(strategy: str, side: np.ndarray, strength: np.ndarray, open_l: np.ndarray, close_l: np.ndarray,
             outcome_value: np.ndarray, sigma: np.ndarray, edges: Sequence[float], kind: str,
             rng: np.random.Generator, n_boot: int, cumulative: bool = True) -> List[ClvRow]:
    """
    CLV of betting ``side`` (+1 home/over, -1 away/under, 0 = no bet) at the open, by bucket of ``strength``.
    ``kind`` 'spread' (``outcome_value`` = home margin) or 'total' (``outcome_value`` = game total).
    """
    base = (side != 0) & ~np.isnan(open_l) & ~np.isnan(close_l) & ~np.isnan(sigma) & ~np.isnan(strength)
    if kind == "spread":
        clv = side * (open_l - close_l)
        outcome = np.sign(side * (outcome_value + open_l))
    else:
        clv = side * (close_l - open_l)
        outcome = np.sign(side * (outcome_value - open_l))
    win_profit = hl.american_to_decimal(hl.ASSUMED_PRICE_AMERICAN) - 1.0
    profit = np.where(outcome > 0, win_profit, np.where(outcome < 0, -1.0, 0.0))
    rows = []
    buckets = []
    for i, lo in enumerate(edges):
        hi = edges[i + 1] if i + 1 < len(edges) else math.inf
        buckets.append((f"[{lo:g}, {hi:g})" if hi != math.inf else f">= {lo:g}", (strength >= lo) & (strength < hi)))
    if cumulative:
        for lo in edges[1:]:
            buckets.append((f"all >= {lo:g}", strength >= lo))
    for label, sel in buckets:
        m = base & sel
        k = int(m.sum())
        if k == 0:
            continue
        c = clv[m]
        prob = np.array([hl.clv_probability(v, s) for v, s in zip(c, sigma[m])])
        decided = outcome[m] != 0
        rows.append(ClvRow(
            strategy, label, k, boot_mean_ci(c, rng, n_boot), boot_mean_ci(prob, rng, n_boot),
            float((c > 0).mean()), float((c < 0).mean()), float((c == 0).mean()),
            float((outcome[m][decided] > 0).mean()) if decided.any() else float("nan"),
            boot_mean_ci(profit[m], rng, n_boot),
        ))
    return rows


def spread_strategies(res: BacktestResult, seed: int) -> Dict[str, Tuple[np.ndarray, np.ndarray, Sequence[float]]]:
    """name -> (side, strength, bucket edges) for the spread market."""
    open_s = res.lines["open_s"]
    n = len(open_s)
    out = {}
    for name, mu in (("elo_vs_open", res.margins["mu_elo"]), ("margin_features_vs_open", res.margins["mu_mf"])):
        gap = mu + open_s  # > 0: the model rates home better than the opening line does
        out[name] = (np.sign(np.nan_to_num(gap)), np.abs(gap), SPREAD_GAP_EDGES)
    for key in ("move_spread", "move_spread_avail_ub"):
        if key in res.margins:
            move = res.margins[key]  # predicted close - open: negative = home will be bet up
            label = "line_move_model" if key == "move_spread" else "line_move_model_avail_UPPER_BOUND"
            out[label] = (-np.sign(np.nan_to_num(move)), np.abs(move), MOVE_EDGES)
    if "move_spread_no_model" in res.margins:
        move = res.margins["move_spread_no_model"]
        out["line_move_ablation_no_model_gaps"] = (-np.sign(np.nan_to_num(move)), np.abs(move), MOVE_EDGES)
    ones = np.ones(n)
    out["naive_always_home"] = (ones, ones, (0.0,))
    fav = -np.sign(np.nan_to_num(open_s))  # +1 when home is favoured at the open; 0 at pk
    out["naive_open_favourite"] = (fav, ones, (0.0,))
    out["naive_open_underdog"] = (-fav, ones, (0.0,))
    coin = np.random.default_rng(seed).choice([-1.0, 1.0], size=n)
    out["naive_coin_flip"] = (coin, ones, (0.0,))
    return out


def total_strategies(res: BacktestResult) -> Dict[str, Tuple[np.ndarray, np.ndarray, Sequence[float]]]:
    open_t = res.lines["open_t"]
    ones = np.ones(len(open_t))
    gap = res.margins["mu_total"] - open_t
    out = {"totals_pace_vs_open": (np.sign(np.nan_to_num(gap)), np.abs(gap), TOTAL_GAP_EDGES)}
    move = res.margins["move_total"]
    out["totals_move_model"] = (np.sign(np.nan_to_num(move)), np.abs(move), MOVE_EDGES)
    out["naive_always_over"] = (ones, ones, (0.0,))
    out["naive_always_under"] = (-ones, ones, (0.0,))
    return out


# ------------------------------------------------------------------------------------------------ report

def _ci(t: Tuple[float, float, float], fmt: str = "{:+.4f}") -> str:
    return f"{fmt.format(t[0])} ({fmt.format(t[1])} .. {fmt.format(t[2])})"


def format_report(res: BacktestResult, config: BacktestConfig, header: Sequence[str] = ()) -> str:
    rng = np.random.default_rng(config.seed)
    out: List[str] = ["# Historical backtest (walk-forward, read-only)", ""]
    out += list(header)
    ev = res.eval_mask
    out += [
        "",
        f"Evaluated seasons: {', '.join(res.evaluated_seasons) or 'none'}; games with a market probability: {int(ev.sum())}.",
        f"Bootstrap: {config.n_boot} iid resamples over games, seed {config.seed}; 95% percentile intervals.",
        "",
        "## 1. Skill against the closing market (h2h, home win)",
        "",
        "Brier gap = model Brier - market-close Brier (negative = the model beats the close). DM p = two-sided "
        "Diebold-Mariano (HLN) on the per-game Brier difference. Calibration: logistic slope/intercept of the outcome "
        "on logit(p) (1/0 is perfect). Same games for every row (the `_ub` row: games with availability data).",
        "",
        "| model | n | Brier | log loss | Brier gap (95% CI) | log-loss gap (95% CI) | DM p | slope | intercept |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in probability_table(res, rng, config.n_boot):
        out.append(
            f"| {r.model} | {r.n} | {r.brier:.4f} | {r.log_loss:.4f} | {_ci(r.gap)} | {_ci(r.ll_gap)} | "
            f"{'-' if r.dm_p is None else f'{r.dm_p:.3f}'} | {r.slope:.3f} | {r.intercept:+.3f} |"
        )
    out += ["", "Brier gap to the close by season (model - market):", ""]
    names = [n for n in res.probs if n != "market_close"]
    out.append("| season | n | " + " | ".join(names) + " |")
    out.append("|---|---|" + "---|" * len(names))
    for label in res.evaluated_seasons:
        sm = res.season_of_game == res.season_labels.index(label)
        rows = {r.model: r for r in probability_table(res, rng, 200, sm)}
        if "market_close" not in rows:
            continue
        cells = [f"{rows[n].gap[0]:+.4f}" if n in rows else "-" for n in names]
        out.append(f"| {label} | {rows['market_close'].n} | " + " | ".join(cells) + " |")
    out += ["", "Fitted elo_blend weight w_used per season (0 = the market alone): "
            + ", ".join(f"{k} {v:.2f}" for k, v in res.blend_weights.items())]

    for market, strategies, outcome, sigma, close_key, open_key in (
        ("spread", spread_strategies(res, config.seed), res.margin, res.sigma_spread, "close_s", "open_s"),
        ("total", total_strategies(res), res.game_total, res.sigma_total, "close_t", "open_t"),
    ):
        open_l, close_l = res.lines[open_key], res.lines[close_key]
        moved = ev & ~np.isnan(open_l) & ~np.isnan(close_l)
        if not moved.any():
            continue
        d = close_l[moved] - open_l[moved]
        out += [
            "",
            f"## {'2' if market == 'spread' else '3'}. Opening-line value: {market}s",
            "",
            f"Games with open and close: {int(moved.sum())}; close - open: mean {d.mean():+.3f}, sd {d.std():.3f}, "
            f"unchanged {np.mean(d == 0):.1%}, |move| > 3: {int((np.abs(d) > 3).sum())}, |move| > 6: {int((np.abs(d) > 6).sum())} "
            f"(kept: real news or data errors cannot be told apart). Walk-forward sigma around the close: "
            f"{np.nanmean(sigma[moved]):.2f} points. Implausible archive values set to missing (|spread| > "
            f"{MAX_ABS_SPREAD:g}, total outside {TOTAL_RANGE[0]:g}-{TOTAL_RANGE[1]:g}), all line fields: {res.implausible_values}.",
            "",
            "CLV pts = mean points gained against the close by betting the open; CLV prob = the same on the "
            "probability scale; toward/against/unch = share of bets whose close moved toward / against the bet / "
            "not at all; ATS win = share of decided bets won at the opening number; ROI = profit per unit at an "
            "ASSUMED -110 price (the archives have no spread/total prices).",
            "",
            "| strategy | bucket | n | CLV pts (95% CI) | CLV prob (95% CI) | toward | against | unch | ATS win | ROI @-110 ASSUMED (95% CI) |",
            "|---|---|---|---|---|---|---|---|---|---|",
        ]
        for name, (side, strength, edges) in strategies.items():
            s = np.where(ev, side, 0.0)
            for r in clv_rows(name, s, strength, open_l, close_l, outcome, sigma, edges, market, rng, config.n_boot,
                              cumulative=len(edges) > 1):
                out.append(
                    f"| {r.strategy} | {r.bucket} | {r.n} | {_ci(r.clv_pts, '{:+.3f}')} | {_ci(r.clv_prob)} | "
                    f"{r.toward:.1%} | {r.against:.1%} | {r.unchanged:.1%} | {r.ats_win:.1%} | {_ci(r.roi, '{:+.3f}')} |"
                )
        headline = {k: v for k, v in strategies.items() if not k.startswith("naive")}
        limit = ROBUST_MOVE[market]
        small = ~(np.abs(close_l - open_l) > limit)
        sens = [(f"|close - open| <= {limit:g} (drops news and data errors alike)", small)]
        if market == "spread" and res.b2b_any is not None:
            sens.append(("no back-to-back team (the open may predate yesterday's result)", ~res.b2b_any))
        for title, keep in sens:
            out += ["", f"Sensitivity, {market}s, {title}:", "",
                    "| strategy | bucket | n | CLV pts (95% CI) | toward | against | ATS win | ROI @-110 ASSUMED (95% CI) |",
                    "|---|---|---|---|---|---|---|---|"]
            for name, (side, strength, edges) in headline.items():
                s = np.where(ev & keep, side, 0.0)
                rows = clv_rows(name, s, strength, open_l, close_l, outcome, sigma, edges, market, rng, config.n_boot)
                for r in (r for r in rows if r.bucket.startswith("all")):
                    out.append(
                        f"| {r.strategy} | {r.bucket} | {r.n} | {_ci(r.clv_pts, '{:+.3f}')} | {r.toward:.1%} | "
                        f"{r.against:.1%} | {r.ats_win:.1%} | {_ci(r.roi, '{:+.3f}')} |"
                    )
        out += ["", f"By season ({market}s; the model strategies at their second-largest cumulative threshold):", ""]
        out.append("| season | " + " | ".join(f"{k} (n, CLV pts, ROI)" for k in headline) + " |")
        out.append("|---|" + "---|" * len(headline))
        for label in res.evaluated_seasons:
            sm = ev & (res.season_of_game == res.season_labels.index(label))
            cells = []
            for name, (side, strength, edges) in headline.items():
                thr = edges[-2] if len(edges) > 1 else edges[0]
                s = np.where(sm & (strength >= thr), side, 0.0)
                rows = clv_rows(name, s, strength, open_l, close_l, outcome, sigma, (thr,), market, rng, 200, cumulative=False)
                cells.append(f"{rows[0].n}, {rows[0].clv_pts[0]:+.3f}, {rows[0].roi[0]:+.3f}" if rows else "-")
            out.append(f"| {label} | " + " | ".join(cells) + " |")
    return "\n".join(out)


# ------------------------------------------------------------------------------------------------ availability (UB)

@dataclass(frozen=True)
class PlayerLine:
    """One player's box score in one game (``team_id`` canonical); ``score`` = Game Score."""

    game_id: str
    team_id: int
    player_id: int
    minutes: float
    score: float


def availability_upper_bound(
    games: Sequence[HistoricalGame], player_lines: Sequence[PlayerLine],
    min_mpg: float = 15.0, min_gp: int = 5, replacement_rate: float = 0.20,
) -> Dict[str, Tuple[float, float]]:
    """
    ``nba_game_id`` -> (missing impact home, missing impact away): the summed impact of the team's rotation players
    (>= ``min_gp`` games and ``min_mpg`` minutes for the team this season, from games on EARLIER dates) who did not
    play this game. Impact = mpg * max(0, GameScore per minute - replacement). A player who later appears for
    another team leaves the old roster. Who played is post-game knowledge: this is an UPPER BOUND on what a
    pre-game injury report gives (train/serve skew), used only as a labelled positive control.
    """
    from app.analytics.availability import compute_player_impact

    by_game: Dict[str, List[PlayerLine]] = {}
    for line in player_lines:
        if line.minutes > 0:
            by_game.setdefault(line.game_id, []).append(line)
    # (season, team) -> player -> [gp, minutes, score]
    stats: Dict[Tuple[int, int], Dict[int, List[float]]] = {}
    current_team: Dict[Tuple[int, int], int] = {}  # (season, player) -> team of the latest appearance
    out: Dict[str, Tuple[float, float]] = {}

    def missing(season_id: int, team_id: int, played: set) -> float:
        total = 0.0
        for player, (gp, minutes, score) in stats.get((season_id, team_id), {}).items():
            if player in played or current_team.get((season_id, player)) != team_id:
                continue
            if gp >= min_gp and minutes / gp >= min_mpg:
                total += compute_player_impact(minutes / gp, score / minutes, replacement_rate)
        return total

    i = 0
    while i < len(games):
        day = games[i].game_date
        j = i
        while j < len(games) and games[j].game_date == day:
            j += 1
        batch = games[i:j]
        for g in batch:  # state strictly before this date
            played = {pl.player_id for pl in by_game.get(g.game_id, [])}
            if not played:
                continue
            out[g.game_id] = (missing(g.season_id, g.home_team_id, played), missing(g.season_id, g.away_team_id, played))
        for g in batch:
            for pl in by_game.get(g.game_id, []):
                rec = stats.setdefault((g.season_id, pl.team_id), {}).setdefault(pl.player_id, [0, 0.0, 0.0])
                rec[0] += 1
                rec[1] += pl.minutes
                rec[2] += pl.score
                current_team[(g.season_id, pl.player_id)] = pl.team_id
        i = j
    return out
