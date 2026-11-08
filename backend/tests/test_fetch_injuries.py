from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import pytest
from sqlmodel import Session

from app.config import settings
from app.models import Game, InjuryReportSnapshot, Season, Team
from scripts.fetch_injuries import run_fetch_injuries

LOCAL_TZ = ZoneInfo("America/Mexico_City")


def test_fetch_injuries_disabled(capsys):
    settings.INJURY_PDF_ENABLED = False
    code = run_fetch_injuries(dry_run=True)
    assert code == 0
    captured = capsys.readouterr()
    assert "INJURY_PDF_ENABLED is False" in captured.out


def test_fetch_injuries_no_games_today(db_session: Session, monkeypatch, capsys):
    monkeypatch.setattr(settings, "INJURY_PDF_ENABLED", True)
    fixed_now = datetime(2026, 10, 31, 10, 0, 0, tzinfo=LOCAL_TZ)

    code = run_fetch_injuries(dry_run=True, now=fixed_now, session=db_session)
    assert code == 0
    captured = capsys.readouterr()
    assert "No games scheduled for today" in captured.out


def test_fetch_injuries_dry_run_decision(db_session: Session, monkeypatch, capsys):
    monkeypatch.setattr(settings, "INJURY_PDF_ENABLED", True)
    session = db_session

    season = Season(season_label="2026-27", is_active=True)
    session.add(season)
    session.flush()

    home_t = Team(abbreviation="UTA", full_name="Utah Jazz", city="Salt Lake City", conference="West", division="NW")
    away_t = Team(abbreviation="POR", full_name="Portland Trail Blazers", city="Portland", conference="West", division="NW")
    session.add_all([home_t, away_t])
    session.flush()

    tipoff = datetime(2026, 10, 31, 19, 0, 0, tzinfo=LOCAL_TZ).astimezone(timezone.utc)
    game = Game(
        season_id=season.id,
        home_team_id=home_t.id,
        away_team_id=away_t.id,
        commence_time=tipoff,
        status="scheduled",
    )
    session.add(game)
    session.commit()

    # 1. At 08:30: not due yet
    t_0830 = datetime(2026, 10, 31, 8, 30, 0, tzinfo=LOCAL_TZ)
    code = run_fetch_injuries(dry_run=True, now=t_0830, session=session)
    assert code == 0
    captured = capsys.readouterr()
    assert "Injury fetch NOT due" in captured.out

    # 2. At 09:30: is due (dry run, does not hit network)
    t_0930 = datetime(2026, 10, 31, 9, 30, 0, tzinfo=LOCAL_TZ)
    code = run_fetch_injuries(dry_run=True, now=t_0930, session=session)
    assert code == 0
    captured = capsys.readouterr()
    assert "Injury fetch IS DUE" in captured.out
    assert "Would download newest PDF" in captured.out


def test_backfilled_snapshots_do_not_count_as_live_downloads(db_session: Session, monkeypatch, capsys):
    monkeypatch.setattr(settings, "INJURY_PDF_ENABLED", True)
    session = db_session
    season = Season(season_label="2026-27", is_active=True)
    session.add(season)
    session.flush()
    home_t = Team(abbreviation="UTA", full_name="Utah Jazz", city="Salt Lake City", conference="West", division="NW")
    away_t = Team(abbreviation="POR", full_name="Portland Trail Blazers", city="Portland", conference="West", division="NW")
    session.add_all([home_t, away_t])
    session.flush()
    tipoff = datetime(2026, 10, 31, 19, 0, 0, tzinfo=LOCAL_TZ).astimezone(timezone.utc)
    session.add(Game(season_id=season.id, home_team_id=home_t.id, away_team_id=away_t.id,
                     commence_time=tipoff, status="scheduled"))
    fetched = datetime(2026, 10, 31, 8, 0, 0, tzinfo=LOCAL_TZ).astimezone(timezone.utc)
    for i in range(5):  # a historical backfill fetched today, reports from 2019
        session.add(InjuryReportSnapshot(
            source="nba_official", report_url=f"https://example.invalid/Injury-Report_2019-12-0{i + 1}_05PM.pdf",
            report_timestamp=datetime(2019, 12, i + 1, 22, 30, tzinfo=timezone.utc), fetched_at=fetched,
            sha256=f"{i:064d}", entries_count=0,
        ))
    session.commit()

    code = run_fetch_injuries(dry_run=True, now=datetime(2026, 10, 31, 9, 30, 0, tzinfo=LOCAL_TZ), session=session)
    assert code == 0
    captured = capsys.readouterr()
    assert "downloads=0/" in captured.out
    assert "Injury fetch IS DUE" in captured.out
