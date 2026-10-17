"""
Elo ratings built from ``player_game_log``: reconstruction of final scores, replay, persistence in
``team_elo_rating``, walk-forward evaluation and ``model_version`` registration.

The Elo maths lives in ``app.analytics.elo``. This module owns the data side:

* Game reconstruction: a team's score is the sum of its players' ``pts``; ``matchup`` says who was home
  ('X vs. Y' row = X is home, 'X @ Y' row = X is away). Preseason (game_id type 1) and all-star (type 3)
  games are excluded, and so is any game with a non-NBA team (EST, WST, ...).
* Franchise continuity: historical abbreviations (NJN, NOH, NOK, SEA) are folded onto the current franchise,
  so ``team_elo_rating.team_id`` always holds the canonical (current) team id and one rating line follows
  the franchise through relocations.
* Replay: chronological by (game_date, game_id); ratings regress toward the mean on a team's first counted
  game of a new season. ``rebuild_all`` and ``update_new_games`` share the same replay code, so the
  incremental path produces exactly the numbers of a full rebuild.

Note: ``app.services.elo`` (older, per-team timeline helper) is unrelated and left untouched.
"""
import math
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel import Session

from app.analytics import elo
from app.models import ModelVersion, PlayerGameLog, Season, Team, TeamEloRating

MODEL_NAME = "elo_538"
MODEL_VERSION = "1.0"
DEFAULT_SIGMA = 12.0
OOS_SEASONS = 5

# game_id[2]: 1 preseason, 2 regular season, 3 all-star, 4 playoffs, 5 play-in, 6 NBA Cup final
INCLUDED_GAME_TYPES = ("2", "4", "5", "6")

CURRENT_TEAMS = frozenset(
    "ATL BOS BKN CHA CHI CLE DAL DEN DET GSW HOU IND LAC LAL MEM MIA MIL MIN NOP NYK OKC ORL PHI PHX POR SAC SAS "
    "TOR UTA WAS".split()
)
# Historical abbreviation -> current franchise (verified against the abbreviations present in player_game_log).
FRANCHISE_ALIASES = {"NJN": "BKN", "NOH": "NOP", "NOK": "NOP", "SEA": "OKC"}

_INSERT_CHUNK = 1000
_LOG_LOSS_EPS = 1e-15


@dataclass(frozen=True)
class HistoricalGame:
    game_id: str
    game_date: date
    season_id: int
    home_team_id: int  # canonical (current franchise) team ids
    away_team_id: int
    home_pts: int
    away_pts: int

    @property
    def sort_key(self) -> Tuple[date, str]:
        return (self.game_date, self.game_id)


@dataclass
class LoadReport:
    games_seen: int = 0
    games_used: int = 0
    unmapped_abbreviations: Counter = field(default_factory=Counter)  # abbreviation -> games skipped
    skipped_not_two_teams: int = 0
    skipped_home_away: int = 0
    skipped_same_franchise: int = 0


@dataclass(frozen=True)
class GameRating:
    game: HistoricalGame
    home_before: float
    away_before: float
    home_after: float
    away_after: float
    p_home: float

    @property
    def expected_margin(self) -> float:
        return elo.expected_margin(self.home_before, self.away_before)

    @property
    def actual_margin(self) -> int:
        return self.game.home_pts - self.game.away_pts


# team_id -> (rating after its last counted game, season_id of that game)
TeamState = Dict[int, Tuple[float, int]]


@dataclass(frozen=True)
class EloPrediction:
    p_home: float
    expected_margin: float
    sigma: float


@dataclass(frozen=True)
class SeasonMetrics:
    season_id: int
    season_label: str
    n_games: int
    brier: float
    log_loss: float
    accuracy: float
    mae_margin: float
    residual_std: float  # std of (actual_margin - expected_margin)
    mean_residual: float  # bias of the expected margin


@dataclass
class BackfillSummary:
    games_used: int = 0
    rows_written: int = 0
    rows_deleted: int = 0
    rebuilt: bool = False  # update_new_games fell back to a full rebuild
    dry_run: bool = False
    final_ratings: Dict[int, float] = field(default_factory=dict)
    report: Optional[LoadReport] = None


def replay_games(
    games: Iterable[HistoricalGame], state: Optional[TeamState] = None
) -> Tuple[List[GameRating], TeamState]:
    """Replay games (already chronological) from ``state``; returns the per-game ratings and the new state."""
    state = dict(state or {})
    results: List[GameRating] = []
    for game in games:
        ratings = []
        for team_id in (game.home_team_id, game.away_team_id):
            rating, last_season = state.get(team_id, (elo.INITIAL_RATING, game.season_id))
            if last_season != game.season_id:
                rating = elo.season_carryover(rating)
            ratings.append(rating)
        home_before, away_before = ratings
        home_after, away_after, p_home = elo.update_ratings(home_before, away_before, game.home_pts, game.away_pts)
        state[game.home_team_id] = (home_after, game.season_id)
        state[game.away_team_id] = (away_after, game.season_id)
        results.append(GameRating(game, home_before, away_before, home_after, away_after, p_home))
    return results, state


def rating_rows(rating: GameRating) -> List[dict]:
    """The two team_elo_rating rows (home, away) a replayed game produces."""
    game = rating.game
    home_won = game.home_pts > game.away_pts
    common = {"season_id": game.season_id, "game_id": game.game_id, "game_date": game.game_date, "k_factor": elo.K}
    return [
        {
            **common,
            "team_id": game.home_team_id,
            "opponent_team_id": game.away_team_id,
            "rating_before": rating.home_before,
            "rating_after": rating.home_after,
            "result": "W" if home_won else "L",
            "win_probability": rating.p_home,
        },
        {
            **common,
            "team_id": game.away_team_id,
            "opponent_team_id": game.home_team_id,
            "rating_before": rating.away_before,
            "rating_after": rating.away_after,
            "result": "L" if home_won else "W",
            "win_probability": 1.0 - rating.p_home,
        },
    ]


def season_metrics(season_id: int, season_label: str, ratings: Sequence[GameRating]) -> SeasonMetrics:
    n = len(ratings)
    brier = log_loss = correct = abs_err = 0.0
    residuals: List[float] = []
    for r in ratings:
        home_won = 1.0 if r.actual_margin > 0 else 0.0
        brier += (r.p_home - home_won) ** 2
        p = min(max(r.p_home, _LOG_LOSS_EPS), 1.0 - _LOG_LOSS_EPS)
        log_loss -= math.log(p if home_won else 1.0 - p)
        correct += 1.0 if (r.p_home > 0.5) == bool(home_won) else 0.0
        residual = r.actual_margin - r.expected_margin
        residuals.append(residual)
        abs_err += abs(residual)
    mean_residual = sum(residuals) / n
    variance = sum((x - mean_residual) ** 2 for x in residuals) / n
    return SeasonMetrics(
        season_id=season_id,
        season_label=season_label,
        n_games=n,
        brier=brier / n,
        log_loss=log_loss / n,
        accuracy=correct / n,
        mae_margin=abs_err / n,
        residual_std=math.sqrt(variance),
        mean_residual=mean_residual,
    )


def out_of_sample_summary(metrics: Sequence[SeasonMetrics], last_n: int = OOS_SEASONS) -> Tuple[float, float]:
    """
    (sigma, brier) over the last ``last_n`` completed seasons: sigma is the pooled residual std (games
    weighted), brier the plain mean of the per-season Brier scores. A season counts as completed when it has
    at least 80% of the median number of games, which drops a partial current season.
    """
    if not metrics:
        raise ValueError("no season metrics to summarise")
    counts = sorted(m.n_games for m in metrics)
    median = counts[len(counts) // 2]
    completed = [m for m in metrics if m.n_games >= 0.8 * median] or list(metrics)
    window = completed[-last_n:]
    total = sum(m.n_games for m in window)
    pooled_mean = sum(m.n_games * m.mean_residual for m in window) / total
    sum_sq = sum(m.n_games * (m.residual_std**2 + (m.mean_residual - pooled_mean) ** 2) for m in window)
    return math.sqrt(sum_sq / total), sum(m.brier for m in window) / len(window)


class EloService:
    def __init__(self, session: Session, sigma: Optional[float] = None):
        self.session = session
        self.sigma = sigma
        self.last_load_report = LoadReport()

    # ------------------------------------------------------------------ games

    def _team_maps(self) -> Tuple[Dict[int, str], Dict[str, int]]:
        rows = self.session.execute(select(Team.id, Team.abbreviation)).all()
        return {team_id: abbr for team_id, abbr in rows}, {abbr: team_id for team_id, abbr in rows}

    def load_games(self, since: Optional[date] = None) -> List[HistoricalGame]:
        """Completed NBA games reconstructed from player_game_log, chronological. Diagnostics: last_load_report."""
        id_to_abbr, abbr_to_id = self._team_maps()
        stmt = (
            select(
                PlayerGameLog.game_id,
                PlayerGameLog.team_id,
                func.min(PlayerGameLog.season_id),
                func.min(PlayerGameLog.game_date),
                func.max(PlayerGameLog.matchup),
                func.sum(PlayerGameLog.pts),
            )
            .where(
                func.substr(PlayerGameLog.game_id, 3, 1).in_(INCLUDED_GAME_TYPES),
                PlayerGameLog.game_date.is_not(None),
                PlayerGameLog.matchup.is_not(None),
            )
            .group_by(PlayerGameLog.game_id, PlayerGameLog.team_id)
        )
        if since is not None:
            stmt = stmt.where(PlayerGameLog.game_date >= since)

        by_game: Dict[str, list] = {}
        for game_id, team_id, season_id, game_date, matchup, pts in self.session.execute(stmt).all():
            by_game.setdefault(game_id, []).append((team_id, season_id, game_date, matchup or "", int(pts or 0)))

        report = LoadReport(games_seen=len(by_game))
        games: List[HistoricalGame] = []
        for game_id, sides in by_game.items():
            if len(sides) != 2:
                report.skipped_not_two_teams += 1
                continue

            canonical: List[Optional[int]] = []
            unmapped: List[str] = []
            for team_id, *_ in sides:
                abbr = id_to_abbr.get(team_id, str(team_id))
                target = FRANCHISE_ALIASES.get(abbr, abbr)
                if target in CURRENT_TEAMS and target in abbr_to_id:
                    canonical.append(abbr_to_id[target])
                else:
                    canonical.append(None)
                    unmapped.append(abbr)
            if unmapped:
                for abbr in unmapped:
                    report.unmapped_abbreviations[abbr] += 1
                continue
            if canonical[0] == canonical[1]:
                report.skipped_same_franchise += 1
                continue

            home_flags = [(" vs. " in side[3]) for side in sides]
            away_flags = [(" @ " in side[3]) for side in sides]
            if home_flags.count(True) != 1 or away_flags.count(True) != 1 or home_flags == away_flags:
                report.skipped_home_away += 1
                continue
            home = 0 if home_flags[0] else 1
            away = 1 - home
            games.append(
                HistoricalGame(
                    game_id=game_id,
                    game_date=min(side[2] for side in sides),
                    season_id=min(side[1] for side in sides),
                    home_team_id=canonical[home],
                    away_team_id=canonical[away],
                    home_pts=sides[home][4],
                    away_pts=sides[away][4],
                )
            )

        games.sort(key=lambda g: g.sort_key)
        report.games_used = len(games)
        self.last_load_report = report
        return games

    # ------------------------------------------------------------ persistence

    def _upsert_rows(self, rows: List[dict]) -> int:
        if not rows:
            return 0
        dialect = self.session.get_bind().dialect.name
        make_insert = {"postgresql": pg_insert, "sqlite": sqlite_insert}.get(dialect)
        if make_insert is None:
            raise NotImplementedError(f"idempotent Elo upsert is not implemented for dialect {dialect!r}")
        table = TeamEloRating.__table__
        updatable = [
            "game_date",
            "opponent_team_id",
            "rating_before",
            "rating_after",
            "k_factor",
            "result",
            "win_probability",
        ]
        for start in range(0, len(rows), _INSERT_CHUNK):
            stmt = make_insert(table).values(rows[start : start + _INSERT_CHUNK])
            stmt = stmt.on_conflict_do_update(
                index_elements=["team_id", "season_id", "game_id"],
                set_={col: getattr(stmt.excluded, col) for col in updatable},
            )
            self.session.execute(stmt)
        return len(rows)

    def _delete_stale(self, keep: Set[Tuple[int, int, str]]) -> int:
        """Remove rating rows (for example under a pre-mapping team id) that a full replay no longer produces."""
        table = TeamEloRating.__table__
        stale = [
            row_id
            for row_id, team_id, season_id, game_id in self.session.execute(
                select(table.c.id, table.c.team_id, table.c.season_id, table.c.game_id)
            ).all()
            if (team_id, season_id, game_id) not in keep
        ]
        for start in range(0, len(stale), _INSERT_CHUNK):
            self.session.execute(delete(table).where(table.c.id.in_(stale[start : start + _INSERT_CHUNK])))
        return len(stale)

    def _load_state(self, as_of: Optional[date] = None) -> Tuple[TeamState, Set[str], Optional[Tuple[date, str]]]:
        """Latest rating per team, the game_ids that already have rows, and the newest (date, game_id) rated."""
        table = TeamEloRating.__table__
        stmt = select(
            table.c.team_id, table.c.season_id, table.c.game_id, table.c.game_date, table.c.rating_after
        ).where(table.c.game_date.is_not(None))
        if as_of is not None:
            stmt = stmt.where(table.c.game_date <= as_of)
        stmt = stmt.order_by(table.c.game_date, table.c.game_id)

        state: TeamState = {}
        rated: Set[str] = set()
        last_key: Optional[Tuple[date, str]] = None
        for team_id, season_id, game_id, game_date, rating_after in self.session.execute(stmt).all():
            state[team_id] = (rating_after, season_id)
            rated.add(game_id)
            last_key = (game_date, game_id)
        return state, rated, last_key

    # --------------------------------------------------------------- backfill

    def rebuild_all(self, dry_run: bool = False) -> BackfillSummary:
        """Recompute every rating from scratch and upsert it. Idempotent; ``dry_run`` writes nothing."""
        games = self.load_games()
        ratings, state = replay_games(games)
        summary = BackfillSummary(
            games_used=len(games),
            dry_run=dry_run,
            final_ratings={team_id: rating for team_id, (rating, _) in state.items()},
            report=self.last_load_report,
        )
        if dry_run:
            summary.rows_written = 2 * len(ratings)
            return summary

        rows = [row for rating in ratings for row in rating_rows(rating)]
        summary.rows_written = self._upsert_rows(rows)
        summary.rows_deleted = self._delete_stale({(r["team_id"], r["season_id"], r["game_id"]) for r in rows})
        self.session.commit()
        return summary

    def update_new_games(self, dry_run: bool = False) -> BackfillSummary:
        """
        Rate only games without rows, continuing from each team's latest rating. If a new game predates the
        newest rated game (a late-ingested result) the incremental order would be wrong, so it falls back to
        a full rebuild; either way the numbers equal those of ``rebuild_all``.
        """
        games = self.load_games()
        state, rated, last_key = self._load_state()
        new_games = [g for g in games if g.game_id not in rated]
        if last_key is not None and any(g.sort_key < last_key for g in new_games):
            summary = self.rebuild_all(dry_run=dry_run)
            summary.rebuilt = True
            return summary

        ratings, new_state = replay_games(new_games, state)
        summary = BackfillSummary(
            games_used=len(new_games),
            dry_run=dry_run,
            final_ratings={team_id: rating for team_id, (rating, _) in new_state.items()},
            report=self.last_load_report,
        )
        rows = [row for rating in ratings for row in rating_rows(rating)]
        if dry_run:
            summary.rows_written = len(rows)
            return summary
        summary.rows_written = self._upsert_rows(rows)
        self.session.commit()
        return summary

    # ---------------------------------------------------------------- queries

    def current_ratings(
        self, as_of: Optional[date] = None, for_season_id: Optional[int] = None
    ) -> Dict[int, float]:
        """
        Latest ``rating_after`` per team (games on or before ``as_of``). With ``for_season_id``, a team whose
        latest game belongs to another season gets the season carryover once, i.e. the rating to use for a
        game of that new season.
        """
        state, _, _ = self._load_state(as_of)
        ratings: Dict[int, float] = {}
        for team_id, (rating, season_id) in state.items():
            if for_season_id is not None and season_id != for_season_id:
                rating = elo.season_carryover(rating)
            ratings[team_id] = rating
        return ratings

    def load_sigma(self) -> float:
        """Sigma registered in model_version, or DEFAULT_SIGMA when the model was never registered."""
        row = self.session.execute(
            select(ModelVersion.params).where(ModelVersion.name == MODEL_NAME, ModelVersion.version == MODEL_VERSION)
        ).first()
        sigma = (row[0] or {}).get("sigma") if row else None
        return float(sigma) if sigma else DEFAULT_SIGMA

    def predict(
        self, home_team_id: int, away_team_id: int, ratings: Optional[Dict[int, float]] = None
    ) -> EloPrediction:
        """Pre-game win probability and expected home margin; unknown teams start at INITIAL_RATING."""
        ratings = self.current_ratings() if ratings is None else ratings
        r_home = ratings.get(home_team_id, elo.INITIAL_RATING)
        r_away = ratings.get(away_team_id, elo.INITIAL_RATING)
        sigma = self.sigma if self.sigma is not None else self.load_sigma()
        return EloPrediction(
            p_home=elo.expected_home_win_prob(r_home, r_away),
            expected_margin=elo.expected_margin(r_home, r_away),
            sigma=sigma,
        )

    # ------------------------------------------------------------- evaluation

    def evaluate_walk_forward(self, seasons: Optional[Iterable[str]] = None) -> List[SeasonMetrics]:
        """
        Per-season metrics of the pre-game predictions. Replaying chronologically means every prediction only
        used earlier games, so this is walk-forward by construction. ``seasons`` filters by season label.
        """
        ratings, _ = replay_games(self.load_games())
        labels = {
            season_id: label for season_id, label in self.session.execute(select(Season.id, Season.season_label)).all()
        }
        wanted = set(seasons) if seasons is not None else None
        by_season: Dict[int, List[GameRating]] = {}
        for rating in ratings:
            by_season.setdefault(rating.game.season_id, []).append(rating)

        metrics = [
            season_metrics(season_id, labels.get(season_id, str(season_id)), games)
            for season_id, games in by_season.items()
            if wanted is None or labels.get(season_id) in wanted
        ]
        metrics.sort(key=lambda m: m.season_label)
        return metrics

    def register_model_version(
        self,
        sigma: float,
        brier_oos: float,
        trained_through: Optional[date] = None,
        seasons_evaluated: Optional[Sequence[str]] = None,
    ) -> ModelVersion:
        """Upsert the elo_538 / 1.0 model_version row. Idempotent."""
        params = {
            "K": elo.K,
            "home_advantage": elo.HOME_ADVANTAGE,
            "initial_rating": elo.INITIAL_RATING,
            "carryover": elo.CARRYOVER,
            "mean_rating": elo.MEAN_RATING,
            "elo_per_point": elo.ELO_PER_POINT,
            "sigma": round(sigma, 4),
            "trained_through": trained_through.isoformat() if trained_through else None,
            "seasons_evaluated": list(seasons_evaluated or []),
        }
        brier = Decimal(f"{brier_oos:.5f}")
        row = self.session.execute(
            select(ModelVersion).where(ModelVersion.name == MODEL_NAME, ModelVersion.version == MODEL_VERSION)
        ).scalar_one_or_none()
        if row is None:
            row = ModelVersion(name=MODEL_NAME, version=MODEL_VERSION)
            self.session.add(row)
        row.params = params
        row.brier_oos = brier
        row.trained_at = datetime.now(timezone.utc)
        self.session.commit()
        self.session.refresh(row)
        return row

    def team_abbreviations(self) -> Dict[int, str]:
        return self._team_maps()[0]
