from datetime import datetime, time, timezone
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo
import pytest
from sqlmodel import Session, select
import httpx

from app.models import (
    Game,
    InjuryEntry,
    InjuryReportSnapshot,
    Player,
    PlayerSeasonStats,
    Season,
    Team,
)
from app.services.injury_report_service import (
    InjuryReportService,
    injury_fetch_due,
    parse_pdf_filename_timestamp,
    select_newest_pdf_url,
)

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
LOCAL_TZ = ZoneInfo("America/Mexico_City")


def test_injury_fetch_due_zero_on_days_without_games():
    now = datetime(2026, 10, 31, 10, 0, tzinfo=LOCAL_TZ)
    assert injury_fetch_due(now, games_today_commence_times=[], downloads_today_local_times=[]) is False


def test_injury_fetch_due_max_per_day():
    now = datetime(2026, 10, 31, 18, 0, tzinfo=LOCAL_TZ)
    games = [datetime(2026, 10, 31, 19, 0, tzinfo=LOCAL_TZ)]
    downloads = [
        datetime(2026, 10, 31, 9, 15, tzinfo=LOCAL_TZ),
        datetime(2026, 10, 31, 14, 15, tzinfo=LOCAL_TZ),
        datetime(2026, 10, 31, 17, 30, tzinfo=LOCAL_TZ),
    ]
    # Already 3 downloads
    assert injury_fetch_due(now, games, downloads, max_per_day=3) is False


def test_injury_fetch_due_cooldown_60_minutes():
    # Only 30 minutes since last download
    d1 = datetime(2026, 10, 31, 9, 0, tzinfo=LOCAL_TZ)
    now = datetime(2026, 10, 31, 9, 30, tzinfo=LOCAL_TZ)
    games = [datetime(2026, 10, 31, 19, 0, tzinfo=LOCAL_TZ)]
    assert injury_fetch_due(now, games, [d1]) is False

    # 65 minutes since last download and after 14:00
    d2 = datetime(2026, 10, 31, 12, 0, tzinfo=LOCAL_TZ)
    now2 = datetime(2026, 10, 31, 14, 5, tzinfo=LOCAL_TZ)
    assert injury_fetch_due(now2, games, [d2]) is True


def test_injury_fetch_due_slot_progression():
    games = [datetime(2026, 10, 31, 19, 0, tzinfo=LOCAL_TZ)]

    # 1. Before 09:00: not due
    t_0830 = datetime(2026, 10, 31, 8, 30, tzinfo=LOCAL_TZ)
    assert injury_fetch_due(t_0830, games, []) is False

    # 2. Slot 1 (after 09:00): due
    t_0905 = datetime(2026, 10, 31, 9, 5, tzinfo=LOCAL_TZ)
    assert injury_fetch_due(t_0905, games, []) is True

    # After download 1 at 09:05:
    downloads = [t_0905]

    # At 11:30: not due (not after 14:00, not within 60-120m of 19:00)
    t_1130 = datetime(2026, 10, 31, 11, 30, tzinfo=LOCAL_TZ)
    assert injury_fetch_due(t_1130, games, downloads) is False

    # 3. Slot 2 (after 14:00): due
    t_1410 = datetime(2026, 10, 31, 14, 10, tzinfo=LOCAL_TZ)
    assert injury_fetch_due(t_1410, games, downloads) is True

    # After download 2 at 14:10:
    downloads.append(t_1410)

    # At 16:00: not due (180 min to tipoff)
    t_1600 = datetime(2026, 10, 31, 16, 0, tzinfo=LOCAL_TZ)
    assert injury_fetch_due(t_1600, games, downloads) is False

    # 4. Slot 3 (tip-off within 60-120 min, e.g. 90m before 19:00 -> 17:30): due
    t_1730 = datetime(2026, 10, 31, 17, 30, tzinfo=LOCAL_TZ)
    assert injury_fetch_due(t_1730, games, downloads) is True


def test_parse_pdf_filename_timestamp():
    url = "https://ak-static.cms.nba.com/referee/injury/Injury-Report_2026-10-31_06_45PM.pdf"
    ts = parse_pdf_filename_timestamp(url)
    assert ts is not None
    # 2026-10-31 18:45 EDT -> 2026-10-31 22:45 UTC
    assert ts.year == 2026
    assert ts.month == 10
    assert ts.day == 31
    assert ts.hour == 22
    assert ts.minute == 45
    assert ts.tzinfo == timezone.utc


def test_select_newest_pdf_url():
    html = """
    <html><body>
    <a href="https://ak-static.cms.nba.com/referee/injury/Injury-Report_2026-10-31_01_00PM.pdf">1:00 PM</a>
    <a href="https://ak-static.cms.nba.com/referee/injury/Injury-Report_2026-10-31_06_45PM.pdf">6:45 PM</a>
    <a href="https://ak-static.cms.nba.com/referee/injury/Injury-Report_2026-10-31_03_30PM.pdf">3:30 PM</a>
    </body></html>
    """
    newest = select_newest_pdf_url(html)
    assert newest == "https://ak-static.cms.nba.com/referee/injury/Injury-Report_2026-10-31_06_45PM.pdf"


def test_injury_report_service_fetch_and_store_idempotent(db_session: Session):
    session = db_session
    # Setup seed data in in-memory test DB
    season = Season(season_label="2026-27", is_active=True)
    session.add(season)
    session.flush()

    team_por = Team(abbreviation="POR", full_name="Portland Trail Blazers", city="Portland", conference="West", division="NW")
    team_uta = Team(abbreviation="UTA", full_name="Utah Jazz", city="Salt Lake City", conference="West", division="NW")
    session.add_all([team_por, team_uta])
    session.flush()

    p1 = Player(full_name="Jordan Kent", is_active=True)
    p2 = Player(full_name="Ethan Baker Jr.", is_active=True)
    session.add_all([p1, p2])
    session.flush()

    # Link p1 and p2 to Portland
    pss1 = PlayerSeasonStats(player_id=p1.id, team_id=team_por.id, season_id=season.id)
    pss2 = PlayerSeasonStats(player_id=p2.id, team_id=team_por.id, season_id=season.id)
    session.add_all([pss1, pss2])
    session.commit()

    # Read synthetic fixture text
    fixture_path = FIXTURES_DIR / "synthetic_injury_report_layout.txt"
    with open(fixture_path, "r", encoding="utf-8") as f:
        fixture_layout_text = f.read()

    dummy_pdf_bytes = b"%PDF-1.4 dummy pdf bytes for test"

    # Mock HTTP client
    def custom_handler(request: httpx.Request) -> httpx.Response:
        url_str = str(request.url)
        if "Injury-Report" in url_str:
            return httpx.Response(200, content=dummy_pdf_bytes)
        return httpx.Response(
            200,
            text='<a href="https://ak-static.cms.nba.com/referee/injury/Injury-Report_2026-10-31_06_45PM.pdf">Latest</a>',
        )

    mock_client = httpx.Client(transport=httpx.MockTransport(custom_handler))

    # Inject mock extractor returning fixture layout text
    def mock_extractor(pdf_bytes: bytes) -> str:
        return fixture_layout_text

    service = InjuryReportService(
        session=session,
        http_client=mock_client,
        pdf_text_extractor=mock_extractor,
    )

    # 1. First fetch: creates snapshot and entries
    snap, created, unresolved = service.fetch_and_store_snapshot()
    assert created is True
    assert snap is not None
    assert snap.entries_count == 6

    # Verify rows in DB
    entries = session.exec(select(InjuryEntry).where(InjuryEntry.snapshot_id == snap.id)).all()
    assert len(entries) == 6

    # Verify player resolution
    kent_entry = next(e for e in entries if "Kent" in e.player_name_raw)
    assert kent_entry.player_id == p1.id
    assert kent_entry.team_name == "Portland Trail Blazers"

    baker_entry = next(e for e in entries if "Baker" in e.player_name_raw)
    assert baker_entry.player_id == p2.id
    assert baker_entry.team_name == "Portland Trail Blazers"

    # Verify Available row kept
    smith_entry = next(e for e in entries if "Smith" in e.player_name_raw)
    assert smith_entry.status == "Available"
    assert smith_entry.availability_prob == Decimal("1.00")

    # 2. Second fetch with identical PDF: idempotent, returns existing snapshot, 0 new rows
    snap2, created2, unresolved2 = service.fetch_and_store_snapshot()
    assert created2 is False
    assert snap2.id == snap.id

    # Count of entries in DB remains 6
    all_entries = session.exec(select(InjuryEntry)).all()
    assert len(all_entries) == 6
