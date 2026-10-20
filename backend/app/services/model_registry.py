"""
Model registry: which models exist, which one is the champion and which ones run in shadow.

``model_version.role`` is one of ``champion`` (drives the paper bets, at most one), ``challenger`` (records
shadow predictions only) or ``retired`` (ignored). A *model family* (the ``name`` of a model_version) is the code
that turns the version's ``params`` into predictions.

Databases that predate roles (and test fixtures that register the model without one) have no champion row: in
that case the single registered ``elo_538`` ``1.1`` model counts as the champion, which is exactly what the
schema migration turns it into.
"""
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import select
from sqlmodel import Session

from app.models import MODEL_ROLE_CHALLENGER, MODEL_ROLE_CHAMPION, MODEL_ROLE_RETIRED, ModelVersion

ELO_FAMILY_NAME = "elo_538"
LEGACY_CHAMPION_VERSION = "1.1"  # 1.1: home advantage 60 (538 original: 100)


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
