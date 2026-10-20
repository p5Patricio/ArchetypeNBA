"""
Leak-free pre-game features for the ``margin_features`` model (pure, no DB, no I/O).

A single chronological pass over completed games produces, for every game, a feature vector computed ONLY from
games that precede it. The same ``FeatureState`` class serves training (``build_feature_set``) and prediction (the
state fed with the history up to now, then ``vector`` for the upcoming game), so there is no train/serve skew:
a game's vector is always ``state.vector(...)`` taken before ``state.update(game)``.

Features (home / away are the teams of the game being predicted):

    elo_edge                reference Elo difference incl. the home edge (internal replay with the default
                            ``EloParams``, independent of any registry model and its database rows)
    rest_home, rest_away    days since the team's previous game, capped at 7 (7 when it has no previous game)
    b2b_home, b2b_away      1 when the previous game was the day before
    games7_home/_away       games the team played in the 7 days before the game
    margin10_home/_away     mean point differential over the last 10 games, shrunk to 0: sum / (n + 5)
    winpct_home/_away       season-to-date win % shrunk toward 0.5: (wins + 5) / (n + 10)
    season_progress         mean of both teams' games played in the season / 82

Targets are the home margin and the home win. Games must be fed in (game_date, game_id) order, like
``elo_service.replay_games``; a team plays at most once a day, so games of the same date never feed each other.
"""
from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Optional, Protocol, Sequence, Tuple

import numpy as np

from app.analytics import elo
from app.analytics.elo import EloParams

FEATURE_NAMES: Tuple[str, ...] = (
    "elo_edge",
    "rest_home",
    "rest_away",
    "b2b_home",
    "b2b_away",
    "games7_home",
    "games7_away",
    "margin10_home",
    "margin10_away",
    "winpct_home",
    "winpct_away",
    "season_progress",
)

REST_CAP = 7
MARGIN_WINDOW = 10
MARGIN_SHRINK = 5.0
WINPCT_SHRINK = 10.0
SEASON_GAMES = 82.0


class GameLike(Protocol):
    """What the feature pass needs from a completed game (``elo_service.HistoricalGame`` satisfies it)."""

    game_id: str
    game_date: date
    season_id: int
    home_team_id: int
    away_team_id: int
    home_pts: int
    away_pts: int


class _TeamHistory:
    __slots__ = ("rating", "rating_season", "dates", "margins", "season_games", "season_wins")

    def __init__(self) -> None:
        self.rating: Optional[float] = None
        self.rating_season: Optional[int] = None
        self.dates: List[date] = []
        self.margins: List[float] = []  # point differential from the team's side, chronological
        self.season_games: Dict[int, int] = {}
        self.season_wins: Dict[int, int] = {}


_UNSEEN = _TeamHistory()  # shared blank history; never mutated


class FeatureState:
    """Everything known before the next game: Elo ratings and per-team histories."""

    def __init__(self, elo_params: Optional[EloParams] = None):
        self.elo_params = elo_params or EloParams()
        self._teams: Dict[int, _TeamHistory] = {}
        self.last_game_date: Optional[date] = None

    # ------------------------------------------------------------------ queries

    def knows(self, team_id: int) -> bool:
        """True when the team has at least one game in the history."""
        return team_id in self._teams

    def team_last_game_date(self, team_id: int) -> Optional[date]:
        team = self._teams.get(team_id)
        return team.dates[-1] if team is not None and team.dates else None

    def _rating(self, team: _TeamHistory, season_id: int) -> float:
        """The team's rating for a game of ``season_id``: the season carryover applies on its first game of a season."""
        params = self.elo_params
        if team.rating is None:
            return params.initial_rating
        if team.rating_season != season_id:
            return elo.season_carryover(team.rating, params.carryover, params.mean_rating)
        return team.rating

    @staticmethod
    def _rest_days(team: _TeamHistory, game_date: date) -> int:
        if not team.dates:
            return REST_CAP
        return max(0, min(REST_CAP, (game_date - team.dates[-1]).days))

    @staticmethod
    def _games_last_week(team: _TeamHistory, game_date: date) -> int:
        count = 0
        for played in reversed(team.dates):
            if (game_date - played).days > 7:
                break
            if played < game_date:
                count += 1
        return count

    @staticmethod
    def _recent_margin(team: _TeamHistory) -> float:
        recent = team.margins[-MARGIN_WINDOW:]
        return sum(recent) / (len(recent) + MARGIN_SHRINK)

    @staticmethod
    def _win_pct(team: _TeamHistory, season_id: int) -> float:
        played = team.season_games.get(season_id, 0)
        return (team.season_wins.get(season_id, 0) + WINPCT_SHRINK / 2.0) / (played + WINPCT_SHRINK)

    def vector(self, home_team_id: int, away_team_id: int, season_id: int, game_date: date) -> np.ndarray:
        """Feature vector of a game, from the history fed so far (unseen teams start from blank histories)."""
        home = self._teams.get(home_team_id, _UNSEEN)
        away = self._teams.get(away_team_id, _UNSEEN)
        rest_home, rest_away = self._rest_days(home, game_date), self._rest_days(away, game_date)
        progress = (home.season_games.get(season_id, 0) + away.season_games.get(season_id, 0)) / 2.0 / SEASON_GAMES
        return np.array(
            [
                self._rating(home, season_id) + self.elo_params.home_advantage - self._rating(away, season_id),
                rest_home,
                rest_away,
                1.0 if rest_home == 1 else 0.0,
                1.0 if rest_away == 1 else 0.0,
                self._games_last_week(home, game_date),
                self._games_last_week(away, game_date),
                self._recent_margin(home),
                self._recent_margin(away),
                self._win_pct(home, season_id),
                self._win_pct(away, season_id),
                progress,
            ],
            dtype=float,
        )

    # ------------------------------------------------------------------ update

    def update(self, game: GameLike) -> None:
        """Add a completed game to the history (call it after taking the game's own vector)."""
        params = self.elo_params
        home = self._teams.setdefault(game.home_team_id, _TeamHistory())
        away = self._teams.setdefault(game.away_team_id, _TeamHistory())
        new_home, new_away, _ = elo.update_ratings(
            self._rating(home, game.season_id),
            self._rating(away, game.season_id),
            game.home_pts,
            game.away_pts,
            params.k,
            params.home_advantage,
            params.mov_exponent,
        )
        margin = float(game.home_pts - game.away_pts)
        for team, rating, team_margin in ((home, new_home, margin), (away, new_away, -margin)):
            team.rating, team.rating_season = rating, game.season_id
            team.dates.append(game.game_date)
            team.margins.append(team_margin)
            team.season_games[game.season_id] = team.season_games.get(game.season_id, 0) + 1
            if team_margin > 0:
                team.season_wins[game.season_id] = team.season_wins.get(game.season_id, 0) + 1
        if self.last_game_date is None or game.game_date > self.last_game_date:
            self.last_game_date = game.game_date


@dataclass(frozen=True)
class FeatureSet:
    """Features and targets of a chronological list of games (row i belongs to game i)."""

    X: np.ndarray  # (n, len(FEATURE_NAMES))
    margin: np.ndarray  # home points - away points
    home_win: np.ndarray  # 1.0 when the home team won
    season_ids: np.ndarray
    season_rank: np.ndarray  # chronological index of the game's season (0 = first season in the data)
    game_ids: Tuple[str, ...]
    dates: Tuple[date, ...]

    def __len__(self) -> int:
        return len(self.game_ids)


def build_feature_set(
    games: Sequence[GameLike], elo_params: Optional[EloParams] = None
) -> Tuple[FeatureSet, FeatureState]:
    """One chronological pass; returns the per-game features and the state after the last game."""
    state = FeatureState(elo_params)
    X = np.empty((len(games), len(FEATURE_NAMES)), dtype=float)
    ranks: Dict[int, int] = {}
    season_rank = np.empty(len(games), dtype=int)
    for i, game in enumerate(games):
        X[i] = state.vector(game.home_team_id, game.away_team_id, game.season_id, game.game_date)
        state.update(game)
        season_rank[i] = ranks.setdefault(game.season_id, len(ranks))
    margin = np.array([g.home_pts - g.away_pts for g in games], dtype=float)
    feature_set = FeatureSet(
        X=X,
        margin=margin,
        home_win=(margin > 0).astype(float),
        season_ids=np.array([g.season_id for g in games], dtype=int),
        season_rank=season_rank,
        game_ids=tuple(g.game_id for g in games),
        dates=tuple(g.game_date for g in games),
    )
    return feature_set, state
