"""
Model registry: which models exist, which one is the champion and which ones run in shadow.

``model_version.role`` is one of ``champion`` (drives the paper bets, at most one), ``challenger`` (records
shadow predictions only) or ``retired`` (ignored). A *model family* (the ``name`` of a model_version) is the code
that turns the version's ``params`` into predictions.

A family exposes ``predict(home_team_id, away_team_id, season_id, game_time) -> Prediction | None`` (``None`` =
the model cannot predict that game, for example because a team has no rating yet) and is built per run by
``load_model``; the registry maps ``model_version.name`` to the factory that builds it.

Databases that predate roles (and test fixtures that register the model without one) have no champion row: in
that case the single registered ``elo_538`` ``1.1`` model counts as the champion, which is exactly what the
schema migration turns it into.
"""
import importlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, Protocol

from sqlalchemy import select
from sqlmodel import Session

from app.analytics.elo import EloParams
from app.models import MODEL_ROLE_CHALLENGER, MODEL_ROLE_CHAMPION, MODEL_ROLE_RETIRED, ModelVersion

ELO_FAMILY_NAME = "elo_538"
LEGACY_CHAMPION_VERSION = "1.1"  # 1.1: home advantage 60 (538 original: 100)


class ModelRegistryError(RuntimeError):
    """A model version cannot be turned into a predictor (unknown family, unusable params)."""


@dataclass(frozen=True)
class Prediction:
    p_home: float  # P(home wins)
    mu: float  # expected home margin in points
    sigma: float  # standard deviation of the margin


class ModelFamily(Protocol):
    name: str
    version: str
    model_version_id: int

    def predict(
        self, home_team_id: int, away_team_id: int, season_id: int, game_time: datetime
    ) -> Optional[Prediction]:
        """Pre-game prediction using only information available before ``game_time``; None when impossible."""
        ...


def get_champion(session: Session) -> Optional[ModelVersion]:
    """The champion model version, else the legacy elo_538 1.1 row (unless retired), else None."""
    champion = session.execute(
        select(ModelVersion).where(ModelVersion.role == MODEL_ROLE_CHAMPION)
    ).scalar_one_or_none()
    if champion is not None:
        return champion
    return session.execute(
        select(ModelVersion).where(
            ModelVersion.name == ELO_FAMILY_NAME,
            ModelVersion.version == LEGACY_CHAMPION_VERSION,
            ModelVersion.role != MODEL_ROLE_RETIRED,
        )
    ).scalar_one_or_none()


def list_active(session: Session) -> List[ModelVersion]:
    """The champion (when there is one) followed by every challenger, oldest first. Retired models are left out."""
    champion = get_champion(session)
    challengers = session.execute(
        select(ModelVersion).where(ModelVersion.role == MODEL_ROLE_CHALLENGER).order_by(ModelVersion.id)
    ).scalars().all()
    return ([champion] if champion is not None else []) + [
        row for row in challengers if champion is None or row.id != champion.id
    ]


def get_elo_reference(session: Session) -> Optional[ModelVersion]:
    """
    The Elo model that stays the default for rating queries, whatever family the champion is: the champion
    itself when it is an Elo model, else the most recent active ``elo_538`` row (the previous champion usually
    stays registered as a challenger), else, as a last resort, the most recent ``elo_538`` row of any role.
    """
    champion = get_champion(session)
    if champion is not None and champion.name == ELO_FAMILY_NAME:
        return champion
    active = [row for row in list_active(session) if row.name == ELO_FAMILY_NAME]
    if active:
        return max(active, key=lambda row: row.id)
    return session.execute(
        select(ModelVersion).where(ModelVersion.name == ELO_FAMILY_NAME).order_by(ModelVersion.id.desc()).limit(1)
    ).scalar_one_or_none()


def ensure_elo_reference(session: Session) -> ModelVersion:
    """
    The Elo reference model, registering the default elo_538 1.1 first when no Elo model exists (as the champion
    when the registry has none, else as a challenger). Flushes, never commits.
    """
    row = get_elo_reference(session)
    if row is not None:
        return row
    has_champion = get_champion(session) is not None
    row = ModelVersion(
        name=ELO_FAMILY_NAME,
        version=LEGACY_CHAMPION_VERSION,
        params={},
        role=MODEL_ROLE_CHALLENGER if has_champion else MODEL_ROLE_CHAMPION,
        promoted_at=None if has_champion else datetime.now(timezone.utc),
    )
    session.add(row)
    session.flush()
    return row


def ensure_default_champion(session: Session) -> ModelVersion:
    """
    The champion, registering the default elo_538 1.1 model as champion first when the registry has none.
    Flushes, never commits: the caller owns the transaction.
    """
    row = get_champion(session)
    if row is None:
        row = ModelVersion(
            name=ELO_FAMILY_NAME,
            version=LEGACY_CHAMPION_VERSION,
            params={},
            role=MODEL_ROLE_CHAMPION,
            promoted_at=datetime.now(timezone.utc),
        )
        session.add(row)
        session.flush()
    return row


# ------------------------------------------------------------------------------------------- families

class EloFamily:
    """``elo_538``: Elo with hyperparameters in ``params`` (missing keys keep the defaults) and a margin sigma."""

    def __init__(self, session: Session, model_version: ModelVersion):
        from app.services.elo_service import EloRatingService  # lazy: elo_service imports this module

        params = model_version.params or {}
        sigma = float(params.get("sigma") or 0.0)
        if sigma <= 0:
            raise ModelRegistryError(f"model_version {model_version.name} {model_version.version} has no sigma in its params")
        self.name = model_version.name
        self.version = model_version.version
        self.model_version_id = model_version.id
        self.sigma = sigma
        self._service = EloRatingService(
            session, sigma=sigma, model_version_id=model_version.id, params=EloParams.from_dict(params)
        )
        self._ratings: Dict[int, Dict[int, float]] = {}  # season id -> current ratings (with the season carryover)

    def predict(
        self, home_team_id: int, away_team_id: int, season_id: int, game_time: datetime
    ) -> Optional[Prediction]:
        if season_id not in self._ratings:
            self._ratings[season_id] = self._service.current_ratings(for_season_id=season_id)
        ratings = self._ratings[season_id]
        if home_team_id not in ratings or away_team_id not in ratings:
            return None
        prediction = self._service.predict(home_team_id, away_team_id, ratings)
        return Prediction(prediction.p_home, prediction.expected_margin, prediction.sigma)


FamilyFactory = Callable[[Session, ModelVersion], ModelFamily]

_FAMILIES: Dict[str, FamilyFactory] = {ELO_FAMILY_NAME: EloFamily}
# Families defined in their own module register themselves on import; load_model imports them on first use.
_FAMILY_MODULES: Dict[str, str] = {"margin_features": "app.services.margin_features_model"}


def register_family(name: str, factory: FamilyFactory) -> None:
    """Make ``model_version`` rows named ``name`` loadable (used by model families defined elsewhere)."""
    _FAMILIES[name] = factory


def _import_family_module(name: str) -> None:
    """Import the module that registers family ``name`` (a model_version row is loadable without prior imports)."""
    module = _FAMILY_MODULES.get(name)
    if module is None:
        return
    try:
        importlib.import_module(module)
    except Exception as exc:  # a broken family module must not escape as a bare ImportError (or anything else)
        raise ModelRegistryError(f"model family {name}: cannot import {module}: {exc!r}") from exc


def load_model(session: Session, model_version: ModelVersion) -> ModelFamily:
    """Build the predictor of a model version from its ``params``."""
    if model_version.name not in _FAMILIES:
        _import_family_module(model_version.name)
    factory = _FAMILIES.get(model_version.name)
    if factory is None:
        raise ModelRegistryError(f"model_version {model_version.name} {model_version.version}: unknown model family")
    try:
        return factory(session, model_version)
    except ModelRegistryError:
        raise
    except Exception as exc:  # constructing a family from malformed params can fail in any number of ways
        raise ModelRegistryError(
            f"model_version {model_version.name} {model_version.version}: cannot build the model: {exc!r}"
        ) from exc
