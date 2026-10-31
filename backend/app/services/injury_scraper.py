from dataclasses import dataclass, field
from datetime import datetime, timezone
import logging
from pathlib import Path
from typing import List, Optional

import httpx
from pydantic import BaseModel
from sqlmodel import Session, select

from app.models import InjuryEntry, InjuryReportSnapshot
from app.services.injury_report_parser import normalize_player_name

logger = logging.getLogger(__name__)


class InjuryItem(BaseModel):
    game_date: str = ""
    matchup: str = ""
    team: str = ""
    player_name: str = ""
    status: str = ""  # Out, Questionable, Doubtful, Probable, Available
    reason: str = ""
    game_time: Optional[str] = None
    availability_prob: Optional[float] = None


@dataclass
class InjuryReport:
    available: bool
    reason: Optional[str] = None
    fetched_at: Optional[datetime] = None
    rows: List[InjuryItem] = field(default_factory=list)
    snapshot_id: Optional[int] = None
    snapshot_timestamp: Optional[datetime] = None


class InjuryScraperService:
    """Provides injury report data for the props pipeline from database snapshots."""

    USER_AGENT = "ArchetypeNBA-research/1.0 (personal, low frequency)"
    MAX_AGE_HOURS = 36  # Snapshots older than 36h are considered stale

    def __init__(
        self,
        session: Optional[Session] = None,
        timeout: float = 30.0,
        http_client: Optional[httpx.Client] = None,
        cache_file: Optional[Path] = None,
    ):
        self.session = session
        self.timeout = timeout
        self.http_client = http_client
        self.cache_file = cache_file

    def fetch_injury_report(self, session: Optional[Session] = None) -> InjuryReport:
        """
        Returns real rows from the latest stored database snapshot.
        If the snapshot is older than 36 hours, returns available=False with reason 'stale'.
        If no snapshot exists, returns available=False with truthful reason.
        Never fabricates or invents data.
        """
        now = datetime.now(timezone.utc)
        sess = session or self.session
        close_sess = False

        if sess is None:
            try:
                from app.deps import engine
                sess = Session(engine)
                close_sess = True
            except Exception as e:
                logger.warning("Could not obtain DB session for InjuryScraperService: %s", e)
                return InjuryReport(
                    available=False,
                    reason=f"database unavailable: {e}",
                    fetched_at=now,
                    rows=[],
                )

        try:
            snapshot = sess.exec(
                select(InjuryReportSnapshot).order_by(
                    InjuryReportSnapshot.report_timestamp.desc(),
                    InjuryReportSnapshot.id.desc(),
                )
            ).first()

            if snapshot is None:
                return InjuryReport(
                    available=False,
                    reason="no injury report snapshot in database",
                    fetched_at=now,
                    rows=[],
                )

            snap_fetched = snapshot.fetched_at
            if snap_fetched.tzinfo is None:
                snap_fetched = snap_fetched.replace(tzinfo=timezone.utc)
            else:
                snap_fetched = snap_fetched.astimezone(timezone.utc)

            age_seconds = (now - snap_fetched).total_seconds()
            if age_seconds > self.MAX_AGE_HOURS * 3600.0:
                logger.info(
                    "Latest injury snapshot id=%s is %.1f hours old (> 36h); marking stale.",
                    snapshot.id,
                    age_seconds / 3600.0,
                )
                return InjuryReport(
                    available=False,
                    reason="stale",
                    fetched_at=snap_fetched,
                    rows=[],
                    snapshot_id=snapshot.id,
                    snapshot_timestamp=snapshot.report_timestamp,
                )

            entries = sess.exec(
                select(InjuryEntry).where(InjuryEntry.snapshot_id == snapshot.id)
            ).all()

            rows = [
                InjuryItem(
                    game_date=e.game_date,
                    matchup=e.matchup or "",
                    team=e.team_name or "",
                    player_name=normalize_player_name(e.player_name_raw),
                    status=e.status,
                    reason=e.reason or "",
                    game_time=e.game_time_et,
                    availability_prob=float(e.availability_prob)
                    if e.availability_prob is not None
                    else None,
                )
                for e in entries
            ]

            return InjuryReport(
                available=True,
                reason=None,
                fetched_at=snap_fetched,
                rows=rows,
                snapshot_id=snapshot.id,
                snapshot_timestamp=snapshot.report_timestamp,
            )

        except Exception as e:
            logger.warning("Error fetching injury report from database: %s", e)
            return InjuryReport(
                available=False,
                reason=f"error: {e}",
                fetched_at=now,
                rows=[],
            )
        finally:
            if close_sess and sess is not None:
                sess.close()
