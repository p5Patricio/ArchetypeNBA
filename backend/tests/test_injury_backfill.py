from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Dict, List
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
from app.services.injury_report_parser import InjuryReportLayoutError
from app.services.injury_report_service import (
    ARCHIVE_START_DATE,
    DEFAULT_BACKFILL_DELAY_SECONDS,
    EASTERN_TZ,
    QUARTER_HOUR_NAMING_START,
    InjuryReportService,
    backfill_injury_reports,
    build_candidate_pdf_urls,
    build_injury_pdf_url,
    discover_game_dates,
    index_page_season,
    injury_entry_tipoff_utc,
    is_hourly_pdf_url,
    latest_snapshot_before_tipoff,
    naming_is_hourly,
    parse_injury_index_links,
    parse_pdf_filename_timestamp,
    plan_backfill_slots,
    report_publication_time_from_url,
    season_label_for_date,
    select_listed_pdf_url,
    snapshot_is_pre_tip,
)
from scripts.backfill_injuries import build_parser, run_backfill_injuries

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
LAYOUT_FIXTURES_DIR = FIXTURES_DIR / "injury_layouts"


def _load_fixture_text() -> str:
    return (FIXTURES_DIR / "synthetic_injury_report_layout.txt").read_text(encoding="utf-8")


def _load_layout_fixture(name: str) -> str:
    return (LAYOUT_FIXTURES_DIR / name).read_text(encoding="utf-8")


def _load_index_html() -> str:
    return (FIXTURES_DIR / "injury_index_page.html").read_text(encoding="utf-8")


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


def test_parse_pdf_filename_timestamp_and_publication_time():
    url_hourly = "https://ak-static.cms.nba.com/referee/injury/Injury-Report_2018-12-17_05PM.pdf"
    url_15m = "https://ak-static.cms.nba.com/referee/injury/Injury-Report_2025-12-22_05_00PM.pdf"

    assert is_hourly_pdf_url(url_hourly) is True
    assert is_hourly_pdf_url(url_15m) is False

    # Label time vs publication time (hourly _05PM is published at 5:30 PM ET = 22:30 UTC)
    assert parse_pdf_filename_timestamp(url_hourly) == datetime(2018, 12, 17, 22, 0, tzinfo=timezone.utc)
    assert report_publication_time_from_url(url_hourly) == datetime(2018, 12, 17, 22, 30, tzinfo=timezone.utc)

    # Quarter-hour _05_00PM has publication time equal to label time (22:00 UTC)
    assert parse_pdf_filename_timestamp(url_15m) == datetime(2025, 12, 22, 22, 0, tzinfo=timezone.utc)
    assert report_publication_time_from_url(url_15m) == datetime(2025, 12, 22, 22, 0, tzinfo=timezone.utc)

    # Naming era boundary
    assert QUARTER_HOUR_NAMING_START == date(2025, 12, 22)
    assert naming_is_hourly(date(2019, 1, 10)) is True
    assert naming_is_hourly(date(2025, 12, 21)) is True
    assert naming_is_hourly(date(2025, 12, 22)) is False
    assert naming_is_hourly(date(2026, 1, 10)) is False

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
    assert report_publication_time_from_url("https://example.com/other.pdf") is None
    assert (
        parse_pdf_filename_timestamp(
            "https://ak-static.cms.nba.com/referee/injury/Injury-Report_2025-01-15_13_00PM.pdf"
        )
        is None
    )


def test_build_candidate_pdf_urls_newest_first_and_leak_free():
    d_hourly = date(2019, 1, 10)
    cands_5pm = build_candidate_pdf_urls(d_hourly, time(17, 0))
    assert cands_5pm == [
        "https://ak-static.cms.nba.com/referee/injury/Injury-Report_2019-01-10_05PM.pdf",
        "https://ak-static.cms.nba.com/referee/injury/Injury-Report_2019-01-10_04PM.pdf",
        "https://ak-static.cms.nba.com/referee/injury/Injury-Report_2019-01-10_03PM.pdf",
    ]

    cands_730pm_pub = build_candidate_pdf_urls(d_hourly, time(19, 30), by_publication=True)
    assert cands_730pm_pub == [
        "https://ak-static.cms.nba.com/referee/injury/Injury-Report_2019-01-10_07PM.pdf",
        "https://ak-static.cms.nba.com/referee/injury/Injury-Report_2019-01-10_06PM.pdf",
        "https://ak-static.cms.nba.com/referee/injury/Injury-Report_2019-01-10_05PM.pdf",
    ]
    cutoff_utc = datetime(2019, 1, 10, 19, 30, tzinfo=EASTERN_TZ).astimezone(timezone.utc)
    for url in cands_730pm_pub:
        pub_ts = report_publication_time_from_url(url)
        assert pub_ts is not None
        assert pub_ts <= cutoff_utc

    d_15m = date(2026, 1, 10)
    assert build_candidate_pdf_urls(d_15m, time(17, 0)) == [
        "https://ak-static.cms.nba.com/referee/injury/Injury-Report_2026-01-10_05_00PM.pdf",
        "https://ak-static.cms.nba.com/referee/injury/Injury-Report_2026-01-10_04_45PM.pdf",
        "https://ak-static.cms.nba.com/referee/injury/Injury-Report_2026-01-10_04_30PM.pdf",
    ]

    # Near the naming switch: 3 hourly names + newest quarter-hour name appended last
    d_switch = date(2025, 12, 21)
    assert build_candidate_pdf_urls(d_switch, time(17, 0)) == [
        "https://ak-static.cms.nba.com/referee/injury/Injury-Report_2025-12-21_05PM.pdf",
        "https://ak-static.cms.nba.com/referee/injury/Injury-Report_2025-12-21_04PM.pdf",
        "https://ak-static.cms.nba.com/referee/injury/Injury-Report_2025-12-21_03PM.pdf",
        "https://ak-static.cms.nba.com/referee/injury/Injury-Report_2025-12-21_05_00PM.pdf",
    ]


def test_season_label_for_date():
    assert season_label_for_date(date(2019, 1, 15)) == "2018-19"
    assert season_label_for_date(date(2019, 10, 25)) == "2019-20"
    assert season_label_for_date(date(2020, 8, 10)) == "2019-20"
    assert season_label_for_date(date(2020, 12, 23)) == "2020-21"
    assert season_label_for_date(date(2021, 7, 20)) == "2020-21"


def test_parse_injury_index_links_and_select_listed_pdf_url():
    html = _load_index_html()
    assert index_page_season(html) == "2026-27"

    by_date = parse_injury_index_links(html)
    target_date = date(2026, 11, 6)
    assert list(by_date.keys()) == [target_date]

    links = by_date[target_date]
    assert len(links) == 8
    pub_times = [report_publication_time_from_url(u) for u in links]
    assert all(t is not None for t in pub_times)
    assert pub_times == sorted(pub_times)  # type: ignore[type-var]
    assert "https://official.nba.com/referee/injury/Injury-Report_2026-11-06_06_15PM.pdf" in links
    assert all("Playing-Rules" not in u for u in links)

    assert (
        select_listed_pdf_url(links, target_date, time(17, 0))
        == "https://ak-static.cms.nba.com/referee/injury/Injury-Report_2026-11-06_05_00PM.pdf"
    )
    assert (
        select_listed_pdf_url(links, target_date, time(18, 10), by_publication=True)
        == "https://ak-static.cms.nba.com/referee/injury/Injury-Report_2026-11-06_06_00PM.pdf"
    )
    assert (
        select_listed_pdf_url(links, target_date, time(0, 0), by_publication=True)
        == "https://ak-static.cms.nba.com/referee/injury/Injury-Report_2026-11-06_12_00AM.pdf"
    )
    assert select_listed_pdf_url(links, date(2026, 11, 5), time(23, 59), by_publication=True) is None
    assert select_listed_pdf_url([], target_date, time(17, 0), by_publication=True) is None


def test_store_pdf_bytes_title_timestamp_and_unknown_layout(db_session: Session):
    text_2019 = _load_layout_fixture("category_columns_2019-01-15.txt")
    service = InjuryReportService(db_session, pdf_text_extractor=lambda _: text_2019)

    url = "https://ak-static.cms.nba.com/referee/injury/Injury-Report_2019-01-15_05PM.pdf"
    snap, created, _ = service.store_pdf_bytes(url, b"%PDF-1.4-2019-01-15")
    assert created is True
    assert snap.report_timestamp.replace(tzinfo=timezone.utc) == datetime(
        2019, 1, 15, 22, 30, tzinfo=timezone.utc
    )

    entries = db_session.exec(select(InjuryEntry).where(InjuryEntry.snapshot_id == snap.id)).all()
    assert len(entries) == 10
    assert entries[0].game_time_et == "07:00 (ET)"

    bad_text = (
        "Game Date Game Time Matchup Team Player Name Status Notes\n"
        "01/15/2019 07:00 (ET) MIN@PHI Minnesota Timberwolves Covington, Robert Out Knee\n"
    )
    bad_service = InjuryReportService(db_session, pdf_text_extractor=lambda _: bad_text)
    with pytest.raises(InjuryReportLayoutError):
        bad_service.store_pdf_bytes(
            "https://ak-static.cms.nba.com/referee/injury/Injury-Report_2019-01-16_05PM.pdf",
            b"%PDF-1.4-unknown-layout",
        )
    db_session.rollback()
    all_snaps = db_session.exec(select(InjuryReportSnapshot)).all()
    assert len(all_snaps) == 1


def test_season_scoped_player_resolution_and_clippers_alias(db_session: Session):
    s_1819 = Season(season_label="2018-19", is_active=False)
    s_2324 = Season(season_label="2023-24", is_active=False)
    t_min = Team(
        abbreviation="MIN",
        full_name="Minnesota Timberwolves",
        city="Minneapolis",
        conference="West",
        division="NW",
    )
    t_phi = Team(
        abbreviation="PHI",
        full_name="Philadelphia 76ers",
        city="Philadelphia",
        conference="East",
        division="Atlantic",
    )
    t_lac = Team(
        abbreviation="LAC",
        full_name="LA Clippers",
        city="Los Angeles",
        conference="West",
        division="Pacific",
    )
    p_a = Player(full_name="Jaylen Smith")
    p_b = Player(full_name="Jaylen Smith")
    db_session.add_all([s_1819, s_2324, t_min, t_phi, t_lac, p_a, p_b])
    db_session.flush()

    db_session.add_all(
        [
            PlayerGameLog(
                player_id=p_a.id,
                team_id=t_phi.id,
                season_id=s_1819.id,
                game_id="0021800600",
                game_date=date(2019, 1, 10),
                matchup="PHI vs. MIN",
                min=20,
            ),
            PlayerGameLog(
                player_id=p_b.id,
                team_id=t_phi.id,
                season_id=s_2324.id,
                game_id="0022300600",
                game_date=date(2024, 1, 10),
                matchup="PHI vs. MIN",
                min=22,
            ),
        ]
    )
    db_session.commit()

    service = InjuryReportService(db_session)
    assert (
        service.resolve_player_id("Jaylen Smith", team_name="Philadelphia 76ers", game_date="01/15/2019")
        == p_a.id
    )
    assert (
        service.resolve_player_id("Jaylen Smith", team_name="Philadelphia 76ers", game_date="01/15/2024")
        == p_b.id
    )
    assert service.resolve_player_id("Jaylen Smith", team_name="Philadelphia 76ers") is None
    assert service._get_team_id("Los Angeles Clippers") == t_lac.id


def test_leakage_helpers_and_matinee_selection(db_session: Session):
    now_utc = datetime(2022, 1, 17, 23, 0, tzinfo=timezone.utc)
    s_old = InjuryReportSnapshot(
        report_url="https://example.com/old.pdf",
        report_timestamp=datetime(2022, 1, 15, 17, 30, tzinfo=EASTERN_TZ).astimezone(timezone.utc),
        fetched_at=now_utc,
        sha256="a" * 64,
        entries_count=1,
    )
    s_1130 = InjuryReportSnapshot(
        report_url="https://example.com/1130.pdf",
        report_timestamp=datetime(2022, 1, 17, 11, 30, tzinfo=EASTERN_TZ).astimezone(timezone.utc),
        fetched_at=now_utc,
        sha256="b" * 64,
        entries_count=1,
    )
    s_1730 = InjuryReportSnapshot(
        report_url="https://example.com/1730.pdf",
        report_timestamp=datetime(2022, 1, 17, 17, 30, tzinfo=EASTERN_TZ).astimezone(timezone.utc),
        fetched_at=now_utc,
        sha256="c" * 64,
        entries_count=1,
    )
    db_session.add_all([s_old, s_1130, s_1730])
    db_session.commit()

    # Matinee tip at 13:00 ET selects 11:30 ET report, not 17:30 ET
    tip_1300_et = datetime(2022, 1, 17, 13, 0, tzinfo=EASTERN_TZ)
    chosen = latest_snapshot_before_tipoff(db_session, tip_1300_et)
    assert chosen is not None and chosen.id == s_1130.id

    # Snapshot exactly at tipoff is excluded (strictly before tipoff)
    s_exact = InjuryReportSnapshot(
        report_url="https://example.com/1300.pdf",
        report_timestamp=tip_1300_et.astimezone(timezone.utc),
        fetched_at=now_utc,
        sha256="d" * 64,
        entries_count=1,
    )
    db_session.add(s_exact)
    db_session.commit()

    chosen_after_exact = latest_snapshot_before_tipoff(db_session, tip_1300_et)
    assert chosen_after_exact is not None and chosen_after_exact.id == s_1130.id
    assert snapshot_is_pre_tip(s_1130.report_timestamp, tip_1300_et) is True
    assert snapshot_is_pre_tip(s_exact.report_timestamp, tip_1300_et) is False
    assert snapshot_is_pre_tip(s_1730.report_timestamp, tip_1300_et) is False

    # max_age=36h excludes older snapshot
    tip_morning = datetime(2022, 1, 17, 10, 0, tzinfo=EASTERN_TZ)
    assert latest_snapshot_before_tipoff(db_session, tip_morning) == s_old
    assert latest_snapshot_before_tipoff(db_session, tip_morning, max_age=timedelta(hours=36)) is None

    entry = InjuryEntry(
        snapshot_id=s_1130.id,  # type: ignore[arg-type]
        game_date="01/17/2022",
        game_time_et="01:00 (ET)",
        player_name_raw="Covington, Robert",
        status="Out",
    )
    assert injury_entry_tipoff_utc(entry) == datetime(2022, 1, 17, 18, 0, tzinfo=timezone.utc)


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

    summary_with_index = run_backfill_injuries(
        start_date=date(2021, 11, 1),
        end_date=date(2021, 11, 1),
        per_day=2,
        dry_run=True,
        use_index_pages=True,
        session=session,
        http_client=fake_client,
    )

    assert summary_with_index.dry_run is True
    assert summary_with_index.requested == 0
    assert summary_with_index.stored == 0
    assert summary_with_index.slots_planned == 2
    assert summary_with_index.estimated_requests == summary_with_index.slots_planned + 1
    assert len(summary_with_index.planned_urls) == 2
    assert "Injury-Report_2021-11-01_05PM.pdf" in summary_with_index.planned_urls[0]
    assert "Injury-Report_2021-11-01_07PM.pdf" in summary_with_index.planned_urls[1]

    out = capsys.readouterr().out
    assert "[dry-run]" in out
    assert "Injury-Report_2021-11-01_05PM.pdf" in out

    summary_no_index = backfill_injury_reports(
        session=session,
        start_date=date(2021, 11, 1),
        end_date=date(2021, 11, 1),
        per_day=2,
        dry_run=True,
        use_index_pages=False,
        http_client=fake_client,
    )
    assert summary_no_index.requested == 0
    assert summary_no_index.estimated_requests == summary_no_index.slots_planned


def test_backfill_hourly_fallback_resume_and_idempotency(db_session: Session):
    session = db_session
    season = Season(season_label="2018-19", is_active=False)
    min_team = Team(
        abbreviation="MIN",
        full_name="Minnesota Timberwolves",
        city="Minneapolis",
        conference="West",
        division="NW",
    )
    phi_team = Team(
        abbreviation="PHI",
        full_name="Philadelphia 76ers",
        city="Philadelphia",
        conference="East",
        division="Atlantic",
    )
    covington = Player(full_name="Robert Covington")
    session.add_all([season, min_team, phi_team, covington])
    session.flush()

    target_date = date(2019, 1, 15)
    session.add(
        PlayerGameLog(
            player_id=covington.id,
            team_id=min_team.id,
            season_id=season.id,
            game_id="0021800640",
            game_date=target_date,
            matchup="MIN @ PHI",
            min=34,
        )
    )
    session.commit()

    fixture_text = _load_layout_fixture("category_columns_2019-01-15.txt")
    requested_urls: List[str] = []
    seen_user_agents: List[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url_str = str(request.url)
        requested_urls.append(url_str)
        seen_user_agents.append(request.headers.get("User-Agent", ""))
        if url_str.endswith("_2019-01-15_05PM.pdf"):
            return httpx.Response(200, content=b"%PDF-1.4 archive 2019-01-15 5pm pdf")
        return httpx.Response(403, content=b"Forbidden")

    mock_client = httpx.Client(transport=httpx.MockTransport(handler))
    sleeps: List[float] = []
    fetch_now = datetime(2026, 11, 6, 12, 0, tzinfo=timezone.utc)

    summary1 = backfill_injury_reports(
        session=session,
        start_date=target_date,
        end_date=target_date,
        per_day=2,
        use_index_pages=False,
        http_client=mock_client,
        pdf_text_extractor=lambda _: fixture_text,
        sleep_fn=sleeps.append,
        now=fetch_now,
    )

    assert summary1.requested == 1
    assert summary1.stored == 1
    assert summary1.reused_slots == 1
    assert summary1.missing_slots == 0
    assert summary1.parse_failures == 0
    assert all(ua == settings.INJURY_USER_AGENT for ua in seen_user_agents)
    assert settings.INJURY_USER_AGENT == InjuryReportService.USER_AGENT

    snaps = session.exec(select(InjuryReportSnapshot)).all()
    assert len(snaps) == 1
    assert snaps[0].report_timestamp.replace(tzinfo=timezone.utc) == datetime(
        2019, 1, 15, 22, 30, tzinfo=timezone.utc
    )
    assert snaps[0].fetched_at.replace(tzinfo=timezone.utc) == fetch_now

    # Second run: 0 requests
    requested_urls.clear()
    summary2 = backfill_injury_reports(
        session=session,
        start_date=target_date,
        end_date=target_date,
        per_day=2,
        use_index_pages=False,
        http_client=mock_client,
        pdf_text_extractor=lambda _: fixture_text,
        sleep_fn=sleeps.append,
        now=fetch_now,
    )
    assert summary2.requested == 0
    assert summary2.slots_planned == 0
    assert summary2.skipped_existing >= 1
    assert len(requested_urls) == 0


def test_backfill_uses_index_pages_when_available(db_session: Session):
    session = db_session
    season = Season(season_label="2026-27", is_active=True)
    mem = Team(abbreviation="MEM", full_name="Memphis Grizzlies", city="Memphis", conference="West", division="SW")
    orl = Team(abbreviation="ORL", full_name="Orlando Magic", city="Orlando", conference="East", division="SE")
    clarke = Player(full_name="Brandon Clarke")
    session.add_all([season, mem, orl, clarke])
    session.flush()

    target_date = date(2026, 11, 6)
    session.add(
        PlayerGameLog(
            player_id=clarke.id,
            team_id=mem.id,
            season_id=season.id,
            game_id="0022600100",
            game_date=target_date,
            matchup="MEM @ ORL",
            min=24,
        )
    )
    session.commit()

    index_html = _load_index_html()
    base_2026_text = (
        _load_layout_fixture("status_reason_inverted_2026-01-15.txt")
        .replace("01/15/2026", "11/06/2026")
        .replace("01/15/26", "11/06/26")
        .replace("02:00  (ET)", "07:00  (ET)")
    )
    text_by_bytes: Dict[bytes, str] = {
        b"%PDF-2026-11-06-0500": base_2026_text,
        b"%PDF-2026-11-06-0600": base_2026_text.replace("05:00            PM", "06:00            PM"),
    }

    requested_urls: List[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        requested_urls.append(url)
        if "official.nba.com/nba-injury-report-" in url:
            return httpx.Response(200, text=index_html)
        if url.endswith("_2026-11-06_05_00PM.pdf"):
            return httpx.Response(200, content=b"%PDF-2026-11-06-0500")
        if url.endswith("_2026-11-06_06_00PM.pdf"):
            return httpx.Response(200, content=b"%PDF-2026-11-06-0600")
        return httpx.Response(404, content=b"Not Found")

    mock_client = httpx.Client(transport=httpx.MockTransport(handler))
    summary = backfill_injury_reports(
        session=session,
        start_date=target_date,
        end_date=target_date,
        per_day=2,
        use_index_pages=True,
        http_client=mock_client,
        pdf_text_extractor=lambda b: text_by_bytes[b],
        sleep_fn=lambda _: None,
        now=datetime(2026, 11, 6, 23, 0, tzinfo=timezone.utc),
    )

    assert summary.requested == 3
    assert summary.index_pages_requested == 1
    assert summary.stored == 2
    assert all(not u.endswith("_05PM.pdf") for u in requested_urls)


def test_backfill_index_page_redirect_falls_back_to_hourly_guesses(db_session: Session):
    session = db_session
    season = Season(season_label="2018-19", is_active=False)
    min_team = Team(
        abbreviation="MIN",
        full_name="Minnesota Timberwolves",
        city="Minneapolis",
        conference="West",
        division="NW",
    )
    covington = Player(full_name="Robert Covington")
    session.add_all([season, min_team, covington])
    session.flush()

    target_date = date(2019, 1, 15)
    session.add(
        PlayerGameLog(
            player_id=covington.id,
            team_id=min_team.id,
            season_id=season.id,
            game_id="0021800640",
            game_date=target_date,
            matchup="MIN @ PHI",
            min=34,
        )
    )
    session.commit()

    index_html_2026 = _load_index_html()
    text_2019 = _load_layout_fixture("category_columns_2019-01-15.txt")
    requested_urls: List[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        requested_urls.append(url)
        if "official.nba.com/nba-injury-report-" in url:
            return httpx.Response(200, text=index_html_2026)
        if url.endswith("_2019-01-15_05PM.pdf"):
            return httpx.Response(200, content=b"%PDF-2019-01-15-05PM")
        return httpx.Response(403, content=b"Forbidden")

    mock_client = httpx.Client(transport=httpx.MockTransport(handler))
    summary = backfill_injury_reports(
        session=session,
        start_date=target_date,
        end_date=target_date,
        per_day=2,
        use_index_pages=True,
        http_client=mock_client,
        pdf_text_extractor=lambda _: text_2019,
        sleep_fn=lambda _: None,
        now=datetime(2026, 11, 6, 23, 0, tzinfo=timezone.utc),
    )

    assert summary.index_pages_requested == 1
    assert summary.index_seasons_unavailable == ["2018-19"]
    assert summary.stored == 1
    assert any(u.endswith("_2019-01-15_05PM.pdf") for u in requested_urls)


def test_delay_minimum_and_max_requests_cap_enforcement(db_session: Session, caplog):
    session = db_session
    season = Season(season_label="2023-24", is_active=False)
    bos = Team(abbreviation="BOS", full_name="Boston Celtics", city="Boston", conference="East", division="Atlantic")
    player = Player(full_name="Clock Test Player")
    session.add_all([season, bos, player])
    session.flush()

    # Add 5 game dates -> 10 slots -> 30 candidate URLs + 1 index page if all 404
    for day in range(1, 6):
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

    assert DEFAULT_BACKFILL_DELAY_SECONDS == 4.0

    mock_client = httpx.Client(
        transport=httpx.MockTransport(lambda req: httpx.Response(404, content=b"Not Found"))
    )
    fake_sleeps: List[float] = []

    with caplog.at_level("INFO"):
        summary = backfill_injury_reports(
            session=session,
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 5),
            per_day=2,
            delay_seconds=0.5,  # Below 2.0s minimum -> clamped to 2.0s
            max_requests=25,    # Hard cap at 25 requests (1 index page + 24 PDF requests)
            use_index_pages=True,
            http_client=mock_client,
            sleep_fn=fake_sleeps.append,
        )

    assert summary.effective_delay_seconds == 2.0
    assert summary.index_pages_requested == 1
    assert summary.requested == 25
    assert summary.cap_reached is True
    assert summary.missing == 24
    # Sleep is called between consecutive requests only: 24 sleeps of 2.0s each
    assert len(fake_sleeps) == 24
    assert all(s == 2.0 for s in fake_sleeps)
    assert any("Backfill progress: requested=25/25" in rec.message for rec in caplog.records)


def test_failure_handling_corrupt_pdf_unknown_layout_http_error_and_ctrl_c(db_session: Session):
    session = db_session
    season = Season(season_label="2024-25", is_active=False)
    bos = Team(abbreviation="BOS", full_name="Boston Celtics", city="Boston", conference="East", division="Atlantic")
    player = Player(full_name="Failure Test Player")
    session.add_all([season, bos, player])
    session.flush()

    for day in (10, 11, 12, 13):
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
        # Day 10: returns 200 with corrupt PDF bytes (extractor raises)
        if "2025-01-10" in url:
            return httpx.Response(200, content=b"CORRUPT_BYTES")
        # Day 11: returns 200 with unknown layout text (store_pdf_bytes raises InjuryReportLayoutError)
        if "2025-01-11" in url:
            return httpx.Response(200, content=b"UNKNOWN_LAYOUT_BYTES")
        # Day 12: first candidate (05PM) times out, second candidate (04PM) returns valid PDF
        if "2025-01-12_05PM" in url:
            raise httpx.ConnectTimeout("simulated timeout")
        if "2025-01-12_04PM" in url:
            return httpx.Response(200, content=b"%PDF-1.4 valid day 12 pdf")
        # Day 13: simulate Ctrl-C on request
        if "2025-01-13" in url:
            raise KeyboardInterrupt()
        return httpx.Response(404)

    def extractor(pdf_bytes: bytes) -> str:
        if pdf_bytes == b"CORRUPT_BYTES":
            raise ValueError("corrupt PDF stream")
        if pdf_bytes == b"UNKNOWN_LAYOUT_BYTES":
            return (
                "Game Date Game Time Matchup Team Player Name Status Notes\n"
                "01/11/2025 07:00 (ET) BOS@NYK Boston Celtics Doe, John Out Knee\n"
            )
        return fixture_text

    mock_client = httpx.Client(transport=httpx.MockTransport(handler))
    summary = backfill_injury_reports(
        session=session,
        start_date=date(2025, 1, 10),
        end_date=date(2025, 1, 13),
        per_day=1,
        delay_seconds=2.0,
        use_index_pages=False,
        http_client=mock_client,
        pdf_text_extractor=extractor,
        sleep_fn=lambda _: None,
    )

    assert summary.parse_failures == 2
    assert summary.http_errors == 1
    assert summary.stored == 1
    assert summary.interrupted is True

    # Only Day 12 snapshot is stored
    snaps = session.exec(select(InjuryReportSnapshot)).all()
    assert len(snaps) == 1
    assert "2025-01-12_04PM.pdf" in snaps[0].report_url


def test_cli_parser_defaults():
    parser = build_parser()
    args = parser.parse_args([])
    assert args.start == date(2018, 12, 17)
    assert args.end is None
    assert args.per_day == 2
    assert args.delay == 4.0
    assert args.max_requests == 300
    assert args.dry_run is False
    assert args.no_index_pages is False
