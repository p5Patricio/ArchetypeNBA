"""
Pure module: Pace/efficiency rolling totals model (numpy and standard library only, no I/O).

Mirrors the leak-free FeatureState pattern from app.analytics.features:
A single chronological pass over completed games maintains rolling combined points per team
and running season league totals, plus past residuals (actual total - mu).

For any upcoming or historical game:
- mu: pace/efficiency style estimate from each team's rolling combined points (points scored +
  allowed over the last N=10 games, shrunk toward the league mean of the season with a prior weight):
      T_home = (sum(recent_home_totals) + prior_weight * league_mean) / (n_home + prior_weight)
      T_away = (sum(recent_away_totals) + prior_weight * league_mean) / (n_away + prior_weight)
      mu = (T_home + T_away) / 2.0
- sigma: standard deviation of (actual total - mu) estimated from the SAME rolling procedure
  over past games only (no look-ahead). Defaults to default_sigma (17.7) when fewer than 2
  past residuals are available.
- p_over(line) = 1 - Phi((line + 0.0 - mu) / sigma).

Convention on pushes:
On half lines (e.g. 224.5), outcomes are strictly binary and push probability is zero.
On integer lines (e.g. 224.0), the point mass at the integer line is ignored under the
continuous normal distribution approximation: p_over(line) = 1 - Phi((line - mu) / sigma)
and p_under(line) = 1 - p_over(line) = Phi((line - mu) / sigma).
"""
from dataclasses import dataclass, field
from datetime import date
import math
from typing import Any, Dict, List, Optional, Protocol, Sequence, Tuple

import numpy as np

DEFAULT_WINDOW: int = 10
DEFAULT_PRIOR_WEIGHT: float = 5.0
DEFAULT_LEAGUE_TOTAL: float = 220.0
DEFAULT_SIGMA: float = 17.7
PROB_CLIP: float = 1e-5


class GameLike(Protocol):
    """Minimal interface needed from a completed game."""

    game_id: str
    game_date: date
    season_id: int
    home_team_id: int
    away_team_id: int
    home_pts: int
    away_pts: int


@dataclass(frozen=True)
class TotalsParams:
    """Hyperparameters for the pace-based totals model."""

    window: int = DEFAULT_WINDOW
    prior_weight: float = DEFAULT_PRIOR_WEIGHT
    default_league_total: float = DEFAULT_LEAGUE_TOTAL
    default_sigma: float = DEFAULT_SIGMA

    @classmethod
    def from_dict(cls, d: Optional[Dict[str, Any]] = None) -> "TotalsParams":
        if not d:
            return cls()
        return cls(
            window=int(d.get("window", DEFAULT_WINDOW)),
            prior_weight=float(d.get("prior_weight", DEFAULT_PRIOR_WEIGHT)),
            default_league_total=float(d.get("default_league_total", DEFAULT_LEAGUE_TOTAL)),
            default_sigma=float(d.get("default_sigma", DEFAULT_SIGMA)),
        )


def normal_cdf(z: float) -> float:
    """Standard normal cumulative distribution function Phi(z)."""
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def p_over(line: float, mu: float, sigma: float) -> float:
    """
    P(total > line) under Normal(mu, sigma^2).

    Convention: On half lines (e.g. 224.5), outcomes are binary and push probability is zero.
    On integer lines (e.g. 224.0), the point mass at the integer line is ignored under
    the continuous normal distribution approximation:
        p_over(line) = 1 - Phi((line + 0.0 - mu) / sigma).
    """
    if sigma <= 0.0:
        raise ValueError(f"sigma must be positive, got {sigma}")
    z = (float(line) - float(mu)) / float(sigma)
    p = 1.0 - normal_cdf(z)
    return float(np.clip(p, PROB_CLIP, 1.0 - PROB_CLIP))


def p_under(line: float, mu: float, sigma: float) -> float:
    """P(total < line) under Normal(mu, sigma^2). 1 - p_over(line, mu, sigma)."""
    return float(np.clip(1.0 - p_over(line, mu, sigma), PROB_CLIP, 1.0 - PROB_CLIP))


class _TeamTotalsHistory:
    __slots__ = ("totals",)

    def __init__(self) -> None:
        self.totals: List[float] = []


class _SeasonTotalsHistory:
    __slots__ = ("game_count", "total_points")

    def __init__(self) -> None:
        self.game_count: int = 0
        self.total_points: float = 0.0


class TotalsState:
    """
    Leak-free feature and parameter state for the rolling totals predictor.
    Updated strictly game by game in chronological order.
    """

    def __init__(self, params: Optional[TotalsParams] = None):
        self.params = params or TotalsParams()
        self._teams: Dict[int, _TeamTotalsHistory] = {}
        self._seasons: Dict[int, _SeasonTotalsHistory] = {}
        self._residuals: List[float] = []  # past (actual_total - mu)
        self.games_seen: int = 0

    def season_mean(self, season_id: int) -> float:
        """The season's running average game total, or default_league_total when empty."""
        season = self._seasons.get(season_id)
        if season is not None and season.game_count > 0:
            return season.total_points / season.game_count
        return self.params.default_league_total

    def team_rolling_total(self, team_id: int, season_id: int) -> float:
        """
        Team's rolling combined points over the last N games, shrunk toward the season
        league mean with prior_weight.
        """
        l_mean = self.season_mean(season_id)
        team = self._teams.get(team_id)
        if team is None or not team.totals:
            return l_mean
        recent = team.totals[-self.params.window :]
        n = len(recent)
        s = sum(recent)
        w = self.params.prior_weight
        return (s + w * l_mean) / (n + w)

    def current_sigma(self) -> float:
        """
        Standard deviation of past residuals (actual total - predicted mu).
        Returns default_sigma if fewer than 2 past games have been recorded.
        """
        if len(self._residuals) < 2:
            return self.params.default_sigma
        sd = float(np.std(self._residuals, ddof=1))
        return sd if sd > 0.0 else self.params.default_sigma

    def predict_mu(self, home_team_id: int, away_team_id: int, season_id: int) -> float:
        """Predicted game total mu = pace/efficiency style average of both teams' rolling totals."""
        t_home = self.team_rolling_total(home_team_id, season_id)
        t_away = self.team_rolling_total(away_team_id, season_id)
        return (t_home + t_away) / 2.0

    def predict(
        self, home_team_id: int, away_team_id: int, season_id: int
    ) -> Tuple[float, float]:
        """Returns (mu, sigma) using only information available prior to this game."""
        mu = self.predict_mu(home_team_id, away_team_id, season_id)
        sigma = self.current_sigma()
        return mu, sigma

    def predict_probs(
        self, line: float, home_team_id: int, away_team_id: int, season_id: int
    ) -> Tuple[float, float]:
        """Returns (p_over, p_under) for the given line."""
        mu, sigma = self.predict(home_team_id, away_team_id, season_id)
        po = p_over(line, mu, sigma)
        pu = p_under(line, mu, sigma)
        return po, pu

    def update(self, game: GameLike, mu: Optional[float] = None) -> None:
        """
        Add a completed game to history.
        Must be called AFTER taking the prediction for this game.
        """
        actual_total = float(game.home_pts + game.away_pts)
        if mu is None:
            mu = self.predict_mu(game.home_team_id, game.away_team_id, game.season_id)
        residual = actual_total - mu
        self._residuals.append(residual)

        # Update per-team rolling combined totals
        home = self._teams.setdefault(game.home_team_id, _TeamTotalsHistory())
        home.totals.append(actual_total)
        away = self._teams.setdefault(game.away_team_id, _TeamTotalsHistory())
        away.totals.append(actual_total)

        # Update season total
        season = self._seasons.setdefault(game.season_id, _SeasonTotalsHistory())
        season.game_count += 1
        season.total_points += actual_total
        self.games_seen += 1


@dataclass(frozen=True)
class TotalsFeatureSet:
    """Chronological predictions and targets for a series of completed games."""

    mu: np.ndarray  # predicted totals
    sigma: np.ndarray  # estimated sigmas
    actual: np.ndarray  # actual game totals
    residuals: np.ndarray  # actual - mu
    game_ids: Tuple[str, ...]
    dates: Tuple[date, ...]

    def __len__(self) -> int:
        return len(self.game_ids)


def build_totals_feature_set(
    games: Sequence[GameLike], params: Optional[TotalsParams] = None
) -> Tuple[TotalsFeatureSet, TotalsState]:
    """
    Performs one chronological leak-free pass over games.
    Returns (TotalsFeatureSet, TotalsState at end of history).
    """
    state = TotalsState(params)
    n = len(games)
    mu_arr = np.empty(n, dtype=float)
    sigma_arr = np.empty(n, dtype=float)
    actual_arr = np.empty(n, dtype=float)

    for i, g in enumerate(games):
        mu, sigma = state.predict(g.home_team_id, g.away_team_id, g.season_id)
        mu_arr[i] = mu
        sigma_arr[i] = sigma
        actual_total = float(g.home_pts + g.away_pts)
        actual_arr[i] = actual_total
        state.update(g, mu=mu)

    feature_set = TotalsFeatureSet(
        mu=mu_arr,
        sigma=sigma_arr,
        actual=actual_arr,
        residuals=actual_arr - mu_arr,
        game_ids=tuple(g.game_id for g in games),
        dates=tuple(g.game_date for g in games),
    )
    return feature_set, state
