from datetime import datetime, timedelta, timezone
from decimal import Decimal
import inspect
import pytest
from sqlmodel import Session

from app.models import InjuryEntry, InjuryReportSnapshot
from app.services import injury_scraper as injury_module
from app.services.injury_scraper import InjuryItem, InjuryReport, InjuryScraperService


def test_no_fabricated_data_in_source_or_output(db_session: Session):
    """Agreements rule 3: never fabricate data."""
    # 1. Structural/source check
    source = inspect.getsource(injury_module)
    assert "_get_fallback_sample_report" not in source
    assert "Anthony Davis" not in source
    assert "Luka Doncic" not in source

    # 2. Method existence check
    scraper = InjuryScraperService(session=db_session)
    assert not hasattr(scraper, "_get_fallback_sample_report")

    # 3. Behavioural check: when unavailable, rows is strictly empty
    report = scraper.fetch_injury_report()
    assert report.available is False
    assert report.rows == []


def test_injury_scraper_no_snapshot_in_db(db_session: Session):
    scraper = InjuryScraperService(session=db_session)
    report = scraper.fetch_injury_report()

    assert report.available is False
    assert "no injury report snapshot" in report.reason
    assert report.rows == []


def test_injury_scraper_stale_snapshot(db_session: Session):
    session = db_session
    now = datetime.now(timezone.utc)
    stale_time = now - timedelta(hours=40)  # > 36h

    snap = InjuryReportSnapshot(
        source="nba_official_pdf",
        report_url="https://ak-static.cms.nba.com/referee/injury/Injury-Report_old.pdf",
        report_timestamp=stale_time,
        fetched_at=stale_time,
        sha256="old_sha256_hash",
        entries_count=1,
    )
    session.add(snap)
    session.flush()

    entry = InjuryEntry(
        snapshot_id=snap.id,
        game_date="10/28/2026",
        matchup="POR@UTA",
        team_name="Portland Trail Blazers",
        player_name_raw="Morant, Ja",
        status="Out",
        reason="Hamstring",
        availability_prob=Decimal("0.00"),
    )
    session.add(entry)
    session.commit()

    scraper = InjuryScraperService(session=session)
    report = scraper.fetch_injury_report()

    assert report.available is False
    assert report.reason == "stale"
    assert report.rows == []
    assert report.snapshot_id == snap.id


def test_injury_scraper_recent_snapshot_success(db_session: Session):
    session = db_session
    now = datetime.now(timezone.utc)
    recent_time = now - timedelta(hours=2)  # < 36h

    snap = InjuryReportSnapshot(
        source="nba_official_pdf",
        report_url="https://ak-static.cms.nba.com/referee/injury/Injury-Report_new.pdf",
        report_timestamp=recent_time,
        fetched_at=recent_time,
        sha256="recent_sha256_hash",
        entries_count=2,
    )
    session.add(snap)
    session.flush()

    e1 = InjuryEntry(
        snapshot_id=snap.id,
        game_date="10/31/2026",
        matchup="POR@UTA",
        team_name="Portland Trail Blazers",
        player_name_raw="Morant, Ja",
        status="Out",
        reason="Hamstring Strain",
        availability_prob=Decimal("0.00"),
    )
    e2 = InjuryEntry(
        snapshot_id=snap.id,
        game_date="10/31/2026",
        matchup="POR@UTA",
        team_name="Portland Trail Blazers",
        player_name_raw="Williams III, Robert",
        status="Available",
        reason="Knee management",
        availability_prob=Decimal("1.00"),
    )
    session.add_all([e1, e2])
    session.commit()

    scraper = InjuryScraperService(session=session)
    report = scraper.fetch_injury_report()

    assert report.available is True
    assert report.reason is None
    assert report.snapshot_id == snap.id
    assert len(report.rows) == 2

    r0 = report.rows[0]
    assert r0.player_name == "Ja Morant"
    assert r0.status == "Out"
    assert r0.availability_prob == 0.0

    r1 = report.rows[1]
    assert r1.player_name == "Robert Williams III"
    assert r1.status == "Available"
    assert r1.availability_prob == 1.0
