"""
Parsers and line maths for free historical NBA game lines (pure: no DB, no network, no file I/O).

Two sources, both read from files downloaded once by the owner (``~/ArchetypeNBA-data/raw/<source>/``):

* SBRO (Sportsbook Reviews Online archive, 2007-08 .. mid-January 2023). One HTML page per season whose table has
  the columns ``Date Rot VH Team 1st 2nd 3rd 4th Final Open Close ML 2H``. Each game is TWO consecutive rows: the
  visitor (``V``) then the home team (``H``); neutral-site games use ``N`` for both rows and the second row is the
  nominal home team. In the ``Open`` and ``Close`` columns one row of the pair holds the point spread (on the
  favourite's row, as a positive number; ``pk`` = 0) and the other the game total. They are told apart by magnitude:
  a value of ``TOTAL_THRESHOLD`` (60) or more is a total. ``NL`` (no line), empty and unparseable cells
  (``.5+03``, ``197.5u10``, ...) stay missing (rule 3: a missing value is never guessed). A column whose two cells
  are both spreads or both totals is ambiguous and stays missing. ``Date`` is ``MMDD`` without a year: the year
  starts at the season's first year and advances when the month wraps (December -> January), which also handles
  the 2019-20 bubble games of July-October 2020.
* Kaggle ``cviaxmiwnptr/nba-betting-data-october-2007-to-june-2024`` (CC0 per the uploader), file
  ``nba_2008-2026.csv``: one row per game with ``whos_favored``, an unsigned ``spread``, ``total`` and moneylines.
  It has ONE line per game (treated as the close; verified against SBRO's close in the import reconciliation) and
  no opening line. Moneylines end in January 2023 (later rows come from other upstream sources).

Lines are stored from the home side: ``spread_home = -3`` means the home team is a 3-point favourite and covers when
``home_margin - 3 > 0``. Team names map to CURRENT franchise abbreviations (New Jersey -> BKN, Seattle -> OKC,
New Orleans -> NOP), matching Elo's franchise continuity.
"""
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from html.parser import HTMLParser
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

SOURCE_SBRO = "sbro"
SOURCE_KAGGLE = "kaggle_cviaxmiwnptr"

TOTAL_THRESHOLD = 60.0  # NBA spreads are far below 60 points and totals far above
SBRO_HEADER = ("Date", "Rot", "VH", "Team", "1st", "2nd", "3rd", "4th", "Final", "Open", "Close", "ML", "2H")

# SBRO team names (spaces removed, lower case) -> current franchise abbreviation.
SBRO_TEAM_NAMES: Dict[str, str] = {
    "atlanta": "ATL",
    "boston": "BOS",
    "brooklyn": "BKN",
    "newjersey": "BKN",
    "charlotte": "CHA",
    "chicago": "CHI",
    "cleveland": "CLE",
    "dallas": "DAL",
    "denver": "DEN",
    "detroit": "DET",
    "goldenstate": "GSW",
    "houston": "HOU",
    "indiana": "IND",
    "laclippers": "LAC",
    "lalakers": "LAL",
    "memphis": "MEM",
    "miami": "MIA",
    "milwaukee": "MIL",
    "minnesota": "MIN",
    "neworleans": "NOP",
    "newyork": "NYK",
    "oklahomacity": "OKC",
    "seattle": "OKC",
    "orlando": "ORL",
    "philadelphia": "PHI",
    "phoenix": "PHX",
    "portland": "POR",
    "sacramento": "SAC",
    "sanantonio": "SAS",
    "toronto": "TOR",
    "utah": "UTA",
    "washington": "WAS",
}

# Kaggle team codes -> current franchise abbreviation (the file already uses current franchises).
KAGGLE_TEAM_CODES: Dict[str, str] = {
    "atl": "ATL", "bkn": "BKN", "bos": "BOS", "cha": "CHA", "chi": "CHI", "cle": "CLE", "dal": "DAL",
    "den": "DEN", "det": "DET", "gs": "GSW", "hou": "HOU", "ind": "IND", "lac": "LAC", "lal": "LAL",
    "mem": "MEM", "mia": "MIA", "mil": "MIL", "min": "MIN", "no": "NOP", "ny": "NYK", "okc": "OKC",
    "orl": "ORL", "phi": "PHI", "phx": "PHX", "por": "POR", "sa": "SAS", "sac": "SAC", "tor": "TOR",
    "utah": "UTA", "wsh": "WAS",
}

_NUMBER = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)$")


def normalize_sbro_team(name: str) -> Optional[str]:
    """Current franchise abbreviation of an SBRO team name ('LA Clippers', 'LAClippers' -> 'LAC'), or None."""
    return SBRO_TEAM_NAMES.get(re.sub(r"[^a-z]", "", (name or "").lower()))


def normalize_kaggle_team(code: str) -> Optional[str]:
    return KAGGLE_TEAM_CODES.get((code or "").strip().lower())


def season_label_from_end_year(end_year: int) -> str:
    """2008 -> '2007-08'."""
    return f"{end_year - 1}-{end_year % 100:02d}"


# --------------------------------------------------------------------------------------------- cell parsing

@dataclass(frozen=True)
class Cell:
    """A parsed Open/Close cell: ``kind`` is 'spread', 'total', 'missing' (NL or empty) or 'bad' (unparseable)."""

    kind: str
    value: Optional[float] = None


def parse_line_cell(raw: Optional[str]) -> Cell:
    text = (raw or "").strip()
    if text == "" or text.upper() == "NL":
        return Cell("missing")
    if text.lower() == "pk":
        return Cell("spread", 0.0)
    if not _NUMBER.match(text):
        return Cell("bad")
    value = float(text)
    if value < 0:  # SBRO lists the favourite's spread unsigned; a negative number is not in the documented format
        return Cell("bad")
    return Cell("total", value) if value >= TOTAL_THRESHOLD else Cell("spread", value)


def parse_moneyline(raw: Optional[str]) -> Optional[int]:
    """American odds as an int; None for NL, empty, unparseable or impossible values (|odds| < 100)."""
    text = (raw or "").strip()
    if not re.match(r"^[+-]?\d+$", text):
        return None
    value = int(text)
    return value if abs(value) >= 100 else None


def parse_int(raw: Optional[str]) -> Optional[int]:
    text = (raw or "").strip()
    return int(text) if re.match(r"^\d+$", text) else None


def split_spread_total(visitor: Cell, home: Cell) -> Tuple[Optional[float], Optional[float], str]:
    """
    (home spread, total, status) from the two cells of one SBRO column. The spread sits on the favourite's row:
    on the visitor's row it means the visitor is favoured (home spread positive), on the home row the home team is.
    ``status`` is 'ok', 'partial' (one cell missing or bad) or 'ambiguous' (two spreads or two totals).
    """
    kinds = (visitor.kind, home.kind)
    if kinds in (("spread", "spread"), ("total", "total")):
        return None, None, "ambiguous"
    spread: Optional[float] = None
    total: Optional[float] = None
    if visitor.kind == "spread":
        spread = visitor.value  # away favoured: home gets the points
    elif home.kind == "spread":
        spread = -home.value if home.value else 0.0
    if visitor.kind == "total":
        total = visitor.value
    elif home.kind == "total":
        total = home.value
    status = "ok" if spread is not None and total is not None else "partial"
    return spread, total, status


# --------------------------------------------------------------------------------------------- HTML tables

class _TableRows(HTMLParser):
    """Collects the text of every <td>/<th> cell, row by row (stdlib only; the page's scripts are never run)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: List[List[str]] = []
        self._row: Optional[List[str]] = None
        self._cell: Optional[List[str]] = None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._row is not None and self._cell is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)


def html_table_rows(html_text: str) -> List[List[str]]:
    parser = _TableRows()
    parser.feed(html_text)
    parser.close()
    return parser.rows


# --------------------------------------------------------------------------------------------- parsed lines

@dataclass(frozen=True)
class ParsedLine:
    """One game's lines from one source; team fields are current franchise abbreviations (None when unknown)."""

    source: str
    source_row_key: str
    season_label: str
    game_date: date
    home_abbr: Optional[str]
    away_abbr: Optional[str]
    home_name_raw: str
    away_name_raw: str
    neutral_site: bool = False
    open_spread_home: Optional[float] = None
    close_spread_home: Optional[float] = None
    open_total: Optional[float] = None
    close_total: Optional[float] = None
    open_moneyline_home: Optional[int] = None
    open_moneyline_away: Optional[int] = None
    close_moneyline_home: Optional[int] = None
    close_moneyline_away: Optional[int] = None
    home_score: Optional[int] = None
    away_score: Optional[int] = None


@dataclass
class ParseReport:
    rows: int = 0
    games: int = 0
    unpaired_rows: int = 0
    bad_dates: int = 0
    dates_out_of_order: int = 0
    bad_cells: int = 0  # unparseable Open/Close cells (kept missing)
    no_line_cells: int = 0  # NL or empty Open/Close cells
    ambiguous_columns: int = 0  # Open or Close column with two spreads or two totals
    bad_moneylines: int = 0
    unknown_teams: Counter = field(default_factory=Counter)

    def merge(self, other: "ParseReport") -> None:
        for name in ("rows", "games", "unpaired_rows", "bad_dates", "dates_out_of_order", "bad_cells",
                     "no_line_cells", "ambiguous_columns", "bad_moneylines"):
            setattr(self, name, getattr(self, name) + getattr(other, name))
        self.unknown_teams.update(other.unknown_teams)


def _sbro_date(mmdd: str, year: int) -> Optional[date]:
    text = (mmdd or "").strip()
    if not re.match(r"^\d{3,4}$", text):
        return None
    try:
        return date(year, int(text[:-2]), int(text[-2:]))
    except ValueError:
        return None


def parse_sbro_rows(rows: Sequence[Sequence[str]], season_label: str, file_key: str) -> Tuple[List[ParsedLine], ParseReport]:
    """
    Games from the table rows of one SBRO season page (header rows are skipped). Rows that do not form a V/H (or
    N/N) pair are counted and skipped, never guessed.
    """
    report = ParseReport()
    data = [list(r) for r in rows if r and r[0].strip() != "Date"]
    report.rows = len(data)
    start_year = int(season_label[:4])
    year, prev_month = start_year, None
    prev_date: Optional[date] = None
    out: List[ParsedLine] = []

    i = 0
    while i < len(data):
        first = data[i]
        second = data[i + 1] if i + 1 < len(data) else None
        flags = (first[2].strip().upper() if len(first) > 2 else "", second[2].strip().upper() if second and len(second) > 2 else "")
        if second is None or len(first) < 12 or len(second) < 12 or flags not in (("V", "H"), ("N", "N")):
            report.unpaired_rows += 1
            i += 1
            continue
        i += 2

        text = first[0].strip()
        month = int(text[:-2]) if re.match(r"^\d{3,4}$", text) else None
        if month is not None and prev_month is not None and month < prev_month and prev_month - month >= 6:
            year += 1
        game_day = _sbro_date(text, year)
        if game_day is None:
            report.bad_dates += 1
            continue
        prev_month = month
        if prev_date is not None and game_day < prev_date:
            report.dates_out_of_order += 1
        prev_date = game_day

        visitor, home = first, second
        cells = {}
        for col, name in ((9, "open"), (10, "close")):
            v_cell, h_cell = parse_line_cell(visitor[col]), parse_line_cell(home[col])
            for cell in (v_cell, h_cell):
                if cell.kind == "bad":
                    report.bad_cells += 1
                elif cell.kind == "missing":
                    report.no_line_cells += 1
            spread, total, status = split_spread_total(v_cell, h_cell)
            if status == "ambiguous":
                report.ambiguous_columns += 1
            cells[name] = (spread, total)
        ml_away, ml_home = parse_moneyline(visitor[11]), parse_moneyline(home[11])
        for raw, parsed in ((visitor[11], ml_away), (home[11], ml_home)):
            if parsed is None and raw.strip().upper() not in ("", "NL"):
                report.bad_moneylines += 1

        away_abbr, home_abbr = normalize_sbro_team(visitor[3]), normalize_sbro_team(home[3])
        for raw_name, abbr in ((visitor[3], away_abbr), (home[3], home_abbr)):
            if abbr is None:
                report.unknown_teams[raw_name] += 1
        out.append(
            ParsedLine(
                source=SOURCE_SBRO,
                source_row_key=f"{file_key}:{text}:{visitor[1].strip()}-{home[1].strip()}",
                season_label=season_label,
                game_date=game_day,
                home_abbr=home_abbr,
                away_abbr=away_abbr,
                home_name_raw=home[3],
                away_name_raw=visitor[3],
                neutral_site=flags == ("N", "N"),
                open_spread_home=cells["open"][0],
                close_spread_home=cells["close"][0],
                open_total=cells["open"][1],
                close_total=cells["close"][1],
                close_moneyline_home=ml_home,
                close_moneyline_away=ml_away,
                home_score=parse_int(home[8]),
                away_score=parse_int(visitor[8]),
            )
        )
    report.games = len(out)
    return out, report


def season_label_from_sbro_name(name: str) -> Optional[str]:
    """'nba-odds-2007-08.html' -> '2007-08'."""
    match = re.search(r"(\d{4})-(\d{2})", name or "")
    return f"{match.group(1)}-{match.group(2)}" if match else None


def parse_sbro_html(html_text: str, season_label: str, file_key: str) -> Tuple[List[ParsedLine], ParseReport]:
    return parse_sbro_rows(html_table_rows(html_text), season_label, file_key)


def _float_or_none(raw: Optional[str]) -> Optional[float]:
    text = (raw or "").strip()
    return float(text) if _NUMBER.match(text) else None


def parse_kaggle_rows(rows: Iterable[Mapping[str, str]], file_key: str = "nba_2008-2026.csv") -> Tuple[List[ParsedLine], ParseReport]:
    """Games from the Kaggle CSV (``csv.DictReader`` rows). The single spread/total is stored as the close."""
    report = ParseReport()
    out: List[ParsedLine] = []
    for index, row in enumerate(rows, start=2):  # line 1 is the header
        report.rows += 1
        try:
            game_day = date.fromisoformat((row.get("date") or "").strip())
            season_label = season_label_from_end_year(int((row.get("season") or "").strip()))
        except ValueError:
            report.bad_dates += 1
            continue
        spread = _float_or_none(row.get("spread"))
        favored = (row.get("whos_favored") or "").strip().lower()
        if spread is not None and favored not in ("home", "away"):
            spread = None
            report.bad_cells += 1
        spread_home = None
        if spread is not None:
            spread_home = 0.0 if spread == 0 else (-spread if favored == "home" else spread)
        ml_home, ml_away = parse_moneyline(row.get("moneyline_home")), parse_moneyline(row.get("moneyline_away"))
        for key, parsed in (("moneyline_home", ml_home), ("moneyline_away", ml_away)):
            if parsed is None and (row.get(key) or "").strip():
                report.bad_moneylines += 1
        home_abbr, away_abbr = normalize_kaggle_team(row.get("home")), normalize_kaggle_team(row.get("away"))
        for raw_name, abbr in ((row.get("away") or "", away_abbr), (row.get("home") or "", home_abbr)):
            if abbr is None:
                report.unknown_teams[raw_name] += 1
        out.append(
            ParsedLine(
                source=SOURCE_KAGGLE,
                source_row_key=f"{file_key}:{index}",
                season_label=season_label,
                game_date=game_day,
                home_abbr=home_abbr,
                away_abbr=away_abbr,
                home_name_raw=row.get("home") or "",
                away_name_raw=row.get("away") or "",
                close_spread_home=spread_home,
                close_total=_float_or_none(row.get("total")),
                close_moneyline_home=ml_home,
                close_moneyline_away=ml_away,
                home_score=parse_int(row.get("score_home")),
                away_score=parse_int(row.get("score_away")),
            )
        )
    report.games = len(out)
    return out, report


# --------------------------------------------------------------------------------------------- line maths

def normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def american_to_decimal(odds: int) -> float:
    return 1.0 + (odds / 100.0 if odds > 0 else 100.0 / -odds)


def devig_moneyline(ml_home: Optional[int], ml_away: Optional[int], max_overround: float = 1.25) -> Optional[float]:
    """
    Proportional de-vig of a two-way moneyline: the home team's fair probability. None when a side is missing or
    the pair is implausible (implied probabilities summing below 1, i.e. an arbitrage, or above ``max_overround``).
    """
    if ml_home is None or ml_away is None:
        return None
    q_home, q_away = 1.0 / american_to_decimal(ml_home), 1.0 / american_to_decimal(ml_away)
    total = q_home + q_away
    if total < 1.0 or total > max_overround:
        return None
    return q_home / total


def spread_implied_prob(spread_home: float, sigma: float) -> float:
    """P(home wins) when the home margin is N(-spread_home, sigma)."""
    return normal_cdf(-spread_home / sigma)


def spread_clv_points(side: int, open_spread_home: float, close_spread_home: float) -> float:
    """
    Points of closing-line value of a spread bet taken at the open: ``side`` +1 = home, -1 = away. A home bet at -3
    that closes -5 gained 2 points (the close moved toward the bet).
    """
    return side * (open_spread_home - close_spread_home)


def total_clv_points(side: int, open_total: float, close_total: float) -> float:
    """``side`` +1 = over, -1 = under: an over at 210 that closes 212 gained 2 points."""
    return side * (close_total - open_total)


def clv_probability(clv_points: float, sigma: float) -> float:
    """
    Probability-scale CLV: the cover probability of the opening number under the closing distribution minus 1/2,
    with the margin (or total) normal around the close with ``sigma`` (continuous approximation, pushes ignored).
    """
    return normal_cdf(clv_points / sigma) - 0.5


def ats_outcome(side: int, home_margin: float, spread_home: float) -> int:
    """+1 win, 0 push, -1 loss of a spread bet (``side`` +1 home, -1 away) graded at ``spread_home``."""
    cover = side * (home_margin + spread_home)
    return 1 if cover > 0 else (-1 if cover < 0 else 0)


def total_outcome(side: int, game_total: float, line: float) -> int:
    diff = side * (game_total - line)
    return 1 if diff > 0 else (-1 if diff < 0 else 0)


ASSUMED_PRICE_AMERICAN = -110  # ASSUMPTION: the archives carry no spread/total prices


def profit_at_assumed_price(outcome: int, american: int = ASSUMED_PRICE_AMERICAN) -> float:
    """Profit per unit staked of a graded bet at an assumed American price (push = 0)."""
    if outcome > 0:
        return american_to_decimal(american) - 1.0
    return -1.0 if outcome < 0 else 0.0
