"""
``elo_injury``: an injury-aware challenger model combining 538-style Elo ratings with a player availability adjustment.

Design:
1. Pure math in ``app.analytics.availability``:
   - Player impact proxy: mpg * max(0.0, production_rate - replacement_rate).
   - Expected missing impact: sum over team players of impact_i * (1 - availability_prob_i).
   - Margin adjustment:
       mu_adj = mu_elo + beta * (expected_missing_away - expected_missing_home)
     Sign convention:
       If away has missing impact (missing_away > missing_home), away is weakened -> home expected margin increases (+).
       If home has missing impact (missing_home > missing_away), home is weakened -> home expected margin decreases (-).
   - Win probability:
       p_home = Phi(mu_adj / sigma) under continuous normal margin distribution M ~ N(mu_adj, sigma).

2. Serving:
   - Latest ``InjuryReportSnapshot`` strictly before ``game_time`` (<= game_time) within ``max_snapshot_age_hours`` (36h).
   - If no snapshot or stale -> NO adjustment (default to Elo; notes record the fallback).
   - Unmatched player names (player_id is None) are ignored and counted, never invented (Rule 3).
   - No look-ahead: only historical logs and snapshots strictly before the prediction instant are read.

3. Calibration & Evaluation (historical training proxy):
   - For every historical game, missing impact is computed from actual absences of rotation players in ``player_game_log``.
   - Fit beta by walk-forward OLS: actual_margin - mu_elo ~ beta * (missing_away - missing_home).
   - UPPER BOUND CAVEAT: Historical logs record actual binary absences (played vs didn't). Serving uses pre-game
     status probabilities from injury reports, which are noisier (train/serve skew). Historical evaluation
     represents an upper bound on what live serving can achieve.
"""
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
import logging
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple

import numpy as np
from sqlalchemy import func, select
from sqlmodel import Session

from app.analytics import availability
from app.analytics.availability import (
    DEFAULT_REPLACEMENT_RATE,
    DEFAULT_ROTATION_MIN_GP,
    DEFAULT_ROTATION_MIN_MPG,
    bootstrap_beta_ci,
    bootstrap_gain_ci,
    compute_adjusted_margin,
    compute_expected_missing_impact,
    compute_gains,
    compute_player_impact,
    compute_production_score,
    compute_team_missing_impact,
    fit_beta,
    normal_win_prob,
)
from app.analytics.elo import EloParams
from app.models import (
    Game,
    InjuryEntry,
    InjuryReportSnapshot,
    ModelVersion,
    Player,
    PlayerGameLog,
    Season,
    Team,
)
from app.services import model_registry
from app.services.elo_service import EloRatingService, GameRating, HistoricalGame, replay_games
from app.services.injury_report_parser import STATUS_AVAILABILITY_PROBABILITIES
from app.services.model_registry import ModelRegistryError, Prediction, register_family

logger = logging.getLogger(__name__)

FAMILY_NAME = "elo_injury"
DEFAULT_BETA = 0.40
DEFAULT_SIGMA = 14.14
DEFAULT_MAX_SNAPSHOT_AGE_HOURS = 36.0


@dataclass(frozen=True)
class PlayerImpactInfo:
    player_id: int
    team_id: int
    season_id: int
    gp: int
    total_minutes: float
    mpg: float
    production_rate: float
    impact: float
    is_rotation: bool


@dataclass(frozen=True)
class SeasonEvalResult:
    season_id: int
    season_label: str
    n_games: int
    beta: float
    elo_log_loss: float
    adj_log_loss: float
    log_loss_gain: float
    elo_brier: float
    adj_brier: float
    brier_gain: float


@dataclass
class WalkForwardEvalResult:
    season_results: List[SeasonEvalResult] = field(default_factory=list)
    overall_beta: float = 0.0
    overall_beta_ci: Tuple[float, float] = (0.0, 0.0)
    log_loss_gain: float = 0.0
    log_loss_gain_ci: Tuple[float, float] = (0.0, 0.0)
    brier_gain: float = 0.0
    brier_gain_ci: Tuple[float, float] = (0.0, 0.0)
    sigma: float = DEFAULT_SIGMA
    n_games: int = 0
    caveat: str = (
        "UPPER BOUND: Historical evaluation uses actual absences from player game logs (train/serve skew). "
        "Live serving uses injury report probabilities, which are noisier."
    )


def compute_historical_player_impacts(
    session: Session,
    season_id: int,
    as_of_date: Optional[date] = None,
    min_mpg: float = DEFAULT_ROTATION_MIN_MPG,
    min_gp: int = DEFAULT_ROTATION_MIN_GP,
    replacement_rate: float = DEFAULT_REPLACEMENT_RATE,
) -> Dict[Tuple[int, int], PlayerImpactInfo]:
    """
    Computes per-player, per-team impact proxies from PlayerGameLog rows strictly before ``as_of_date``.
    Returns a mapping: (player_id, team_id) -> PlayerImpactInfo.
    """
    stmt = (
        select(
            PlayerGameLog.player_id,
            PlayerGameLog.team_id,
            func.count(PlayerGameLog.id).label("gp"),
            func.sum(PlayerGameLog.min).label("total_min"),
            func.sum(PlayerGameLog.pts).label("pts"),
            func.sum(PlayerGameLog.fgm).label("fgm"),
            func.sum(PlayerGameLog.fga).label("fga"),
            func.sum(PlayerGameLog.ftm).label("ftm"),
            func.sum(PlayerGameLog.fta).label("fta"),
            func.sum(PlayerGameLog.oreb).label("oreb"),
            func.sum(PlayerGameLog.dreb).label("dreb"),
            func.sum(PlayerGameLog.reb).label("reb"),
            func.sum(PlayerGameLog.ast).label("ast"),
            func.sum(PlayerGameLog.stl).label("stl"),
            func.sum(PlayerGameLog.blk).label("blk"),
            func.sum(PlayerGameLog.tov).label("tov"),
            func.sum(PlayerGameLog.pf).label("pf"),
        )
        .where(
            PlayerGameLog.season_id == season_id,
            PlayerGameLog.min > 0,
        )
        .group_by(PlayerGameLog.player_id, PlayerGameLog.team_id)
    )
    if as_of_date is not None:
        stmt = stmt.where(PlayerGameLog.game_date < as_of_date)

    impacts: Dict[Tuple[int, int], PlayerImpactInfo] = {}
    rows = session.execute(stmt).all()
    for row in rows:
        player_id = int(row.player_id)
        team_id = int(row.team_id)
        gp = int(row.gp or 0)
        total_min = float(row.total_min or 0.0)
        if gp <= 0 or total_min <= 0.0:
            continue
        mpg = total_min / gp
        score = compute_production_score(
            pts=float(row.pts or 0.0),
            fgm=float(row.fgm or 0.0),
            fga=float(row.fga or 0.0),
            ftm=float(row.ftm or 0.0),
            fta=float(row.fta or 0.0),
            oreb=float(row.oreb or 0.0),
            dreb=float(row.dreb or 0.0),
            reb=float(row.reb or 0.0),
            ast=float(row.ast or 0.0),
            stl=float(row.stl or 0.0),
            blk=float(row.blk or 0.0),
            tov=float(row.tov or 0.0),
            pf=float(row.pf or 0.0),
        )
        rate = score / total_min
        impact = compute_player_impact(mpg, rate, replacement_rate=replacement_rate)
        is_rotation = (mpg >= min_mpg) and (gp >= min_gp)
        impacts[(player_id, team_id)] = PlayerImpactInfo(
            player_id=player_id,
            team_id=team_id,
            season_id=season_id,
            gp=gp,
            total_minutes=total_min,
            mpg=mpg,
            production_rate=rate,
            impact=impact,
            is_rotation=is_rotation,
        )

    return impacts


def fit_walk_forward_injury_adjustment(
    session: Session,
    n_test_seasons: int = 5,
    min_mpg: float = DEFAULT_ROTATION_MIN_MPG,
    min_gp: int = DEFAULT_ROTATION_MIN_GP,
    replacement_rate: float = DEFAULT_REPLACEMENT_RATE,
    bootstrap_samples: int = 2000,
    seed: int = 42,
) -> WalkForwardEvalResult:
    """
    Fits and evaluates the injury adjustment walk-forward on completed historical seasons.
    For each test season T:
      1. Train on all completed seasons strictly before T: fit beta = sum(x*y)/sum(x^2).
      2. Evaluate Elo vs Elo+adj on season T using actual rotation player absences.
    Reports pooled log loss and Brier gains with bootstrap confidence intervals.
    """
    elo_service = EloRatingService(session)
    games = elo_service.load_games()
    if not games:
        return WalkForwardEvalResult()

    ratings, _ = replay_games(games, params=elo_service.params)
    game_ratings_by_id = {r.game.game_id: r for r in ratings}

    # Group games by season
    seasons_order: List[int] = []
    games_by_season: Dict[int, List[HistoricalGame]] = {}
    for g in games:
        if g.season_id not in games_by_season:
            games_by_season[g.season_id] = []
            seasons_order.append(g.season_id)
        games_by_season[g.season_id].append(g)

    season_labels = {
        s.id: s.season_label
        for s in session.execute(select(Season.id, Season.season_label)).all()
    }

    # Precompute player appearances per game: game_id -> set of (player_id, team_id) who played
    log_rows = session.execute(
        select(PlayerGameLog.game_id, PlayerGameLog.team_id, PlayerGameLog.player_id).where(
            PlayerGameLog.min > 0
        )
    ).all()
    played_players_by_game: Dict[str, Set[Tuple[int, int]]] = {}
    for gid, tid, pid in log_rows:
        played_players_by_game.setdefault(gid, set()).add((pid, tid))

    # Precompute rotation players and their impacts per season
    season_impacts: Dict[int, Dict[Tuple[int, int], PlayerImpactInfo]] = {}
    for sid in seasons_order:
        season_impacts[sid] = compute_historical_player_impacts(
            session, sid, min_mpg=min_mpg, min_gp=min_gp, replacement_rate=replacement_rate
        )

    # Compute missing impact features x and Elo residual y for each game
    # x = missing_away - missing_home
    # y = actual_margin - mu_elo
    game_features: Dict[str, Tuple[float, float, float, float]] = {}  # gid -> (x, y, mu_elo, actual_margin)
    for g in games:
        r = game_ratings_by_id[g.game_id]
        mu_elo = r.expected_margin
        act_margin = float(r.actual_margin)
        y = act_margin - mu_elo

        sid = g.season_id
        impacts = season_impacts[sid]
        played = played_players_by_game.get(g.game_id, set())

        # Home missing impact
        home_missing = 0.0
        for (pid, tid), info in impacts.items():
            if tid == g.home_team_id and info.is_rotation and (pid, tid) not in played:
                home_missing += info.impact

        # Away missing impact
        away_missing = 0.0
        for (pid, tid), info in impacts.items():
            if tid == g.away_team_id and info.is_rotation and (pid, tid) not in played:
                away_missing += info.impact

        x = away_missing - home_missing
        game_features[g.game_id] = (x, y, mu_elo, act_margin)

    # Determine test seasons (last n_test_seasons, minimum 1 train season)
    if len(seasons_order) <= 1:
        test_season_ids = seasons_order
    else:
        k = min(n_test_seasons, len(seasons_order) - 1)
        test_season_ids = seasons_order[-k:]

    sigma = elo_service.sigma or DEFAULT_SIGMA
    season_results: List[SeasonEvalResult] = []
    pooled_p_elo: List[float] = []
    pooled_p_adj: List[float] = []
    pooled_y_act: List[float] = []
    all_train_x: List[float] = []
    all_train_y: List[float] = []

    for test_sid in test_season_ids:
        # Train on all seasons strictly prior to test_sid
        train_sids = [sid for sid in seasons_order if seasons_order.index(sid) < seasons_order.index(test_sid)]
        if not train_sids:
            # First season fallback
            train_sids = [test_sid]

        train_x = [game_features[g.game_id][0] for sid in train_sids for g in games_by_season[sid]]
        train_y = [game_features[g.game_id][1] for sid in train_sids for g in games_by_season[sid]]
        beta = fit_beta(np.asarray(train_x), np.asarray(train_y))

        test_games = games_by_season[test_sid]
        p_elo_list: List[float] = []
        p_adj_list: List[float] = []
        y_act_list: List[float] = []

        for g in test_games:
            x, y, mu_elo, act_margin = game_features[g.game_id]
            mu_adj = compute_adjusted_margin(mu_elo, missing_away=x, missing_home=0.0, beta=beta)
            p_elo = normal_win_prob(mu_elo, sigma)
            p_adj = normal_win_prob(mu_adj, sigma)
            y_win = 1.0 if act_margin > 0.0 else 0.0

            p_elo_list.append(p_elo)
            p_adj_list.append(p_adj)
            y_act_list.append(y_win)

        gains = compute_gains(np.asarray(p_elo_list), np.asarray(p_adj_list), np.asarray(y_act_list))
        s_result = SeasonEvalResult(
            season_id=test_sid,
            season_label=season_labels.get(test_sid, str(test_sid)),
            n_games=len(test_games),
            beta=beta,
            elo_log_loss=gains["mean_loss_baseline"],
            adj_log_loss=gains["mean_loss_adjusted"],
            log_loss_gain=gains["log_loss_gain"],
            elo_brier=gains["mean_brier_baseline"],
            adj_brier=gains["mean_brier_adjusted"],
            brier_gain=gains["brier_gain"],
        )
        season_results.append(s_result)

        pooled_p_elo.extend(p_elo_list)
        pooled_p_adj.extend(p_adj_list)
        pooled_y_act.extend(y_act_list)

    # Overall beta fit across all historical games
    for sid in seasons_order:
        for g in games_by_season[sid]:
            all_train_x.append(game_features[g.game_id][0])
            all_train_y.append(game_features[g.game_id][1])

    overall_beta = fit_beta(np.asarray(all_train_x), np.asarray(all_train_y))
    overall_beta_ci = bootstrap_beta_ci(
        np.asarray(all_train_x), np.asarray(all_train_y), n_boot=bootstrap_samples, seed=seed
    )

    pooled_gains = compute_gains(np.asarray(pooled_p_elo), np.asarray(pooled_p_adj), np.asarray(pooled_y_act))
    ll_ci = bootstrap_gain_ci(
        pooled_gains["loss_baseline"], pooled_gains["loss_adjusted"], n_boot=bootstrap_samples, seed=seed
    )
    brier_ci = bootstrap_gain_ci(
        pooled_gains["brier_baseline"], pooled_gains["brier_adjusted"], n_boot=bootstrap_samples, seed=seed
    )

    return WalkForwardEvalResult(
        season_results=season_results,
        overall_beta=overall_beta,
        overall_beta_ci=overall_beta_ci,
        log_loss_gain=pooled_gains["log_loss_gain"],
        log_loss_gain_ci=ll_ci,
        brier_gain=pooled_gains["brier_gain"],
        brier_gain_ci=brier_ci,
        sigma=sigma,
        n_games=len(pooled_y_act),
    )


class EloInjuryFamily:
    """
    Model family implementing Elo rating baseline with player availability adjustment.
    Conforms to the ``ModelFamily`` protocol in ``app.services.model_registry``.
    """

    def __init__(
        self,
        session: Session,
        model_version: ModelVersion,
        impact_lookup: Optional[Callable[[int, int, date], float]] = None,
    ):
        params = model_version.params or {}
        sigma = float(params.get("sigma") or DEFAULT_SIGMA)
        if sigma <= 0.0:
            raise ModelRegistryError(f"model_version {model_version.name} {model_version.version} has invalid sigma: {sigma}")
        self.name = model_version.name
        self.version = model_version.version
        self.model_version_id = model_version.id
        self.sigma = sigma
        self.beta = float(params.get("beta", DEFAULT_BETA))
        self.rotation_min_mpg = float(params.get("rotation_min_mpg", DEFAULT_ROTATION_MIN_MPG))
        self.replacement_rate = float(params.get("replacement_rate", DEFAULT_REPLACEMENT_RATE))
        self.max_snapshot_age_hours = float(params.get("max_snapshot_age_hours", DEFAULT_MAX_SNAPSHOT_AGE_HOURS))
        self.session = session
        self.last_notes: Optional[str] = None
        self._custom_impact_lookup = impact_lookup

        # Wrapped Elo rating service
        elo_params_dict = params.get("elo_params") or {}
        elo_model_id = params.get("elo_model_version_id", model_version.parent_id)
        self._elo_service = EloRatingService(
            session,
            sigma=sigma,
            model_version_id=elo_model_id,
            params=EloParams.from_dict(elo_params_dict) if elo_params_dict else None,
        )
        self._ratings: Dict[int, Dict[int, float]] = {}
        self._player_impact_cache: Dict[Tuple[int, int, date], float] = {}
        self._team_id_lookup: Optional[Dict[str, int]] = None

    def _team_id_for_name(self, name: Optional[str]) -> Optional[int]:
        if not name:
            return None
        if self._team_id_lookup is None:
            self._team_id_lookup = {}
            for t in self.session.execute(select(Team)).scalars().all():
                if t.id is not None:
                    self._team_id_lookup[t.full_name.lower()] = t.id
                    self._team_id_lookup[t.abbreviation.lower()] = t.id
                    self._team_id_lookup[t.city.lower()] = t.id
        return self._team_id_lookup.get(name.lower())

    def get_player_impact(self, player_id: int, season_id: int, as_of_date: date) -> float:
        """
        Gets a player's impact proxy as of ``as_of_date`` strictly before tip-off.
        Uses season-to-date logs; if < 5 games, falls back to prior season.
        """
        if self._custom_impact_lookup is not None:
            return self._custom_impact_lookup(player_id, season_id, as_of_date)

        cache_key = (player_id, season_id, as_of_date)
        if cache_key in self._player_impact_cache:
            return self._player_impact_cache[cache_key]

        # Query season-to-date logs strictly before as_of_date
        stmt = (
            select(
                func.count(PlayerGameLog.id).label("gp"),
                func.sum(PlayerGameLog.min).label("total_min"),
                func.sum(PlayerGameLog.pts).label("pts"),
                func.sum(PlayerGameLog.fgm).label("fgm"),
                func.sum(PlayerGameLog.fga).label("fga"),
                func.sum(PlayerGameLog.ftm).label("ftm"),
                func.sum(PlayerGameLog.fta).label("fta"),
                func.sum(PlayerGameLog.oreb).label("oreb"),
                func.sum(PlayerGameLog.dreb).label("dreb"),
                func.sum(PlayerGameLog.reb).label("reb"),
                func.sum(PlayerGameLog.ast).label("ast"),
                func.sum(PlayerGameLog.stl).label("stl"),
                func.sum(PlayerGameLog.blk).label("blk"),
                func.sum(PlayerGameLog.tov).label("tov"),
                func.sum(PlayerGameLog.pf).label("pf"),
            )
            .where(
                PlayerGameLog.player_id == player_id,
                PlayerGameLog.season_id == season_id,
                PlayerGameLog.game_date < as_of_date,
                PlayerGameLog.min > 0,
            )
        )
        row = self.session.execute(stmt).first()
        gp = int(row.gp or 0) if row else 0
        total_min = float(row.total_min or 0.0) if row else 0.0

        # If insufficient games in current season, fall back to prior season
        if gp < DEFAULT_ROTATION_MIN_GP:
            prior_stmt = (
                select(
                    func.count(PlayerGameLog.id).label("gp"),
                    func.sum(PlayerGameLog.min).label("total_min"),
                    func.sum(PlayerGameLog.pts).label("pts"),
                    func.sum(PlayerGameLog.fgm).label("fgm"),
                    func.sum(PlayerGameLog.fga).label("fga"),
                    func.sum(PlayerGameLog.ftm).label("ftm"),
                    func.sum(PlayerGameLog.fta).label("fta"),
                    func.sum(PlayerGameLog.oreb).label("oreb"),
                    func.sum(PlayerGameLog.dreb).label("dreb"),
                    func.sum(PlayerGameLog.reb).label("reb"),
                    func.sum(PlayerGameLog.ast).label("ast"),
                    func.sum(PlayerGameLog.stl).label("stl"),
                    func.sum(PlayerGameLog.blk).label("blk"),
                    func.sum(PlayerGameLog.tov).label("tov"),
                    func.sum(PlayerGameLog.pf).label("pf"),
                )
                .where(
                    PlayerGameLog.player_id == player_id,
                    PlayerGameLog.season_id < season_id,
                    PlayerGameLog.min > 0,
                )
                .order_by(PlayerGameLog.season_id.desc())
                .group_by(PlayerGameLog.season_id)
                .limit(1)
            )
            prior_row = self.session.execute(prior_stmt).first()
            if prior_row and int(prior_row.gp or 0) >= DEFAULT_ROTATION_MIN_GP:
                row = prior_row
                gp = int(row.gp or 0)
                total_min = float(row.total_min or 0.0)

        if not row or gp <= 0 or total_min <= 0.0:
            impact = 0.0
        else:
            mpg = total_min / gp
            score = compute_production_score(
                pts=float(row.pts or 0.0),
                fgm=float(row.fgm or 0.0),
                fga=float(row.fga or 0.0),
                ftm=float(row.ftm or 0.0),
                fta=float(row.fta or 0.0),
                oreb=float(row.oreb or 0.0),
                dreb=float(row.dreb or 0.0),
                reb=float(row.reb or 0.0),
                ast=float(row.ast or 0.0),
                stl=float(row.stl or 0.0),
                blk=float(row.blk or 0.0),
                tov=float(row.tov or 0.0),
                pf=float(row.pf or 0.0),
            )
            rate = score / total_min
            impact = compute_player_impact(mpg, rate, replacement_rate=self.replacement_rate)

        self._player_impact_cache[cache_key] = impact
        return impact

    def predict(
        self,
        home_team_id: int,
        away_team_id: int,
        season_id: int,
        game_time: datetime,
    ) -> Optional[Prediction]:
        """
        Pre-game prediction strictly using information available before ``game_time``.
        Returns None when Elo ratings cannot be resolved.
        """
        # Ensure game_time is tz-aware UTC
        if game_time.tzinfo is None:
            game_time = game_time.replace(tzinfo=timezone.utc)
        else:
            game_time = game_time.astimezone(timezone.utc)

        # 1. Base Elo prediction
        if season_id not in self._ratings:
            self._ratings[season_id] = self._elo_service.current_ratings(for_season_id=season_id)
        ratings = self._ratings[season_id]
        if home_team_id not in ratings or away_team_id not in ratings:
            return None

        elo_pred = self._elo_service.predict(home_team_id, away_team_id, ratings)
        mu_elo = elo_pred.expected_margin

        # 2. Latest injury snapshot before tip-off
        stmt = (
            select(InjuryReportSnapshot)
            .where(InjuryReportSnapshot.report_timestamp <= game_time)
            .order_by(InjuryReportSnapshot.report_timestamp.desc())
            .limit(1)
        )
        snapshot = self.session.execute(stmt).scalar_one_or_none()

        if snapshot is None:
            self.last_notes = "no injury snapshot available; defaulted to Elo"
            return Prediction(p_home=elo_pred.p_home, mu=mu_elo, sigma=self.sigma)

        # Check snapshot freshness
        report_ts = snapshot.report_timestamp
        if report_ts.tzinfo is None:
            report_ts = report_ts.replace(tzinfo=timezone.utc)
        else:
            report_ts = report_ts.astimezone(timezone.utc)

        age = game_time - report_ts
        if age < timedelta(0) or age > timedelta(hours=self.max_snapshot_age_hours):
            self.last_notes = (
                f"injury snapshot stale ({age.total_seconds() / 3600.0:.1f}h > {self.max_snapshot_age_hours}h); defaulted to Elo"
            )
            return Prediction(p_home=elo_pred.p_home, mu=mu_elo, sigma=self.sigma)

        # 3. Process entries from the snapshot
        entries_stmt = select(InjuryEntry).where(InjuryEntry.snapshot_id == snapshot.id)
        entries = self.session.execute(entries_stmt).scalars().all()

        unmatched_count = 0
        as_of_date = game_time.date()
        home_player_impacts: List[float] = []
        home_player_probs: List[float] = []
        away_player_impacts: List[float] = []
        away_player_probs: List[float] = []

        for entry in entries:
            # Rule 3: unmatched names are ignored and counted, never invented
            if entry.player_id is None:
                unmatched_count += 1
                continue

            # Determine player team
            entry_team_id = self._team_id_for_name(entry.team_name)
            is_home = (entry_team_id == home_team_id) if entry_team_id is not None else False
            is_away = (entry_team_id == away_team_id) if entry_team_id is not None else False

            # If entry team_name did not match, fallback to player's season team
            if not is_home and not is_away:
                player_team_stmt = (
                    select(PlayerGameLog.team_id)
                    .where(
                        PlayerGameLog.player_id == entry.player_id,
                        PlayerGameLog.season_id == season_id,
                        PlayerGameLog.game_date < as_of_date,
                    )
                    .order_by(PlayerGameLog.game_date.desc())
                    .limit(1)
                )
                p_tid = self.session.execute(player_team_stmt).scalar_one_or_none()
                if p_tid == home_team_id:
                    is_home = True
                elif p_tid == away_team_id:
                    is_away = True
                else:
                    # Player belongs to another team playing today
                    continue

            # Availability probability
            if entry.availability_prob is not None:
                prob = float(entry.availability_prob)
            else:
                prob = STATUS_AVAILABILITY_PROBABILITIES.get(entry.status.upper(), 1.0)

            impact = self.get_player_impact(entry.player_id, season_id, as_of_date)
            if is_home:
                home_player_impacts.append(impact)
                home_player_probs.append(prob)
            elif is_away:
                away_player_impacts.append(impact)
                away_player_probs.append(prob)

        # 4. Sum expected missing impacts and compute adjusted margin
        exp_missing_home = compute_expected_missing_impact(home_player_impacts, home_player_probs)
        exp_missing_away = compute_expected_missing_impact(away_player_impacts, away_player_probs)

        # If zero expected missing on both sides, identical to Elo
        if exp_missing_home == 0.0 and exp_missing_away == 0.0:
            self.last_notes = f"clean injury report (no missing impact); unmatched={unmatched_count}; defaulted to Elo"
            return Prediction(p_home=elo_pred.p_home, mu=mu_elo, sigma=self.sigma)

        mu_adj = compute_adjusted_margin(
            elo_margin=mu_elo,
            missing_away=exp_missing_away,
            missing_home=exp_missing_home,
            beta=self.beta,
        )
        p_home_adj = normal_win_prob(mu_adj, self.sigma)
        self.last_notes = (
            f"injury adjusted: missing_home={exp_missing_home:.2f}, missing_away={exp_missing_away:.2f}, "
            f"unmatched={unmatched_count}, beta={self.beta:.2f}"
        )

        return Prediction(p_home=p_home_adj, mu=mu_adj, sigma=self.sigma)


# Register model family in the model registry
register_family(FAMILY_NAME, EloInjuryFamily)
