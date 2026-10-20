"""
``margin_features``: a ridge regression for the home margin plus a logistic regression for P(home win) on the
leak-free game features of ``app.analytics.features``.

Training (``fit_margin_features``) standardizes the features with the training means and scales, picks the ridge
penalty and the logistic C by expanding-window time-series cross-validation over the last training seasons, and sets
sigma to the std of the out-of-fold ridge residuals. scikit-learn is used for the logistic fit only and is imported
lazily, so inference never needs it.

Everything inference needs is a JSON-serializable ``params`` dict (``model_version.params``): feature names, scaler,
coefficients, intercepts, penalties, sigma, and the provenance (trained_through, seasons, seed, reference Elo
parameters). No pickles. ``MarginFeaturesModel`` is numpy-only and ``MarginFeaturesFamily`` plugs it into the model
registry: it builds the features of an upcoming game from the database history at call time (one history load per
family instance, i.e. per process) and returns ``None`` when a team has no history.
"""
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
from sqlmodel import Session

from app.analytics.elo import EloParams
from app.analytics.features import FEATURE_NAMES, FeatureSet, FeatureState, GameLike, build_feature_set
from app.models import ModelVersion
from app.services.model_registry import ModelRegistryError, Prediction, register_family

FAMILY_NAME = "margin_features"

RIDGE_ALPHAS = (1.0, 10.0, 30.0, 100.0, 300.0, 1000.0, 3000.0, 10000.0)
LOGISTIC_CS = (0.003, 0.01, 0.03, 0.1, 0.3, 1.0)
CV_SEASONS = 5  # validation folds: the last 5 training seasons, each predicted by all seasons before it
DEFAULT_ALPHA = 300.0
DEFAULT_C = 0.1
_MIN_SCALE = 1e-12
_PROB_EPS = 1e-6
# NBA tip-offs fall between 12:00 and 23:00 Eastern; shifting a UTC instant back this many hours lands on the
# calendar date player_game_log uses, without needing a timezone database.
NBA_DAY_SHIFT = timedelta(hours=6)


# ------------------------------------------------------------------------------------------------ training

def _fit_scaler(X: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    mean = X.mean(axis=0)
    scale = X.std(axis=0)
    scale[scale < _MIN_SCALE] = 1.0
    return mean, scale


def _fit_ridge(Z: np.ndarray, y: np.ndarray, alpha: float) -> Tuple[np.ndarray, float]:
    """Closed-form ridge on centered features: (coef, intercept); the intercept is not penalized."""
    y_mean = float(y.mean())
    gram = Z.T @ Z + alpha * np.eye(Z.shape[1])
    coef = np.linalg.solve(gram, Z.T @ (y - y_mean))
    return coef, y_mean


def _fit_logistic(Z: np.ndarray, y: np.ndarray, c: float, seed: int) -> Tuple[np.ndarray, float]:
    from sklearn.linear_model import LogisticRegression  # training only; inference is numpy-only

    model = LogisticRegression(C=c, solver="lbfgs", max_iter=1000, random_state=seed)
    model.fit(Z, y)
    return model.coef_[0], float(model.intercept_[0])


def _log_loss(p: np.ndarray, y: np.ndarray) -> float:
    p = np.clip(p, _PROB_EPS, 1.0 - _PROB_EPS)
    return float(-np.mean(y * np.log(p) + (1.0 - y) * np.log(1.0 - p)))


def _sigmoid(z: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-z))


def _time_series_folds(season_rank: np.ndarray, n_folds: int) -> List[Tuple[np.ndarray, np.ndarray]]:
    """(train_mask, validation_mask) per fold: validate on one of the last seasons, train on every season before."""
    ranks = sorted(set(season_rank.tolist()))
    folds = []
    for rank in ranks[1:][-n_folds:]:  # the first season has nothing before it
        folds.append((season_rank < rank, season_rank == rank))
    return folds


def fit_margin_features(
    X: np.ndarray,
    margin: np.ndarray,
    home_win: np.ndarray,
    season_rank: np.ndarray,
    *,
    seed: int,
    elo_params: Optional[EloParams] = None,
    trained_through: Optional[date] = None,
    seasons: Sequence[str] = (),
    alphas: Sequence[float] = RIDGE_ALPHAS,
    cs: Sequence[float] = LOGISTIC_CS,
    cv_seasons: int = CV_SEASONS,
) -> Dict[str, Any]:
    """
    Fit both heads on ``X`` (rows in chronological order, ``season_rank`` = chronological season index) and
    return the JSON-serializable ``params``. The penalties come from expanding-window time-series CV inside the
    training rows; with a single season there is nothing to validate on and the defaults apply.
    """
    folds = _time_series_folds(season_rank, cv_seasons)

    alpha, c = DEFAULT_ALPHA, DEFAULT_C
    if folds:
        sq_err = {a: 0.0 for a in alphas}
        oof: Dict[float, List[np.ndarray]] = {a: [] for a in alphas}
        ll = {cc: 0.0 for cc in cs}
        for train, val in folds:
            mean, scale = _fit_scaler(X[train])
            Z_train, Z_val = (X[train] - mean) / scale, (X[val] - mean) / scale
            for a in alphas:
                coef, intercept = _fit_ridge(Z_train, margin[train], a)
                residual = margin[val] - (Z_val @ coef + intercept)
                sq_err[a] += float(residual @ residual)
                oof[a].append(residual)
            for cc in cs:
                coef, intercept = _fit_logistic(Z_train, home_win[train], cc, seed)
                ll[cc] += _log_loss(_sigmoid(Z_val @ coef + intercept), home_win[val]) * int(val.sum())
        alpha = min(alphas, key=lambda a: (sq_err[a], a))
        c = min(cs, key=lambda cc: (ll[cc], cc))
        sigma = float(np.std(np.concatenate(oof[alpha])))
    mean, scale = _fit_scaler(X)
    Z = (X - mean) / scale
    ridge_coef, ridge_intercept = _fit_ridge(Z, margin, alpha)
    if not folds:
        sigma = float(np.std(margin - (Z @ ridge_coef + ridge_intercept)))
    logit_coef, logit_intercept = _fit_logistic(Z, home_win, c, seed)

    return {
        "feature_names": list(FEATURE_NAMES),
        "mean": [float(v) for v in mean],
        "scale": [float(v) for v in scale],
        "ridge": {"coef": [float(v) for v in ridge_coef], "intercept": float(ridge_intercept), "alpha": float(alpha)},
        "logistic": {"coef": [float(v) for v in logit_coef], "intercept": float(logit_intercept), "C": float(c)},
        "sigma": sigma,
        "trained_through": trained_through.isoformat() if trained_through else None,
        "seasons": list(seasons),
        "n_train": int(len(X)),
        "seed": int(seed),
        "elo_params": (elo_params or EloParams()).to_dict(),
    }


def fit_on_feature_set(
    feature_set: FeatureSet, train_mask: np.ndarray, *, seed: int, elo_params: Optional[EloParams] = None,
    trained_through: Optional[date] = None, seasons: Sequence[str] = (),
) -> Dict[str, Any]:
    """``fit_margin_features`` on the rows selected by ``train_mask`` of a feature set."""
    return fit_margin_features(
        feature_set.X[train_mask],
        feature_set.margin[train_mask],
        feature_set.home_win[train_mask],
        feature_set.season_rank[train_mask],
        seed=seed,
        elo_params=elo_params,
        trained_through=trained_through,
        seasons=seasons,
    )


# ---------------------------------------------------------------------------------------------- inference

class MarginFeaturesModel:
    """numpy-only inference from a ``params`` dict."""

    def __init__(self, params: Mapping[str, Any]):
        try:
            self.feature_names = tuple(params["feature_names"])
            self.mean = np.array(params["mean"], dtype=float)
            self.scale = np.array(params["scale"], dtype=float)
            self.ridge_coef = np.array(params["ridge"]["coef"], dtype=float)
            self.ridge_intercept = float(params["ridge"]["intercept"])
            self.logit_coef = np.array(params["logistic"]["coef"], dtype=float)
            self.logit_intercept = float(params["logistic"]["intercept"])
            self.sigma = float(params["sigma"])
            self.elo_params = EloParams.from_dict(params.get("elo_params") or {})
        except (KeyError, TypeError, ValueError) as exc:
            raise ModelRegistryError(f"margin_features params are incomplete or malformed: {exc!r}") from exc
        if self.feature_names != FEATURE_NAMES:
            raise ModelRegistryError(
                f"margin_features was trained on features {list(self.feature_names)}, this code builds {list(FEATURE_NAMES)}"
            )
        if self.sigma <= 0:
            raise ModelRegistryError("margin_features params have no positive sigma")

    def predict_matrix(self, X: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """(p_home, mu) for each feature row."""
        Z = (np.atleast_2d(X) - self.mean) / self.scale
        mu = Z @ self.ridge_coef + self.ridge_intercept
        p_home = np.clip(_sigmoid(Z @ self.logit_coef + self.logit_intercept), _PROB_EPS, 1.0 - _PROB_EPS)
        return p_home, mu

    def predict_vector(self, x: np.ndarray) -> Prediction:
        p_home, mu = self.predict_matrix(x)
        return Prediction(float(p_home[0]), float(mu[0]), self.sigma)


def nba_date(game_time: datetime) -> date:
    """Calendar date (as in player_game_log) of a tip-off given as a UTC (or naive UTC) datetime."""
    return (game_time - NBA_DAY_SHIFT).date()


class MarginFeaturesFamily:
    """``margin_features`` in the model registry: features for an upcoming game come from the database history."""

    def __init__(self, session: Session, model_version: ModelVersion):
        self.name = model_version.name
        self.version = model_version.version
        self.model_version_id = model_version.id
        self._model = MarginFeaturesModel(model_version.params or {})
        self._session = session
        self._games: Optional[List[GameLike]] = None
        self._state: Optional[FeatureState] = None
        self._past: Optional[Tuple[date, FeatureState]] = None  # state restricted to games before a date

    def _history(self) -> Tuple[List[GameLike], FeatureState]:
        if self._games is None:
            from app.services.elo_service import EloRatingService  # lazy: elo_service imports the registry

            self._games = EloRatingService(self._session).load_games()
            self._state = build_feature_set(self._games, self._model.elo_params)[1]
        return self._games, self._state

    def _state_before(self, teams: Sequence[int], day: date) -> FeatureState:
        """History state usable for a game on ``day``: the full one unless these teams already played on/after it."""
        games, state = self._history()
        if all((state.team_last_game_date(t) or date.min) < day for t in teams):
            return state
        if self._past is None or self._past[0] != day:
            self._past = (day, build_feature_set([g for g in games if g.game_date < day], self._model.elo_params)[1])
        return self._past[1]

    def predict(
        self, home_team_id: int, away_team_id: int, season_id: int, game_time: datetime
    ) -> Optional[Prediction]:
        day = nba_date(game_time)
        state = self._state_before((home_team_id, away_team_id), day)
        if not (state.knows(home_team_id) and state.knows(away_team_id)):
            return None
        return self._model.predict_vector(state.vector(home_team_id, away_team_id, season_id, day))


register_family(FAMILY_NAME, MarginFeaturesFamily)
