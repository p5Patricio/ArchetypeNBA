import csv
from datetime import date
from pathlib import Path

import pytest

from app.analytics import historical_lines as hl


def test_parse_line_cell():
    # "pk" and "PK" -> Cell("spread", 0.0)
    assert hl.parse_line_cell("pk") == hl.Cell("spread", 0.0)
    assert hl.parse_line_cell("PK") == hl.Cell("spread", 0.0)

    # "NL" and "" -> kind "missing"
    assert hl.parse_line_cell("NL") == hl.Cell("missing")
    assert hl.parse_line_cell("nl") == hl.Cell("missing")
    assert hl.parse_line_cell("") == hl.Cell("missing")
    assert hl.parse_line_cell(None) == hl.Cell("missing")

    # ".5+03", "197.5u10", ".5ev", "-3" -> kind "bad"
    assert hl.parse_line_cell(".5+03") == hl.Cell("bad")
    assert hl.parse_line_cell("197.5u10") == hl.Cell("bad")
    assert hl.parse_line_cell(".5ev") == hl.Cell("bad")
    assert hl.parse_line_cell("-3") == hl.Cell("bad")

    # "215.5" -> total 215.5
    assert hl.parse_line_cell("215.5") == hl.Cell("total", 215.5)

    # "59.5" -> spread
    assert hl.parse_line_cell("59.5") == hl.Cell("spread", 59.5)

    # "60" -> total (TOTAL_THRESHOLD boundary)
    assert hl.parse_line_cell("60") == hl.Cell("total", 60.0)


def test_parse_moneyline():
    assert hl.parse_moneyline("-110") == -110
    assert hl.parse_moneyline("+150") == 150
    assert hl.parse_moneyline("NL") is None
    assert hl.parse_moneyline("8") is None
    assert hl.parse_moneyline("-7.5") is None


def test_split_spread_total():
    # (spread 5 on visitor, total 210 home) -> (5.0, 210.0, "ok")
    spread, total, status = hl.split_spread_total(hl.Cell("spread", 5.0), hl.Cell("total", 210.0))
    assert spread == 5.0
    assert total == 210.0
    assert status == "ok"

    # (total, spread 6.5 on home) -> (-6.5, total, "ok")
    spread, total, status = hl.split_spread_total(hl.Cell("total", 205.0), hl.Cell("spread", 6.5))
    assert spread == -6.5
    assert total == 205.0
    assert status == "ok"

    # (total, pk on home) -> spread 0.0
    spread, total, status = hl.split_spread_total(hl.Cell("total", 195.0), hl.Cell("spread", 0.0))
    assert spread == 0.0
    assert total == 195.0
    assert status == "ok"

    # two spreads -> (None, None, "ambiguous")
    spread, total, status = hl.split_spread_total(hl.Cell("spread", 3.0), hl.Cell("spread", 4.0))
    assert spread is None
    assert total is None
    assert status == "ambiguous"

    # two totals -> ambiguous
    spread, total, status = hl.split_spread_total(hl.Cell("total", 200.0), hl.Cell("total", 202.0))
    assert spread is None
    assert total is None
    assert status == "ambiguous"

    # (missing, spread 3 home) -> (-3.0, None, "partial")
    spread, total, status = hl.split_spread_total(hl.Cell("missing"), hl.Cell("spread", 3.0))
    assert spread == -3.0
    assert total is None
    assert status == "partial"


def _sbro_row(date_str, rot, vh, team, final="100", open_val="200", close_val="5", ml="-110"):
    return [date_str, rot, vh, team, "25", "25", "25", "25", final, open_val, close_val, ml, ""]


def test_parse_sbro_rows_handbuilt():
    # header row skipped
    header = list(hl.SBRO_HEADER)
    v1 = _sbro_row("1230", "501", "V", "Boston")
    h1 = _sbro_row("1230", "502", "H", "Miami")
    v2 = _sbro_row("102", "503", "V", "Boston")
    h2 = _sbro_row("102", "504", "H", "Miami")

    # year inference: season "2007-08" with dates "1230" then "102" gives 2007-12-30 and 2008-01-02
    games, rep = hl.parse_sbro_rows([header, v1, h1, v2, h2], "2007-08", "test.html")
    assert len(games) == 2
    assert games[0].game_date == date(2007, 12, 30)
    assert games[1].game_date == date(2008, 1, 2)

    # season "2019-20" with dates "1022", "311", "730", "1011" gives 2019-10-22, 2020-03-11, 2020-07-30, 2020-10-11
    b_v1 = _sbro_row("1022", "501", "V", "Boston")
    b_h1 = _sbro_row("1022", "502", "H", "Miami")
    b_v2 = _sbro_row("311", "503", "V", "Boston")
    b_h2 = _sbro_row("311", "504", "H", "Miami")
    b_v3 = _sbro_row("730", "505", "V", "Boston")
    b_h3 = _sbro_row("730", "506", "H", "Miami")
    b_v4 = _sbro_row("1011", "507", "V", "Boston")
    b_h4 = _sbro_row("1011", "508", "H", "Miami")
    bubble_games, _ = hl.parse_sbro_rows(
        [b_v1, b_h1, b_v2, b_h2, b_v3, b_h3, b_v4, b_h4], "2019-20", "bubble.html"
    )
    assert len(bubble_games) == 4
    assert bubble_games[0].game_date == date(2019, 10, 22)
    assert bubble_games[1].game_date == date(2020, 3, 11)
    assert bubble_games[2].game_date == date(2020, 7, 30)
    assert bubble_games[3].game_date == date(2020, 10, 11)

    # an orphan row (a V row followed by another V row) increments report.unpaired_rows and the following valid pair is still parsed
    orphan_v = _sbro_row("1230", "500", "V", "Chicago")
    orphan_games, orphan_rep = hl.parse_sbro_rows([orphan_v, v1, h1], "2007-08", "orphan.html")
    assert orphan_rep.unpaired_rows == 1
    assert len(orphan_games) == 1
    assert orphan_games[0].source_row_key.endswith("501-502")

    # an unknown team name increments report.unknown_teams and gives home_abbr None; source_row_key contains the rotation numbers
    unk_h = _sbro_row("1230", "502", "H", "Atlantis")
    unk_games, unk_rep = hl.parse_sbro_rows([v1, unk_h], "2007-08", "unk.html")
    assert len(unk_games) == 1
    assert unk_games[0].home_abbr is None
    assert unk_games[0].away_abbr == "BOS"
    assert unk_rep.unknown_teams["Atlantis"] == 1
    assert "501-502" in unk_games[0].source_row_key


def test_parse_sbro_html_fixture():
    fixture_path = Path(__file__).parent / "fixtures" / "historical" / "sbro_sample.html"
    html_text = fixture_path.read_text(encoding="utf-8")
    games, report = hl.parse_sbro_html(html_text, "2007-08", fixture_path.name)

    # 5 games with exactly the values listed above (dates 2007-10-30, 2007-12-31, 2008-01-01, 2008-01-02, 2008-01-03)
    assert len(games) == 5
    assert [g.game_date for g in games] == [
        date(2007, 10, 30),
        date(2007, 12, 31),
        date(2008, 1, 1),
        date(2008, 1, 2),
        date(2008, 1, 3),
    ]

    # pair 1: Portland @ SanAntonio
    g1 = games[0]
    assert g1.away_abbr == "POR" and g1.home_abbr == "SAS"
    assert g1.open_spread_home == -13.0
    assert g1.close_spread_home == -13.5
    assert g1.open_total == 189.5
    assert g1.close_total == 190.0
    assert g1.close_moneyline_home == -1400
    assert g1.close_moneyline_away == 900
    assert g1.home_score == 106 and g1.away_score == 97

    # pair 2: LA Lakers @ NewJersey
    g2 = games[1]
    assert g2.away_abbr == "LAL" and g2.home_abbr == "BKN"
    assert g2.open_spread_home == 4.0
    assert g2.close_spread_home == 0.0
    assert g2.open_total == 195.0
    assert g2.close_total == 196.5

    # pair 3: Seattle @ Utah
    g3 = games[2]
    assert g3.away_abbr == "OKC" and g3.home_abbr == "UTA"
    assert g3.open_spread_home is None
    assert g3.open_total == 205.0
    assert g3.close_spread_home == -7.5
    assert g3.close_total == 200.0
    assert g3.close_moneyline_home is None
    assert g3.close_moneyline_away is None

    # pair 4: Boston @ Miami (open ambiguous)
    g4 = games[3]
    assert g4.away_abbr == "BOS" and g4.home_abbr == "MIA"
    assert g4.open_spread_home is None
    assert g4.open_total is None
    assert g4.close_spread_home == 5.5
    assert g4.close_total == 199.0
    assert g4.close_moneyline_home == 130
    assert g4.close_moneyline_away == -150

    # pair 5: Toronto vs NewYork (neutral)
    g5 = games[4]
    assert g5.neutral_site is True
    assert g5.away_abbr == "TOR" and g5.home_abbr == "NYK"
    assert g5.open_spread_home == -2.0
    assert g5.close_spread_home == -1.5
    assert g5.open_total == 200.0
    assert g5.close_total == 201.0
    assert g5.close_moneyline_home == -140
    assert g5.close_moneyline_away == 120

    assert report.ambiguous_columns == 1
    assert report.no_line_cells >= 1


def test_normalize_sbro_team():
    assert hl.normalize_sbro_team("LA Clippers") == "LAC"
    assert hl.normalize_sbro_team("LAClippers") == "LAC"
    assert hl.normalize_sbro_team("NewJersey") == "BKN"
    assert hl.normalize_sbro_team("Seattle") == "OKC"
    assert hl.normalize_sbro_team("NewOrleans") == "NOP"
    assert hl.normalize_sbro_team("Nowhere") is None


def test_normalize_kaggle_team():
    assert hl.normalize_kaggle_team("no") == "NOP"
    assert hl.normalize_kaggle_team("gs") == "GSW"
    assert hl.normalize_kaggle_team("utah") == "UTA"
    assert hl.normalize_kaggle_team("wsh") == "WAS"


def test_parse_kaggle_rows_fixture():
    fixture_path = Path(__file__).parent / "fixtures" / "historical" / "kaggle_sample.csv"
    with open(fixture_path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        games, report = hl.parse_kaggle_rows(reader, fixture_path.name)

    assert len(games) == 4
    # season 2008 -> "2007-08", 2024 -> "2023-24"
    assert games[0].season_label == "2007-08"
    assert games[2].season_label == "2023-24"
    assert games[3].season_label == "2025-26"

    # whos_favored home spread 13 -> close_spread_home -13.0
    assert games[0].close_spread_home == -13.0

    # away 3 -> +3.0
    assert games[1].close_spread_home == 3.0

    # spread 0 -> 0.0
    assert games[2].close_spread_home == 0.0

    # empty moneylines -> None
    assert games[2].close_moneyline_home is None
    assert games[2].close_moneyline_away is None

    # open_spread_home always None
    for g in games:
        assert g.open_spread_home is None

    # unknown team code counted in report.unknown_teams
    assert report.unknown_teams["xyz"] == 1
    assert games[3].away_abbr is None
    assert games[3].home_abbr == "BOS"


def test_line_maths():
    assert hl.devig_moneyline(-110, -110) == pytest.approx(0.5)

    p_home = hl.devig_moneyline(-200, 170)
    assert 0.6 < p_home < 0.7
    assert p_home == pytest.approx((2 / 3) / ((2 / 3) + (100 / 270)))

    assert hl.devig_moneyline(150, 150) is None
    assert hl.devig_moneyline(None, -110) is None

    assert hl.spread_implied_prob(0, 12) == 0.5
    assert hl.spread_implied_prob(-5, 12) > 0.5

    assert hl.spread_clv_points(1, -3, -5) == 2
    assert hl.spread_clv_points(-1, -3, -5) == -2

    assert hl.total_clv_points(1, 210, 212) == 2
    assert hl.total_clv_points(-1, 210, 212) == -2

    assert hl.clv_probability(0, 12) == 0.0
    assert hl.clv_probability(2, 12) > 0.0

    assert hl.ats_outcome(1, 5, -4.5) == 1
    assert hl.ats_outcome(1, 4, -4) == 0
    assert hl.ats_outcome(-1, 3, -4.5) == 1
    assert hl.ats_outcome(-1, 10, -4.5) == -1

    assert hl.total_outcome(1, 211, 210.5) == 1

    assert hl.profit_at_assumed_price(1) == pytest.approx(100 / 110)
    assert hl.profit_at_assumed_price(-1) == -1.0
    assert hl.profit_at_assumed_price(0) == 0.0
