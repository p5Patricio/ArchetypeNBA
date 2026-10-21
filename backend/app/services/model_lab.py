"""
Historical candidate lab: proposes challengers to the champion using only past data and a strict time split.

Time split. T is the latest completed season. Candidates are SELECTED on the pooled walk-forward log loss of the
seasons [T-9, T-2] and REPORTED (and gated) on the hold-out seasons [T-1, T], which no choice has seen:

* Elo variants are online, so every game is predicted from earlier games only. ``search_elo_params`` draws a
  seeded random search over K, home advantage, season carryover and the margin-of-victory exponent.
* ``margin_features`` is trained on seasons < the test season (expanding) for the selection-window table, and on
  seasons <= T-2 (one fit) for the hold-out. The version that gets deployed is re-fit on every completed season.
* The baseline is the current champion (its Elo parameters from the registry), predicted the same way.

Every comparison is paired per game (log loss of the baseline minus that of the candidate, positive = candidate
better) with a seeded bootstrap 95% interval. Historical gate to become a challenger: the hold-out log loss beats
the champion's by at least ``GATE_MIN_GAIN`` AND the parameters differ materially from every active model.

Elo margin sigma is estimated walk-forward as well (residual spread of the 5 seasons before the test season), the
same rule for the champion and the candidates, so the margin NLL is comparable and leak-free.

``register_candidates`` is the only writer: it inserts the gate-passing candidates as challengers (never the
default), runs the initial Elo rating backfill for each Elo candidate, and refuses on a non-SQLite database
without an explicit confirmation or when the challenger slots are full.
"""
import hashlib
import json
import math
import time
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
from sqlalchemy import select
from sqlalchemy.engine import URL
from sqlmodel import Session

from app.analytics.elo import EloParams
from app.analytics.features import FeatureSet, build_feature_set
from app.models import MODEL_ROLE_CHALLENGER, ModelVersion, Season
from app.services import margin_features_model as mfm
from app.services import model_registry
from app.services.elo_service import DEFAULT_SIGMA, EloRatingService, HistoricalGame, replay_games

SELECTION_SEASONS = 8  # [T-9, T-2]
HOLDOUT_SEASONS = 2  # [T-1, T]
SIGMA_LOOKBACK = 5
GATE_MIN_GAIN = 0.0005
MAX_CHALLENGERS = 3
BOOTSTRAP_RESAMPLES = 2000
BOOTSTRAP_CHUNK = 250
BURN_IN_SEASONS = 1  # the first season of the data: every Elo starts at the same rating there
MIN_TRAIN_SEASONS = 2  # margin_features needs a season to fit on and another to validate its penalties
TOP_N = 5
DEFAULT_CONFIGS = 40

# Elo search space (mean rating, initial rating and Elo-per-point stay at their defaults) and the size of a
# "material" difference for each searched parameter: 5% of the range, 0.02 for carryover.
ELO_SEARCH_RANGES: Dict[str, Tuple[float, float]] = {
    "k": (10.0, 30.0),
    "home_advantage": (30.0, 110.0),
    "carryover": (0.6, 0.9),
    "mov_exponent": (0.6, 1.0),
}
ELO_MATERIAL_DIFFERENCE: Dict[str, float] = {
    "k": 1.0,
    "home_advantage": 4.0,
    "carryover": 0.02,
    "mov_exponent": 0.02,
}

_LOG_EPS = 1e-15


class LabError(RuntimeError):
    """The lab cannot run (not enough history, champion is not an Elo model, ...)."""


class RegistrationRefused(RuntimeError):
    """``register_candidates`` declined to write (guard, full slots, nothing to register)."""


# ------------------------------------------------------------------------------------------- metrics

@dataclass(frozen=True)
class Metrics:
    n: int
    log_loss: float
    brier: float
    accuracy: float
    mae_margin: float
    margin_nll: float  # Gaussian negative log-likelihood of the margin, nats per game
    calibration_slope: float  # logistic regression of the outcome on logit(p): 1 = calibrated
    calibration_intercept: float


@dataclass(frozen=True)
class PairedDelta:
    """Per-game improvement of a candidate's log loss over the baseline's (positive = candidate better)."""

    mean: float
    ci_low: float
    ci_high: float
    n: int


def log_loss_each(p: np.ndarray, win: np.ndarray) -> np.ndarray:
    p = np.clip(p, _LOG_EPS, 1.0 - _LOG_EPS)
    return -(win * np.log(p) + (1.0 - win) * np.log(1.0 - p))


def calibration_fit(p: np.ndarray, win: np.ndarray, iterations: int = 30) -> Tuple[float, float]:
    """(slope, intercept) of the logistic regression of the outcome on logit(p), by Newton-Raphson."""
    p = np.clip(p, 1e-6, 1.0 - 1e-6)
    design = np.column_stack([np.ones(len(p)), np.log(p / (1.0 - p))])
    beta = np.array([0.0, 1.0])
    for _ in range(iterations):
        q = 1.0 / (1.0 + np.exp(-design @ beta))
        gradient = design.T @ (win - q)
        hessian = (design * (q * (1.0 - q))[:, None]).T @ design + 1e-9 * np.eye(2)
        step = np.linalg.solve(hessian, gradient)
        beta = beta + step
        if np.max(np.abs(step)) < 1e-10:
            break
    return float(beta[1]), float(beta[0])


def compute_metrics(p: np.ndarray, mu: np.ndarray, sigma: np.ndarray, win: np.ndarray, margin: np.ndarray) -> Metrics:
    slope, intercept = calibration_fit(p, win)
    nll = 0.5 * np.log(2.0 * np.pi * sigma**2) + (margin - mu) ** 2 / (2.0 * sigma**2)
    return Metrics(
        n=int(len(p)),
        log_loss=float(log_loss_each(p, win).mean()),
        brier=float(((p - win) ** 2).mean()),
        accuracy=float(((p > 0.5) == (win > 0.5)).mean()),
        mae_margin=float(np.abs(margin - mu).mean()),
        margin_nll=float(nll.mean()),
        calibration_slope=slope,
        calibration_intercept=intercept,
    )


def bootstrap_means(gains: np.ndarray, seed: int, resamples: int = BOOTSTRAP_RESAMPLES) -> np.ndarray:
    """Means of ``resamples`` seeded resamples of ``gains`` (chunked to bound memory); the same seed and length
    always draw the same indices, so two metrics resampled with one seed are resampled over the same games."""
    n = len(gains)
    rng = np.random.default_rng(seed)
    means = []
    for start in range(0, resamples, BOOTSTRAP_CHUNK):
        size = min(BOOTSTRAP_CHUNK, resamples - start)
        means.append(gains[rng.integers(0, n, size=(size, n))].mean(axis=1))
    return np.concatenate(means)


def paired_bootstrap(
    gains: np.ndarray, seed: int, resamples: int = BOOTSTRAP_RESAMPLES, level: float = 0.95
) -> PairedDelta:
    """Mean of per-game ``gains`` with a seeded percentile bootstrap interval (chunked to bound memory)."""
    n = len(gains)
    means_all = bootstrap_means(gains, seed, resamples)
    tail = (1.0 - level) / 2.0 * 100.0
    low, high = np.percentile(means_all, [tail, 100.0 - tail])
    return PairedDelta(mean=float(gains.mean()), ci_low=float(low), ci_high=float(high), n=int(n))


# --------------------------------------------------------------------------------------------- data

@dataclass(frozen=True)
class LabData:
    games: List[HistoricalGame]
    features: FeatureSet
    rank_labels: List[str]  # season label by chronological rank
    completed_ranks: List[int]  # ranks of the completed seasons, chronological

    @property
    def ranks(self) -> np.ndarray:
        return self.features.season_rank

    @property
    def win(self) -> np.ndarray:
        return self.features.home_win

    @property
    def margin(self) -> np.ndarray:
        return self.features.margin


def prepare_lab_data(games: Sequence[HistoricalGame], season_labels: Mapping[int, str]) -> LabData:
    """Features for every game (one leak-free pass) plus the season bookkeeping the lab needs."""
    games = list(games)
    if not games:
        raise LabError("no completed games to evaluate")
    features, _ = build_feature_set(games)
    rank_season: Dict[int, int] = {}
    for game, rank in zip(games, features.season_rank.tolist()):
        rank_season.setdefault(rank, game.season_id)
    counts = np.bincount(features.season_rank)
    median = sorted(counts.tolist())[len(counts) // 2]
    completed = [rank for rank in range(len(counts)) if counts[rank] >= 0.8 * median]  # drops a partial season
    labels = [season_labels.get(rank_season[rank], str(rank_season[rank])) for rank in range(len(counts))]
    return LabData(games=games, features=features, rank_labels=labels, completed_ranks=completed)


@dataclass(frozen=True)
class SeasonSplit:
    selection: Tuple[int, ...]  # ranks [T-9, T-2]
    holdout: Tuple[int, ...]  # ranks [T-1, T]
    fit_through: int  # last rank margin_features is trained on for the hold-out (T-2)

    def labels(self, data: LabData, ranks: Sequence[int]) -> List[str]:
        return [data.rank_labels[r] for r in ranks]


def make_split(
    completed_ranks: Sequence[int], selection_seasons: int = SELECTION_SEASONS, holdout_seasons: int = HOLDOUT_SEASONS
) -> SeasonSplit:
    n = len(completed_ranks)
    if n < holdout_seasons + 3:
        raise LabError(f"need at least {holdout_seasons + 3} completed seasons, found {n}")
    holdout = tuple(completed_ranks[n - holdout_seasons :])
    window = completed_ranks[max(0, n - holdout_seasons - selection_seasons) : n - holdout_seasons]
    selection = tuple(r for r in window if r >= BURN_IN_SEASONS)
    return SeasonSplit(selection=selection, holdout=holdout, fit_through=completed_ranks[n - holdout_seasons - 1])


# ---------------------------------------------------------------------------------------- model runs

@dataclass
class ModelRun:
    """Pre-game predictions for every game of the lab data (NaN where the model did not predict)."""

    label: str
    p: np.ndarray
    mu: np.ndarray
    sigma: np.ndarray


def trailing_sigma(
    residuals: np.ndarray, ranks: np.ndarray, default: float = DEFAULT_SIGMA, lookback: int = SIGMA_LOOKBACK
) -> np.ndarray:
    """Per-game sigma: the RMS residual of the ``lookback`` seasons before each game's season."""
    n_ranks = int(ranks.max()) + 1
    squares = np.bincount(ranks, weights=residuals**2, minlength=n_ranks)
    counts = np.bincount(ranks, minlength=n_ranks)
    per_rank = np.empty(n_ranks)
    for rank in range(n_ranks):
        window = slice(max(0, rank - lookback), rank)
        total = counts[window].sum()
        per_rank[rank] = math.sqrt(squares[window].sum() / total) if total else default
    return per_rank[ranks]


def run_elo(data: LabData, params: EloParams, label: str = "elo") -> ModelRun:
    ratings, _ = replay_games(data.games, params=params)
    p = np.array([r.p_home for r in ratings])
    mu = np.array([r.expected_margin for r in ratings])
    return ModelRun(label, p, mu, trailing_sigma(data.margin - mu, data.ranks))


def _train_mask(data: LabData, train_ranks: Sequence[int]) -> np.ndarray:
    return np.isin(data.ranks, list(train_ranks)) & (data.ranks >= BURN_IN_SEASONS)


def fit_margin_model(data: LabData, train_ranks: Sequence[int], seed: int) -> Dict[str, Any]:
    mask = _train_mask(data, train_ranks)
    last = int(np.flatnonzero(mask)[-1])
    return mfm.fit_on_feature_set(
        data.features,
        mask,
        seed=seed,
        trained_through=data.features.dates[last],
        seasons=sorted({data.rank_labels[r] for r in set(data.ranks[mask].tolist())}),
    )


def run_margin_features(
    data: LabData, plan: Sequence[Tuple[Sequence[int], Sequence[int]]], seed: int, label: str = "margin_features"
) -> Tuple[ModelRun, Dict[str, Any]]:
    """``plan`` = (train ranks, test ranks) steps; returns the combined predictions and the last fitted params."""
    n = len(data.games)
    run = ModelRun(label, np.full(n, np.nan), np.full(n, np.nan), np.full(n, np.nan))
    params: Dict[str, Any] = {}
    for train_ranks, test_ranks in plan:
        params = fit_margin_model(data, train_ranks, seed)
        rows = np.isin(data.ranks, list(test_ranks))
        run.p[rows], run.mu[rows] = mfm.MarginFeaturesModel(params).predict_matrix(data.features.X[rows])
        run.sigma[rows] = params["sigma"]
    return run, params


def evaluate(data: LabData, run: ModelRun, ranks: Sequence[int]) -> Metrics:
    rows = np.isin(data.ranks, list(ranks))
    return compute_metrics(run.p[rows], run.mu[rows], run.sigma[rows], data.win[rows], data.margin[rows])


def paired_gain(
    data: LabData, baseline: ModelRun, candidate: ModelRun, ranks: Sequence[int], seed: int, resamples: int
) -> PairedDelta:
    rows = np.isin(data.ranks, list(ranks))
    gains = log_loss_each(baseline.p[rows], data.win[rows]) - log_loss_each(candidate.p[rows], data.win[rows])
    return paired_bootstrap(gains, seed, resamples)


# ------------------------------------------------------------------------------------------- search

def search_elo_params(n: int = DEFAULT_CONFIGS, seed: int = 42) -> List[EloParams]:
    """``n`` seeded random Elo configurations over ``ELO_SEARCH_RANGES`` (other parameters at their defaults)."""
    rng = np.random.default_rng(seed)
    unit = rng.random(size=(n, len(ELO_SEARCH_RANGES)))
    configs = []
    for row in unit:
        values = {
            name: round(low + u * (high - low), 4) for (name, (low, high)), u in zip(ELO_SEARCH_RANGES.items(), row)
        }
        configs.append(EloParams(**values))
    return configs


def elo_materially_differs(candidate: EloParams, other: EloParams) -> bool:
    return any(
        abs(getattr(candidate, name) - getattr(other, name)) > tolerance + 1e-9  # exact differences are not material
        for name, tolerance in ELO_MATERIAL_DIFFERENCE.items()
    )


def differs_from_active(kind: str, elo_params: Optional[EloParams], active: Sequence[ModelVersion]) -> bool:
    """True when the candidate differs materially from EVERY active model (a different family always differs)."""
    for row in active:
        if row.name != kind:
            continue
        if kind == model_registry.ELO_FAMILY_NAME and elo_materially_differs(elo_params, EloParams.from_dict(row.params or {})):
            continue
        return False
    return True


@dataclass(frozen=True)
class GateVerdict:
    passed: bool
    gain: float  # champion hold-out log loss minus the candidate's
    differs: bool
    reasons: Tuple[str, ...]


def evaluate_gate(gain: float, differs: bool, min_gain: float = GATE_MIN_GAIN) -> GateVerdict:
    reasons = []
    if gain < min_gain:
        reasons.append(f"hold-out log loss gain {gain:+.4f} is below the required {min_gain:+.4f}")
    if not differs:
        reasons.append("parameters do not differ materially from an active model")
    return GateVerdict(passed=not reasons, gain=float(gain), differs=bool(differs), reasons=tuple(reasons))


# --------------------------------------------------------------------------------------------- report

@dataclass
class EloConfigResult:
    params: Dict[str, float]
    selection: Metrics
    selection_gain: PairedDelta  # vs the champion on the selection window


@dataclass
class CandidateResult:
    kind: str  # model family (model_version.name)
    label: str
    holdout: Metrics
    holdout_gain: PairedDelta  # vs the champion on the hold-out
    gate: GateVerdict
    selection: Optional[Metrics] = None
    selection_gain: Optional[PairedDelta] = None
    summary: Dict[str, Any] = field(default_factory=dict)  # what makes the candidate: Elo params or penalties
    deploy_params: Optional[Dict[str, Any]] = None  # model_version.params of the deployable version (gate passers)


@dataclass
class LabReport:
    seed: int
    n_games: int
    split: Dict[str, List[str]]
    champion_params: Dict[str, float]
    champion_selection: Metrics
    champion_holdout: Metrics
    configs_requested: int
    configs_evaluated: int
    elo_top: List[EloConfigResult]
    candidates: List[CandidateResult]
    partial: bool = False
    notes: List[str] = field(default_factory=list)
    elapsed_seconds: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _deployed_elo_params(data: LabData, params: EloParams, run: ModelRun, seed: int) -> Dict[str, Any]:
    """Elo version to deploy: the selected hyperparameters plus the margin sigma of the latest seasons."""
    last = data.completed_ranks[-1]
    residual = (data.margin - run.mu)[np.isin(data.ranks, data.completed_ranks[-SIGMA_LOOKBACK:])]
    return {
        **params.to_dict(),
        "sigma": round(float(math.sqrt(np.mean(residual**2))), 4),
        "trained_through": max(d for d, r in zip(data.features.dates, data.ranks) if r == last).isoformat(),
        "seasons_evaluated": [data.rank_labels[r] for r in data.completed_ranks],
        "seed": seed,
        "source": "model_lab",
    }


def run_lab(
    data: LabData,
    champion_params: EloParams,
    active: Sequence[ModelVersion] = (),
    *,
    seed: int = 42,
    n_configs: int = DEFAULT_CONFIGS,
    deadline: Optional[float] = None,
    clock: Callable[[], float] = time.monotonic,
    resamples: int = BOOTSTRAP_RESAMPLES,
    min_gain: float = GATE_MIN_GAIN,
    top_n: int = TOP_N,
    with_margin_features: bool = True,
) -> LabReport:
    """
    Run the whole lab on ``data``. ``deadline`` (``clock`` units) ends the work gracefully: at least the champion
    and one Elo configuration are always evaluated, anything skipped is listed in ``notes`` and ``partial`` is set.
    """
    started = clock()
    out_of_time = lambda: deadline is not None and clock() >= deadline
    split = make_split(data.completed_ranks)
    notes: List[str] = []

    champion = run_elo(data, champion_params, "champion")
    champion_selection = evaluate(data, champion, split.selection)
    champion_holdout = evaluate(data, champion, split.holdout)

    # ---- Elo random search, selected on the selection window only
    configs = search_elo_params(n_configs, seed)
    scored: List[Tuple[float, int, EloParams, ModelRun]] = []
    for index, params in enumerate(configs):
        if index > 0 and out_of_time():
            break
        run = run_elo(data, params, f"elo#{index}")
        rows = np.isin(data.ranks, list(split.selection))
        scored.append((float(log_loss_each(run.p[rows], data.win[rows]).mean()), index, params, run))
    partial = len(scored) < len(configs)
    if partial:
        notes.append(f"time budget reached: evaluated {len(scored)} of {len(configs)} Elo configurations")
    scored.sort(key=lambda item: (item[0], item[1]))

    elo_top = [
        EloConfigResult(
            params.to_dict(),
            evaluate(data, run, split.selection),
            paired_gain(data, champion, run, split.selection, seed, resamples),
        )
        for _, _, params, run in scored[:top_n]
    ]

    candidates: List[CandidateResult] = []
    _, best_index, best_params, best_run = scored[0]
    candidates.append(
        _candidate(
            data, split, champion, best_run, model_registry.ELO_FAMILY_NAME, f"elo_538 selected (cfg {best_index})",
            differs_from_active(model_registry.ELO_FAMILY_NAME, best_params, active), seed, resamples, min_gain,
            summary=best_params.to_dict(),
            selection=evaluate(data, best_run, split.selection),
            selection_gain=paired_gain(data, champion, best_run, split.selection, seed, resamples),
            deploy=lambda: _deployed_elo_params(data, best_params, best_run, seed),
        )
    )

    # ---- margin_features: walk-forward on the selection window, one fit through T-2 for the hold-out
    if with_margin_features:
        if out_of_time():
            partial = True
            notes.append("time budget reached: margin_features skipped")
        else:
            completed = data.completed_ranks
            usable = lambda before: [r for r in completed if BURN_IN_SEASONS <= r < before]
            walk_plan = [(usable(test), [test]) for test in split.selection if len(usable(test)) >= MIN_TRAIN_SEASONS]
            hold_plan = [([r for r in completed if r <= split.fit_through], list(split.holdout))]
            hold_run, hold_params = run_margin_features(data, hold_plan, seed)
            selection_metrics = selection_gain = None
            if not walk_plan:
                notes.append("margin_features selection-window walk-forward skipped: too few training seasons")
            elif out_of_time():
                partial = True
                notes.append("time budget reached: margin_features selection-window walk-forward skipped")
            else:
                walked = [test[0] for _, test in walk_plan]
                selection_run, _ = run_margin_features(data, walk_plan, seed)
                selection_metrics = evaluate(data, selection_run, walked)
                selection_gain = paired_gain(data, champion, selection_run, walked, seed, resamples)
            candidates.append(
                _candidate(
                    data, split, champion, hold_run, mfm.FAMILY_NAME, "margin_features",
                    differs_from_active(mfm.FAMILY_NAME, None, active), seed, resamples, min_gain,
                    summary={"ridge_alpha": hold_params["ridge"]["alpha"], "logistic_C": hold_params["logistic"]["C"],
                             "sigma": round(hold_params["sigma"], 4), "trained_through": hold_params["trained_through"]},
                    selection=selection_metrics,
                    selection_gain=selection_gain,
                    deploy=lambda: fit_margin_model(data, completed, seed),
                )
            )

    return LabReport(
        seed=seed,
        n_games=len(data.games),
        split={"selection": split.labels(data, split.selection), "holdout": split.labels(data, split.holdout)},
        champion_params=champion_params.to_dict(),
        champion_selection=champion_selection,
        champion_holdout=champion_holdout,
        configs_requested=len(configs),
        configs_evaluated=len(scored),
        elo_top=elo_top,
        candidates=candidates,
        partial=partial,
        notes=notes,
        elapsed_seconds=clock() - started,
    )


def _candidate(
    data: LabData, split: SeasonSplit, champion: ModelRun, run: ModelRun, kind: str, label: str, differs: bool,
    seed: int, resamples: int, min_gain: float, *, summary: Dict[str, Any], selection: Optional[Metrics],
    selection_gain: Optional[PairedDelta], deploy: Callable[[], Dict[str, Any]],
) -> CandidateResult:
    holdout = evaluate(data, run, split.holdout)
    gain = paired_gain(data, champion, run, split.holdout, seed, resamples)
    gate = evaluate_gate(gain.mean, differs, min_gain)
    return CandidateResult(
        kind=kind,
        label=label,
        holdout=holdout,
        holdout_gain=gain,
        gate=gate,
        selection=selection,
        selection_gain=selection_gain,
        summary=summary,
        deploy_params=deploy() if gate.passed else None,
    )


# ------------------------------------------------------------------------------------------ database

def load_lab_data(session: Session) -> LabData:
    service = EloRatingService(session)
    labels = {season_id: label for season_id, label in session.execute(select(Season.id, Season.season_label)).all()}
    return prepare_lab_data(service.load_games(), labels)


def lab_baseline(session: Session) -> Tuple[ModelVersion, EloParams, Optional[str]]:
    """
    The Elo model the lab measures candidates against, its parameters and, when it is not the champion, a note
    saying so. The lab replays Elo, so an Elo champion is the baseline; when another family holds the title (for
    example ``margin_features`` after a promotion) the best active Elo model (lowest ``brier_oos``) stands in and
    the report says so: a candidate that passes the historical gate then beat that Elo model, not the champion,
    and the live evaluation against the real champion still decides.
    """
    champion = model_registry.get_champion(session)
    if champion is None:
        raise LabError("the registry has no champion")
    if champion.name == model_registry.ELO_FAMILY_NAME:
        return champion, EloParams.from_dict(champion.params or {}), None
    elo_models = [row for row in model_registry.list_active(session) if row.name == model_registry.ELO_FAMILY_NAME]
    if not elo_models:
        raise LabError(f"the champion is {champion.name} and no {model_registry.ELO_FAMILY_NAME} model is active to serve as the baseline")
    baseline = min(elo_models, key=lambda row: (float(row.brier_oos) if row.brier_oos is not None else math.inf, row.id))
    note = (
        f"baseline: the champion is {champion.name} {champion.version}, which the lab cannot replay; candidates were "
        f"compared with the best active Elo model {baseline.name} {baseline.version}"
    )
    return baseline, EloParams.from_dict(baseline.params or {}), note


def champion_elo_params(session: Session) -> Tuple[ModelVersion, EloParams]:
    baseline, params, _ = lab_baseline(session)
    return baseline, params


def run_lab_on_database(session: Session, **kwargs: Any) -> LabReport:
    """Read-only: loads the games and the registry, runs the lab, writes nothing."""
    _, baseline_params, note = lab_baseline(session)
    report = run_lab(load_lab_data(session), baseline_params, model_registry.list_active(session), **kwargs)
    if note:
        report.notes.append(note)
    return report


# ---------------------------------------------------------------------------------- registration

@dataclass(frozen=True)
class PlannedModel:
    name: str
    version: str
    params: Dict[str, Any]
    notes: str
    brier_oos: float
    trained_at: datetime


@dataclass
class RegistrationResult:
    planned: List[PlannedModel] = field(default_factory=list)
    registered: List[ModelVersion] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)
    backfilled_rows: Dict[int, int] = field(default_factory=dict)  # model id -> rating rows written
    dry_run: bool = False


def check_registration_target(url: URL, confirm_database: Optional[str]) -> None:
    """Writing anywhere but SQLite needs the database name typed back: a deliberate act, never a default."""
    if url.get_backend_name() == "sqlite":
        return
    if confirm_database != url.database:
        raise RegistrationRefused(
            f"refusing to register on the {url.get_backend_name()} database {url.database!r}; "
            f"pass --confirm-database {url.database} to confirm"
        )


def candidate_version(params: Mapping[str, Any], trained_through: Optional[str]) -> str:
    digest = hashlib.sha1(json.dumps(params, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:6]
    stamp = (trained_through or date.today().isoformat()).replace("-", "")
    return f"lab-{stamp}-{digest}"


def _plan(report: LabReport, champion: ModelVersion, now: datetime) -> List[PlannedModel]:
    passed = sorted(
        (c for c in report.candidates if c.gate.passed and c.deploy_params is not None),
        key=lambda c: c.gate.gain,
        reverse=True,
    )
    planned = []
    for candidate in passed:
        params = dict(candidate.deploy_params)
        notes = {
            "source": "model_lab",
            "seed": report.seed,
            "split": report.split,
            "parent": f"{champion.name} {champion.version}",
            "holdout": asdict(candidate.holdout),
            "holdout_gain_vs_champion": asdict(candidate.holdout_gain),
            "champion_holdout": asdict(report.champion_holdout),
        }
        planned.append(
            PlannedModel(
                name=candidate.kind,
                version=candidate_version(params, params.get("trained_through")),
                params=params,
                notes=json.dumps(notes, sort_keys=True),
                brier_oos=round(candidate.holdout.brier, 5),
                trained_at=now,
            )
        )
    return planned


def register_candidates(
    session: Session,
    report: LabReport,
    *,
    dry_run: bool = False,
    confirm_database: Optional[str] = None,
    max_challengers: int = MAX_CHALLENGERS,
) -> RegistrationResult:
    """
    Insert the gate-passing candidates as challengers (parent = the champion) and, for Elo candidates, run the
    initial rating backfill so the first tick does not replay the whole history. ``dry_run`` only plans.
    Raises ``RegistrationRefused`` on a guarded database or when ``max_challengers`` (default 3) are already active.
    """
    if not dry_run:
        check_registration_target(session.get_bind().url, confirm_database)
    champion = model_registry.get_champion(session)
    if champion is None:
        raise RegistrationRefused("the registry has no champion to derive challengers from")
    active_challengers = [row for row in model_registry.list_active(session) if row.role == MODEL_ROLE_CHALLENGER]
    free_slots = max_challengers - len(active_challengers)
    if free_slots <= 0:
        raise RegistrationRefused(f"{len(active_challengers)} challengers are already active (maximum {max_challengers})")

    result = RegistrationResult(dry_run=dry_run)
    plan = _plan(report, champion, datetime.now(timezone.utc))
    if not plan:
        result.skipped.append("no candidate passed the historical gate")
        return result
    existing = {(row.name, row.version) for row in session.execute(select(ModelVersion)).scalars().all()}
    for item in plan:
        if (item.name, item.version) in existing:
            result.skipped.append(f"{item.name} {item.version} is already registered")
        elif len(result.planned) >= free_slots:
            result.skipped.append(f"{item.name} {item.version}: no free challenger slot")
        else:
            result.planned.append(item)
    if dry_run:
        return result

    for item in result.planned:
        try:
            row = ModelVersion(
                name=item.name,
                version=item.version,
                params=item.params,
                brier_oos=Decimal(f"{item.brier_oos:.5f}"),
                trained_at=item.trained_at,
                role=MODEL_ROLE_CHALLENGER,
                parent_id=champion.id,
                notes=item.notes,
            )
            session.add(row)
            session.flush()
            if item.name == model_registry.ELO_FAMILY_NAME:
                summary = EloRatingService(session, model_version_id=row.id).rebuild_all()  # commits
                result.backfilled_rows[row.id] = summary.rows_written
            else:
                session.commit()
        except Exception:
            session.rollback()
            raise
        result.registered.append(row)
    return result
