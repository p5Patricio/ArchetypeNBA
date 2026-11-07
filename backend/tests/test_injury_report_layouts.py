from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from app.services.injury_report_parser import (
    EASTERN_TZ,
    InjuryReportLayout,
    InjuryReportLayoutError,
    ParsedGame,
    canonical_team_name,
    parse_game_tipoff_et,
    parse_injury_report,
    parse_injury_report_text,
    parse_report_title_time,
)

LAYOUT_FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "injury_layouts"


def _read_layout_fixture(filename: str) -> str:
    return (LAYOUT_FIXTURES_DIR / filename).read_text(encoding="utf-8")


def test_category_columns_2019_01_15():
    text = _read_layout_fixture("category_columns_2019-01-15.txt")
    report = parse_injury_report(text)

    assert report.layout == InjuryReportLayout.CATEGORY_COLUMNS
    assert report.report_time_et == datetime(2019, 1, 15, 17, 30, tzinfo=ZoneInfo("America/New_York"))
    assert len(report.rows) == 10

    row0 = report.rows[0]
    assert row0.player_name == "Robert Covington"
    assert row0.raw_name == "Covington, Robert"
    assert row0.team == "Minnesota Timberwolves"
    assert row0.status == "Out"
    assert row0.reason == "Injury/Illness - Right Knee Bone Bruise"
    assert row0.game_time == "07:00 (ET)"
    assert row0.matchup == "MIN@PHI"
    assert row0.game_date == "01/15/2019"

    by_name = {r.player_name: r for r in report.rows}

    rose = by_name["Derrick Rose"]
    assert rose.status == "Questionable"
    assert rose.team == "Minnesota Timberwolves"

    terrell = by_name["Jared Terrell"]
    assert terrell.reason == "G League Team"

    fultz = by_name["Markelle Fultz"]
    assert fultz.team == "Philadelphia 76ers"

    anigbogu = by_name["Ike Anigbogu"]
    assert anigbogu.matchup == "PHX@IND"
    assert anigbogu.game_time == "07:00 (ET)"

    for name in ("Yante Maten", "Josh Richardson"):
        r = by_name[name]
        assert r.team == "Miami Heat"
        assert r.matchup == "MIA@MIL"
        assert r.game_time == "08:00 (ET)"

    giannis = by_name["Giannis Antetokounmpo"]
    assert giannis.team == "Milwaukee Bucks"
    assert giannis.status == "Probable"
    assert giannis.reason.endswith("Left hip contusion")

    for r in report.rows:
        assert "Injury" not in r.raw_name
        assert "League" not in r.raw_name


def test_category_columns_2019_05_15():
    text = _read_layout_fixture("category_columns_2019-05-15.txt")
    report = parse_injury_report(text)

    assert report.layout == InjuryReportLayout.CATEGORY_COLUMNS
    assert len(report.rows) == 7
    assert ParsedGame("05/16/2019", "09:00 (ET)", "POR@GSW") in report.games
    assert all(r.matchup != "POR@GSW" for r in report.rows)

    by_name = {r.player_name: r for r in report.rows}
    assert by_name["Jordan Loyd"].reason == "Coach's Decision"
    boucher = by_name["Chris Boucher"]
    assert boucher.status == "Available"
    assert boucher.availability_prob == 1.0


def test_status_reason_upright_2020_08_10():
    text = _read_layout_fixture("status_reason_upright_2020-08-10.txt")
    report = parse_injury_report(text)

    assert report.layout == InjuryReportLayout.STATUS_REASON_UPRIGHT
    assert len(report.rows) == 9

    by_name = {r.player_name: r for r in report.rows}
    for name in ("Goran Dragic", "Kendrick Nunn", "KZ Okpala"):
        r = by_name[name]
        assert r.team == "Miami Heat"
        assert r.matchup == "IND@MIA"
        assert r.game_time == "08:00 (ET)"

    assert by_name["Steven Adams"].game_time == "02:30 (ET)"
    assert by_name["Kendrick Nunn"].reason == "Not With Team - Self Isolating"


def test_status_reason_inverted_2023_05_17():
    text = _read_layout_fixture("status_reason_inverted_2023-05-17.txt")
    report = parse_injury_report(text)

    assert report.layout == InjuryReportLayout.STATUS_REASON_INVERTED
    assert len(report.rows) == 6
    assert [r.player_name for r in report.rows] == [
        "Bam Adebayo",
        "Tyler Herro",
        "Victor Oladipo",
        "Cody Zeller",
        "Jaylen Brown",
        "Danilo Gallinari",
    ]
    assert [r.team for r in report.rows[:4]] == ["Miami Heat"] * 4
    assert [r.team for r in report.rows[4:]] == ["Boston Celtics"] * 2

    adebayo = report.rows[0]
    assert adebayo.reason == "Injury/Illness- Right Shoulder; Discomfort"

    brown = report.rows[4]
    assert brown.reason.startswith("Injury/Illness")
    assert brown.reason.endswith("Face Mask")

    assert all(r.team != "Los Angeles Lakers" for r in report.rows)
    assert any(g.matchup == "LAL@DEN" and g.game_date == "05/18/2023" for g in report.games)


def test_status_reason_inverted_2026_01_15():
    text = _read_layout_fixture("status_reason_inverted_2026-01-15.txt")
    report = parse_injury_report(text)

    assert report.layout == InjuryReportLayout.STATUS_REASON_INVERTED
    assert report.report_time_et == datetime(2026, 1, 15, 17, 0, tzinfo=EASTERN_TZ)

    row0 = report.rows[0]
    assert row0.player_name == "Brandon Clarke"
    assert row0.team == "Memphis Grizzlies"
    assert row0.matchup == "MEM@ORL"
    assert row0.game_time == "02:00 (ET)"

    by_name = {r.player_name: r for r in report.rows}
    assert "Scotty Pippen Jr." in by_name
    assert "Surgery Recovery" in by_name["Scotty Pippen Jr."].reason
    assert by_name["Zach Edey"].reason == "Injury/Illness -Left Ankle; Stress Reaction"
    assert by_name["Colin Castleton"].team == "Orlando Magic"


def test_unknown_layouts_raise_and_never_guess():
    unknown_header_text = (
        "Game Date Game Time Matchup Team Player Name Status Notes\n"
        "01/15/2026 07:00 (ET) BOS@NYK Boston Celtics Doe, John Out Knee Soreness\n"
    )
    with pytest.raises(InjuryReportLayoutError):
        parse_injury_report(unknown_header_text)
    with pytest.raises(InjuryReportLayoutError):
        parse_injury_report_text(unknown_header_text)

    no_header_with_rows = (
        "01/15/2026 07:00 (ET) BOS@NYK Boston Celtics Doe, John Out Injury/Illness - Knee\n"
    )
    with pytest.raises(InjuryReportLayoutError):
        parse_injury_report(no_header_text := no_header_with_rows)
    with pytest.raises(InjuryReportLayoutError):
        parse_injury_report_text(no_header_text)

    assert parse_injury_report_text("") == []


def test_parse_game_tipoff_et():
    ny = ZoneInfo("America/New_York")
    assert parse_game_tipoff_et("01/15/2019", "07:00 (ET)") == datetime(2019, 1, 15, 19, 0, tzinfo=ny)
    assert parse_game_tipoff_et("01/17/2022", "01:00  (ET)") == datetime(2022, 1, 17, 13, 0, tzinfo=ny)
    assert parse_game_tipoff_et("12/25/2024", "12:00 (ET)") == datetime(2024, 12, 25, 12, 0, tzinfo=ny)
    assert parse_game_tipoff_et("2026-01-15", "10:30 (ET)") == datetime(2026, 1, 15, 22, 30, tzinfo=ny)
    assert parse_game_tipoff_et("01/15/2019", "") is None
    assert parse_game_tipoff_et("bad", "07:00 (ET)") is None
    assert parse_game_tipoff_et("01/15/2019", "25:00 (ET)") is None


def test_parse_report_title_time():
    assert parse_report_title_time(
        "Injury            Report:               01/15/26   05:00    PM"
    ) == datetime(2026, 1, 15, 17, 0, tzinfo=EASTERN_TZ)
    assert parse_report_title_time("Injury Report: 12/25/24 11:30 AM") == datetime(
        2024, 12, 25, 11, 30, tzinfo=EASTERN_TZ
    )


def test_canonical_team_name():
    assert canonical_team_name("Minnesota    Timberwolves") == "Minnesota Timberwolves"
    assert canonical_team_name("   Unknown   Team  Name  ") == "Unknown Team Name"
