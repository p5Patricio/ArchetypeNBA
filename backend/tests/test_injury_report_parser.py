from pathlib import Path
import pytest

from app.services.injury_report_parser import (
    STATUS_AVAILABILITY_PROBABILITIES,
    ParsedInjuryRow,
    normalize_player_name,
    parse_injury_report_text,
)

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def test_status_availability_probabilities_constants():
    """Verify that expected statuses are defined as ESTIMATES with valid probabilities."""
    expected_statuses = {"AVAILABLE", "PROBABLE", "QUESTIONABLE", "DOUBTFUL", "OUT"}
    assert set(STATUS_AVAILABILITY_PROBABILITIES.keys()) == expected_statuses
    for status, prob in STATUS_AVAILABILITY_PROBABILITIES.items():
        assert 0.0 <= prob <= 1.0

    assert STATUS_AVAILABILITY_PROBABILITIES["AVAILABLE"] == 1.0
    assert STATUS_AVAILABILITY_PROBABILITIES["PROBABLE"] == 0.75
    assert STATUS_AVAILABILITY_PROBABILITIES["QUESTIONABLE"] == 0.50
    assert STATUS_AVAILABILITY_PROBABILITIES["DOUBTFUL"] == 0.25
    assert STATUS_AVAILABILITY_PROBABILITIES["OUT"] == 0.0


def test_normalize_player_name():
    assert normalize_player_name("James, LeBron") == "LeBron James"
    assert normalize_player_name("Doncic, Luka") == "Luka Doncic"
    assert normalize_player_name("Curry, Stephen") == "Stephen Curry"
    assert normalize_player_name("Smith Jr., Nick") == "Nick Smith Jr."
    assert normalize_player_name("Jackson Jr.,Jaren") == "Jaren Jackson Jr."
    assert normalize_player_name("Williams III,Robert") == "Robert Williams III"
    assert normalize_player_name("Brown,  Jaylen") == "Jaylen Brown"
    assert normalize_player_name("Giannis Antetokounmpo") == "Giannis Antetokounmpo"
    assert normalize_player_name("") == ""


def test_parse_with_page_headers_and_unknown_status():
    text = """
    10/28/2026 07:00 (ET) BOS@DET Boston Celtics Brown, Jaylen Available Hamstring
    Page 2 of 5
    NBA INJURY REPORT
    Game Date Game Time Matchup Team Player Name Current Status Reason
    Tatum, Jayson Questionable Illness
    """
    rows = parse_injury_report_text(text)
    assert len(rows) == 2
    assert rows[0].player_name == "Jaylen Brown"
    assert rows[1].player_name == "Jayson Tatum"
    assert rows[1].team == "Boston Celtics"
    assert rows[1].matchup == "BOS@DET"
    assert rows[1].availability_prob == 0.50


def test_parse_synthetic_injury_report_text():
    fixture_path = FIXTURES_DIR / "synthetic_injury_report.txt"
    with open(fixture_path, "r", encoding="utf-8") as f:
        text = f.read()

    rows = parse_injury_report_text(text)
    assert len(rows) == 10

    # 1. Jaylen Brown
    r0 = rows[0]
    assert r0.player_name == "Jaylen Brown"
    assert r0.team == "Boston Celtics"
    assert r0.matchup == "BOS@DET"
    assert r0.game_date == "10/28/2026"
    assert "07:00" in r0.game_time
    assert r0.status == "Available"
    assert r0.availability_prob == 1.0
    assert "Hamstring" in r0.reason

    # 2. Kristaps Porzingis (inherits team, matchup, date from previous row; line-wrapped reason)
    r1 = rows[1]
    assert r1.player_name == "Kristaps Porzingis"
    assert r1.team == "Boston Celtics"
    assert r1.matchup == "BOS@DET"
    assert r1.game_date == "10/28/2026"
    assert r1.status == "Out"
    assert r1.availability_prob == 0.0
    assert "tibialis" in r1.reason and "dislocation" in r1.reason

    # 3. Cade Cunningham (switches to Detroit Pistons)
    r2 = rows[2]
    assert r2.player_name == "Cade Cunningham"
    assert r2.team == "Detroit Pistons"
    assert r2.matchup == "BOS@DET"
    assert r2.status == "Questionable"
    assert r2.availability_prob == 0.50

    # 4. Isaiah Stewart (Detroit Pistons repeated/inherited)
    r3 = rows[3]
    assert r3.player_name == "Isaiah Stewart"
    assert r3.team == "Detroit Pistons"
    assert r3.status == "Out"
    assert r3.availability_prob == 0.0

    # 5. Jimmy Butler (new game 07:30 ET LAL@MIA, Miami Heat)
    r4 = rows[4]
    assert r4.player_name == "Jimmy Butler"
    assert r4.team == "Miami Heat"
    assert r4.matchup == "LAL@MIA"
    assert r4.status == "Doubtful"
    assert r4.availability_prob == 0.25

    # 6. Anthony Davis (Los Angeles Lakers, line-wrapped reason)
    r5 = rows[5]
    assert r5.player_name == "Anthony Davis"
    assert r5.team == "Los Angeles Lakers"
    assert r5.matchup == "LAL@MIA"
    assert r5.status == "Probable"
    assert r5.availability_prob == 0.75
    assert "Achilles" in r5.reason and "tendinitis" in r5.reason

    # 7. LeBron James (Los Angeles Lakers inherited)
    r6 = rows[6]
    assert r6.player_name == "LeBron James"
    assert r6.team == "Los Angeles Lakers"
    assert r6.status == "Available"
    assert r6.availability_prob == 1.0

    # 8. Nikola Jokic (new game 10/29/2026, 08:00 ET, DEN@GSW, Denver Nuggets)
    r7 = rows[7]
    assert r7.player_name == "Nikola Jokic"
    assert r7.team == "Denver Nuggets"
    assert r7.matchup == "DEN@GSW"
    assert r7.game_date == "10/29/2026"
    assert r7.status == "Available"
    assert r7.availability_prob == 1.0

    # 9. Stephen Curry (Golden State Warriors)
    r8 = rows[8]
    assert r8.player_name == "Stephen Curry"
    assert r8.team == "Golden State Warriors"
    assert r8.status == "Questionable"
    assert r8.availability_prob == 0.50

    # 10. Draymond Green (Golden State Warriors inherited)
    r9 = rows[9]
    assert r9.player_name == "Draymond Green"
    assert r9.team == "Golden State Warriors"
    assert r9.status == "Available"
    assert r9.availability_prob == 1.0


def test_empty_text_returns_empty_list():
    assert parse_injury_report_text("") == []
    assert parse_injury_report_text("NBA INJURY REPORT\nPage 1 of 1\n") == []
    assert parse_injury_report_text("NOT YET SUBMITTED\n") == []


def test_parse_synthetic_injury_report_layout():
    """
    Tests parsing a fixture shaped identically to official NBA injury report layout text.
    Verifies:
      1. Inverted order restoration per page.
      2. Blank carried cells (date, time, matchup, team).
      3. Suffix name handling ('Baker Jr.,Ethan', 'Smith III,Robert').
      4. Available status kept.
      5. Page-break continuation of wrapped reasons across pages.
      6. NOT YET SUBMITTED rows yielding zero player rows without error.
    """
    fixture_path = FIXTURES_DIR / "synthetic_injury_report_layout.txt"
    with open(fixture_path, "r", encoding="utf-8") as f:
        text = f.read()

    rows = parse_injury_report_text(text)
    assert len(rows) == 6

    # Row 0: Jordan Kent
    r0 = rows[0]
    assert r0.player_name == "Jordan Kent"
    assert r0.raw_name == "Kent, Jordan"
    assert r0.team == "Portland Trail Blazers"
    assert r0.matchup == "POR@UTA"
    assert r0.game_date == "10/31/2026"
    assert "03:00" in r0.game_time
    assert r0.status == "Out"
    assert r0.availability_prob == 0.0
    assert "G League - Two-Way" in r0.reason

    # Row 1: Ethan Baker Jr. (prefix and suffix combined reason, carried Portland)
    r1 = rows[1]
    assert r1.player_name == "Ethan Baker Jr."
    assert r1.raw_name == "Baker Jr.,Ethan"
    assert r1.team == "Portland Trail Blazers"
    assert r1.status == "Out"
    assert "Hamstring Strain" in r1.reason and "Management" in r1.reason

    # Row 2: Robert Smith III (Available status kept, Utah Jazz)
    r2 = rows[2]
    assert r2.player_name == "Robert Smith III"
    assert r2.team == "Utah Jazz"
    assert r2.status == "Available"
    assert r2.availability_prob == 1.0

    # Row 3: Jane Doe (Philadelphia 76ers, PHI@CHA, 06:00 ET)
    r3 = rows[3]
    assert r3.player_name == "Jane Doe"
    assert r3.team == "Philadelphia 76ers"
    assert r3.matchup == "PHI@CHA"
    assert "06:00" in r3.game_time
    assert r3.status == "Questionable"
    assert r3.availability_prob == 0.50

    # Row 4: Alex Taylor (reason spans across page break: 'Reaction' on Page 1, 'Surgery' on Page 2)
    r4 = rows[4]
    assert r4.player_name == "Alex Taylor"
    assert r4.team == "Philadelphia 76ers"
    assert r4.status == "Out"
    assert "Knee Injury" in r4.reason
    assert "Reaction" in r4.reason
    assert "Surgery" in r4.reason

    # Row 5: David Miller (Philadelphia 76ers carried across page break!)
    r5 = rows[5]
    assert r5.player_name == "David Miller"
    assert r5.team == "Philadelphia 76ers"
    assert r5.status == "Probable"
    assert r5.availability_prob == 0.75
    assert "Illness" in r5.reason

