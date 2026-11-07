from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import List
from zoneinfo import ZoneInfo

import httpx
import pytest
from sqlmodel import Session, select

from app.config import settings
from app.models import (
    Game,
    InjuryEntry,
    InjuryReportSnapshot,
    Player,
    PlayerGameLog,
    PlayerSeasonStats,
    Season,
    Team,
)
from app.services.injury_report_service import (
    ARCHIVE_START_DATE,
    EASTERN_TZ,
    InjuryReportService,
    backfill_injury_reports,
    build_candidate_pdf_urls,
    build_injury_pdf_url,
    discover_game_dates,
    parse_pdf_filename_timestamp,
    plan_backfill_slots,
)
from scripts.backfill_injuries import build_parser, run_backfill_injuries

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def _load_fixture_text() -> str:
    with open(FIXTURES_DIR / "synthetic_injury_report_layout.txt", "r", encoding="utf-8") as f:
        return f.read()


def test_url_builder_both_eras_and_ampm_edge_cases():
    d_modern = date(2025, 1, 15)
    d_archive = date(2018, 12, 17)

    # 1. Midnight (00:00 -> 12:00AM / 12AM)
    assert (
        build_injury_pdf_url(d_modern, time(0, 0), hourly=False)
        == "https://ak-static.cms.nba.com/referee/injury/Injury-Report_2025-01-15_12_00AM.pdf"
    )
    assert (
        build_injury_pdf_url(d_archive, time(0, 0), hourly=True)
        == "https://ak-static.cms.nba.com/referee/injury/Injury-Report_2018-12-17_12AM.pdf"
    )

    # 2. 12:30 AM (00:30 -> 12_30AM)
    assert (
        build_injury_pdf_url(d_modern, time(0, 30), hourly=False)
        == "https://ak-static.cms.nba.com/referee/injury/Injury-Report_2025-01-15_12_30AM.pdf"
    )

    # 3. Morning (09:15 AM -> 09_15AM, 09:00 AM -> 09AM)
    assert (
        build_injury_pdf_url(d_modern, time(9, 15), hourly=False)
        == "https://ak-static.cms.nba.com/referee/injury/Injury-Report_2025-01-15_09_15AM.pdf"
    )
    assert (
        build_injury_pdf_url(d_archive, time(9, 0), hourly=True)
        == "https://ak-static.cms.nba.com/referee/injury/Injury-Report_2018-12-17_09AM.pdf"
    )

    # 4. Noon (12:00 -> 12_00PM / 12PM) and 12:45 PM
    assert (
        build_injury_pdf_url(d_modern, time(12, 0), hourly=False)
        == "https://ak-static.cms.nba.com/referee/injury/Injury-Report_2025-01-15_12_00PM.pdf"
    )
    assert (
        build_injury_pdf_url(d_archive, time(12, 0), hourly=True)
        == "https://ak-static.cms.nba.com/referee/injury/Injury-Report_2018-12-17_12PM.pdf"
    )
    assert (
        build_injury_pdf_url(d_modern, time(12, 45), hourly=False)
        == "https://ak-static.cms.nba.com/referee/injury/Injury-Report_2025-01-15_12_45PM.pdf"
    )

    # 5. Afternoon / Evening (17:00 -> 05_00PM / 05PM, 19:30 -> 07_30PM, 23:45 -> 11_45PM)
    assert (
        build_injury_pdf_url(d_modern, time(17, 0), hourly=False)
        == "https://ak-static.cms.nba.com/referee/injury/Injury-Report_2025-01-15_05_00PM.pdf"
    )
    assert (
        build_injury_pdf_url(d_archive, time(17, 0), hourly=True)
        == "https://ak-static.cms.nba.com/referee/injury/Injury-Report_2018-12-17_05PM.pdf"
    )
    assert (
        build_injury_pdf_url(d_modern, time(19, 30), hourly=False)
        == "https://ak-static.cms.nba.com/referee/injury/Injury-Report_2025-01-15_07_30PM.pdf"
    )
    assert (
        build_injury_pdf_url(d_modern, time(23, 45), hourly=False)
        == "https://ak-static.cms.nba.com/referee/injury/Injury-Report_2025-01-15_11_45PM.pdf"
    )


def test_parse_pdf_filename_timestamp_both_eras_and_edge_cases():
    # Hourly era: 2018-12-17 05PM EST (UTC-5) -> 2018-12-17 22:00 UTC
    ts_hourly = parse_pdf_filename_timestamp(
        "https://ak-static.cms.nba.com/referee/injury/Injury-Report_2018-12-17_05PM.pdf"
    )
    assert ts_hourly == datetime(2018, 12, 17, 22, 0, tzinfo=timezone.utc)

    # 15-minute era: 2025-01-15 07:30PM EST (UTC-5) -> 2025-01-16 00:30 UTC
    ts_15m = parse_pdf_filename_timestamp(
        "https://ak-static.cms.nba.com/referee/injury/Injury-Report_2025-01-15_07_30PM.pdf"
    )
    assert ts_15m == datetime(2025, 1, 16, 0, 30, tzinfo=timezone.utc)

    # 12AM (midnight) and 12PM (noon)
    ts_midnight = parse_pdf_filename_timestamp(
        "https://ak-static.cms.nba.com/referee/injury/Injury-Report_2025-01-15_12_00AM.pdf"
    )
    assert ts_midnight == datetime(2025, 1, 15, 5, 0, tzinfo=timezone.utc)

    ts_noon = parse_pdf_filename_timestamp(
        "https://ak-static.cms.nba.com/referee/injury/Injury-Report_2025-01-15_12PM.pdf"
    )
    assert ts_noon == datetime(2025, 1, 15, 17, 0, tzinfo=timezone.utc)

    # Invalid filenames return None
    assert parse_pdf_filename_timestamp("https://example.com/other.pdf") is None
    assert (
        parse_pdf_filename_timestamp(
            "https://ak-static.cms.nba.com/referee/injury/Injury-Report_2025-01-15_13_00PM.pdf"
        )
        is None
    )


def test_build_candidate_pdf_urls_newest_first_and_leak_free():
    d = date(2019, 1, 10)
    # 5:00 PM ET cutoff -> newest-first within [16:15, 17:00], includes 05_00PM and 05PM
    cands_5pm = build_candidate_pdf_urls(d, time(17, 0))
    assert cands_5pm == [
        "https://ak-static.cms.nba.com/referee/injury/Injury-Report_2019-01-10_05_00PM.pdf",
        "https://ak-static.cms.nba.com/referee/injury/Injury-Report_2019-01-10_05PM.pdf",
        "https://ak-static.cms.nba.com/referee/injury/Injury-Report_2019-01-10_04_45PM.pdf",
        "https://ak-static.cms.nba.com/referee/injury/Injury-Report_2019-01-10_04_30PM.pdf",
        "https://ak-static.cms.nba.com/referee/injury/Injury-Report_2019-01-10_04_15PM.pdf",
    ]

    # 7:30 PM ET cutoff -> newest-first within [18:45, 19:30], includes 07_00PM and 07PM at 19:00
    cands_730pm = build_candidate_pdf_urls(d, time(19, 30))
    assert cands_730pm == [
        "https://ak-static.cms.nba.com/referee/injury/Injury-Report_2019-01-10_07_30PM.pdf",
        "https://ak-static.cms.nba.com/referee/injury/Injury-Report_2019-01-10_07_15PM.pdf",
        "https://ak-static.cms.nba.com/referee/injury/Injury-Report_2019-01-10_07_00PM.pdf",
        "https://ak-static.cms.nba.com/referee/injury/Injury-Report_2019-01-10_07PM.pdf",
        "https://ak-static.cms.nba.com/referee/injury/Injury-Report_2019-01-10_06_45PM.pdf",
    ]

    # Every candidate timestamp must be <= cutoff_time_et
    cutoff_utc = datetime(2019, 1, 10, 19, 30, tzinfo=EASTERN_TZ).astimezone(timezone.utc)
    for url in cands_730pm:
        ts = parse_pdf_filename_timestamp(url)
        assert ts is not None
        assert ts <= cutoff_utc


def test_date_planning_from_game_tables_skips_non_game_days(db_session: Session):
    session = db_session
    season = Season(season_label="2024-25", is_active=True)
    session.add(season)
    session.flush()

    bos = Team(abbreviation="BOS", full_name="Boston Celtics", city="Boston", conference="East", division="Atlantic")
    nyk = Team(abbreviation="NYK", full_name="New York Knicks", city="New York", conference="East", division="Atlantic")
    session.add_all([bos, nyk])
    session.flush()

    player = Player(full_name="Test Starter")
    session.add(player)
    session.flush()

    # 1. Game date in player_game_log only (no tip time known -> defaults to 17:00 and 19:30 ET)
    pgl_reg = PlayerGameLog(
        player_id=player.id,
        team_id=bos.id,
        season_id=season.id,
        game_id="0022400001",  # regular season (type 2)
        game_date=date(2024, 10, 22),
        matchup="BOS vs. NYK",
        min=32,
    )
    # Preseason game on 2024-10-15 (type 1) -> must be excluded
    pgl_pre = PlayerGameLog(
        player_id=player.id,
        team_id=bos.id,
        season_id=season.id,
        game_id="0012400001",
        game_date=date(2024, 10, 15),
        matchup="BOS vs. NYK",
        min=20,
    )
    session.add_all([pgl_reg, pgl_pre])

    # 2. Scheduled game in Game table on 2024-10-24 tipping off at 8:00 PM ET (20:00 ET -> tip-60m = 19:00 ET)
    tip_2024_10_24_et = datetime(2024, 10, 24, 20, 0, tzinfo=EASTERN_TZ)
    g_active = Game(
        season_id=season.id,
        home_team_id=bos.id,
        away_team_id=nyk.id,
        commence_time=tip_2024_10_24_et.astimezone(timezone.utc),
        status="final",
    )
    # Postponed game on 2024-10-23 -> must be excluded
    g_postponed = Game(
        season_id=season.id,
        home_team_id=bos.id,
        away_team_id=nyk.id,
        commence_time=datetime(2024, 10, 23, 19, 30, tzinfo=EASTERN_TZ).astimezone(timezone.utc),
        status="postponed",
    )
    session.add_all([g_active, g_postponed])
    session.commit()

    dates_map = discover_game_dates(session, date(2024, 10, 14), date(2024, 10, 25))
    assert list(dates_map.keys()) == [date(2024, 10, 22), date(2024, 10, 24)]
    assert dates_map[date(2024, 10, 22)] is None
    assert dates_map[date(2024, 10, 24)] == tip_2024_10_24_et

    planned, game_dates_count, skipped = plan_backfill_slots(
        session, start_date=date(2024, 10, 14), end_date=date(2024, 10, 25), per_day=2
    )
    assert game_dates_count == 2
    assert skipped == 0
    assert len(planned) == 4

    # 2024-10-22 (no tip time known): 17:00 ET and 19:30 ET
    assert planned[0].game_date == date(2024, 10, 22)
    assert planned[0].cutoff_time_et == time(17, 0)
    assert planned[0].tipoff_known is False
    assert planned[1].game_date == date(2024, 10, 22)
    assert planned[1].cutoff_time_et == time(19, 30)
    assert planned[1].tipoff_known is False

    # 2024-10-24 (tip time 20:00 ET known): 17:00 ET and 19:00 ET (60m before tip-off)
    assert planned[2].game_date == date(2024, 10, 24)
    assert planned[2].cutoff_time_et == time(17, 0)
    assert planned[2].tipoff_known is True
    assert planned[3].game_date == date(2024, 10, 24)
    assert planned[3].cutoff_time_et == time(19, 0)
    assert planned[3].tipoff_known is True


def test_dry_run_makes_zero_network_calls(db_session: Session, capsys):
    session = db_session
    season = Season(season_label="2021-22", is_active=False)
    bos = Team(abbreviation="BOS", full_name="Boston Celtics", city="Boston", conference="East", division="Atlantic")
    player = Player(full_name="Dry Run Player")
    session.add_all([season, bos, player])
    session.flush()

    session.add(
        PlayerGameLog(
            player_id=player.id,
            team_id=bos.id,
            season_id=season.id,
            game_id="0022100010",
            game_date=date(2021, 11, 1),
            matchup="BOS vs. NYK",
            min=30,
        )
    )
    session.commit()

    def forbidden_handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"Network call made during --dry-run: {request.url}")

    fake_client = httpx.Client(transport=httpx.MockTransport(forbidden_handler))

    summary = run_backfill_injuries(
        start_date=date(2021, 11, 1),
        end_date=date(2021, 11, 1),
        per_day=2,
        dry_run=True,
        session=session,
        http_client=fake_client,
    )

    assert summary.dry_run is True
    assert summary.requested == 0
    assert summary.stored == 0
    assert summary.slots_planned == 2
    assert len(summary.planned_urls) == 2
    assert "Injury-Report_2021-11-01_05_00PM.pdf" in summary.planned_urls[0]
    assert "Injury-Report_2021-11-01_07_30PM.pdf" in summary.planned_urls[1]

    out = capsys.readouterr().out
    assert "[dry-run]" in out
    assert "Injury-Report_2021-11-01_05_00PM.pdf" in out


def test_backfill_hourly_fallback_resume_and_idempotency(db_session: Session):
    session = db_session
    season = Season(season_label="2018-19", is_active=False)
    por = Team(abbreviation="POR", full_name="Portland Trail Blazers", city="Portland", conference="West", division="NW")
    uta = Team(abbreviation="UTA", full_name="Utah Jazz", city="Salt Lake City", conference="West", division="NW")
    p1 = Player(full_name="Jordan Kent")
    p2 = Player(full_name="Ethan Baker Jr.")
    session.add_all([season, por, uta, p1, p2])
    session.flush()

    session.add_all(
        [
            PlayerSeasonStats(player_id=p1.id, team_id=por.id, season_id=season.id),
            PlayerSeasonStats(player_id=p2.id, team_id=por.id, season_id=season.id),
            PlayerGameLog(
                player_id=p1.id,
                team_id=por.id,
                season_id=season.id,
                game_id="0021800440",
                game_date=ARCHIVE_START_DATE,
                matchup="POR @ UTA",
                min=34,
            ),
        ]
    )
    session.commit()

    fixture_text = _load_fixture_text()
    requested_urls: List[str] = []
    seen_user_agents: List[str] = []

    # Simulate 2018-12-17 archive where 15-min URLs return 403 and hourly 05PM / 07PM return 200
    def handler(request: httpx.Request) -> httpx.Response:
        url_str = str(request.url)
        requested_urls.append(url_str)
        seen_user_agents.append(request.headers.get("User-Agent", ""))
        if url_str.endswith("_05PM.pdf"):
            return httpx.Response(200, content=b"%PDF-1.4 archive 5pm pdf")
        if url_str.endswith("_07PM.pdf"):
            return httpx.Response(200, content=b"%PDF-1.4 archive 7pm pdf")
        return httpx.Response(403, content=b"Forbidden")

    mock_client = httpx.Client(transport=httpx.MockTransport(handler))
    sleeps: List[float] = []

    fetch_now = datetime(2026, 11, 6, 12, 0, tzinfo=timezone.utc)
    summary1 = backfill_injury_reports(
        session=session,
        start_date=ARCHIVE_START_DATE,
        end_date=ARCHIVE_START_DATE,
        per_day=2,
        delay_seconds=4.0,
        max_requests=300,
        http_client=mock_client,
        pdf_text_extractor=lambda _: fixture_text,
        sleep_fn=sleeps.append,
        now=fetch_now,
    )

    # Slot 1 (17:00): tries 05_00PM (403) -> 05PM (200) [2 reqs]
    # Slot 2 (19:30): tries 07_30PM (403) -> 07_15PM (403) -> 07_00PM (403) -> 07PM (200) [4 reqs]
    assert summary1.requested == 6
    assert summary1.stored == 2
    assert summary1.missing == 4
    assert summary1.missing_slots == 0
    assert summary1.parse_failures == 0
    # 6 entries per fixture PDF; 2 resolved (Kent, Baker), 4 unresolved per snapshot -> 8 total
    assert summary1.unmatched_player_names == 8

    # Verify honest User-Agent from settings matches InjuryReportService
    assert all(ua == settings.INJURY_USER_AGENT for ua in seen_user_agents)
    assert settings.INJURY_USER_AGENT == InjuryReportService.USER_AGENT

    # Verify real report_timestamp (2018-12-17 17:00 EST = 22:00 UTC and 19:00 EST = 2018-12-18 00:00 UTC)
    snaps = session.exec(
        select(InjuryReportSnapshot).order_by(InjuryReportSnapshot.report_timestamp)
    ).all()
    assert len(snaps) == 2
    assert snaps[0].report_timestamp.replace(tzinfo=timezone.utc) == datetime(2018, 12, 17, 22, 0, tzinfo=timezone.utc)
    assert snaps[1].report_timestamp.replace(tzinfo=timezone.utc) == datetime(2018, 12, 18, 0, 0, tzinfo=timezone.utc)
    assert snaps[0].fetched_at.replace(tzinfo=timezone.utc) == fetch_now

    # Second run (resume): both slots are already stored in injury_report_snapshot -> 0 HTTP requests!
    requested_urls.clear()
    summary2 = backfill_injury_reports(
        session=session,
        start_date=ARCHIVE_START_DATE,
        end_date=ARCHIVE_START_DATE,
        per_day=2,
        http_client=mock_client,
        pdf_text_extractor=lambda _: fixture_text,
        sleep_fn=sleeps.append,
        now=fetch_now,
    )
    assert summary2.skipped_existing == 2
    assert summary2.slots_planned == 0
    assert summary2.requested == 0
    assert summary2.stored == 0
    assert len(requested_urls) == 0


def test_delay_minimum_and_max_requests_cap_enforcement(db_session: Session, caplog):
    session = db_session
    season = Season(season_label="2023-24", is_active=False)
    bos = Team(abbreviation="BOS", full_name="Boston Celtics", city="Boston", conference="East", division="Atlantic")
    player = Player(full_name="Clock Test Player")
    session.add_all([season, bos, player])
    session.flush()

    # Add 6 game dates -> 12 slots -> up to 60 candidate URLs if all 404
    for day in range(1, 7):
        session.add(
            PlayerGameLog(
                player_id=player.id,
                team_id=bos.id,
                season_id=season.id,
                game_id=f"002230000{day}",
                game_date=date(2024, 1, day),
                matchup="BOS vs. NYK",
                min=25,
            )
        )
    session.commit()

    mock_client = httpx.Client(
        transport=httpx.MockTransport(lambda req: httpx.Response(404, content=b"Not Found"))
    )
    fake_sleeps: List[float] = []

    with caplog.at_level("INFO"):
        summary = backfill_injury_reports(
            session=session,
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 6),
            per_day=2,
            delay_seconds=0.5,  # Below 2.0s minimum -> must be clamped to 2.0s
            max_requests=25,    # Hard cap at 25 requests (also triggers 25-request progress log)
            http_client=mock_client,
            sleep_fn=fake_sleeps.append,
        )

    assert summary.effective_delay_seconds == 2.0
    assert summary.requested == 25
    assert summary.cap_reached is True
    assert summary.missing == 25
    # Sleep is called between consecutive requests: 24 sleeps of 2.0s each
    assert len(fake_sleeps) == 24
    assert all(s == 2.0 for s in fake_sleeps)
    # Progress log line emitted at request 25
    assert any("Backfill progress: requested=25/25" in rec.message for rec in caplog.records)


def test_failure_handling_corrupt_pdf_http_error_and_ctrl_c(db_session: Session):
    session = db_session
    season = Season(season_label="2024-25", is_active=False)
    bos = Team(abbreviation="BOS", full_name="Boston Celtics", city="Boston", conference="East", division="Atlantic")
    player = Player(full_name="Failure Test Player")
    session.add_all([season, bos, player])
    session.flush()

    for day in (10, 11, 12):
        session.add(
            PlayerGameLog(
                player_id=player.id,
                team_id=bos.id,
                season_id=season.id,
                game_id=f"00224001{day}",
                game_date=date(2025, 1, day),
                matchup="BOS vs. NYK",
                min=28,
            )
        )
    session.commit()

    fixture_text = _load_fixture_text()

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        # Day 10: returns 200 with corrupt PDF bytes
        if "2025-01-10" in url:
            return httpx.Response(200, content=b"CORRUPT_BYTES")
        # Day 11: first candidate raises network timeout, second returns valid PDF
        if "2025-01-11_05_00PM" in url:
            raise httpx.ConnectTimeout("simulated timeout")
        if "2025-01-11_05PM" in url:
            return httpx.Response(200, content=b"%PDF-1.4 valid day 11 pdf")
        # Day 12: simulate Ctrl-C on request
        if "2025-01-12" in url:
            raise KeyboardInterrupt()
        return httpx.Response(404)

    def extractor(pdf_bytes: bytes) -> str:
        if pdf_bytes == b"CORRUPT_BYTES":
            raise ValueError("corrupt PDF stream")
        return fixture_text

    mock_client = httpx.Client(transport=httpx.MockTransport(handler))
    summary = backfill_injury_reports(
        session=session,
        start_date=date(2025, 1, 10),
        end_date=date(2025, 1, 12),
        per_day=1,
        delay_seconds=2.0,
        http_client=mock_client,
        pdf_text_extractor=extractor,
        sleep_fn=lambda _: None,
    )

    assert summary.parse_failures == 1
    assert summary.http_errors == 1
    assert summary.stored == 1
    assert summary.interrupted is True

    # Day 11 snapshot remains safely committed despite Day 10 parse failure and Day 12 Ctrl-C
    snaps = session.exec(select(InjuryReportSnapshot)).all()
    assert len(snaps) == 1
    assert "2025-01-11_05PM.pdf" in snaps[0].report_url


def test_cli_parser_defaults():
    parser = build_parser()
    args = parser.parse_args([])
    assert args.start == date(2018, 12, 17)
    assert args.end is None
    assert args.per_day == 2
    assert args.delay == 4.0
    assert args.max_requests == 300
    assert args.dry_run is False
