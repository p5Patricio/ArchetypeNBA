"""
Parser for the layout-mode text that ``pypdf`` extracts from official NBA injury report PDFs.

The PDF format changed over time. Three layouts are known (verified on official PDFs, 2026-11-06):

``CATEGORY_COLUMNS`` (2018-19 and the start of 2019-20)
    Nine columns: Game Date | Game Time | Matchup | Team | Player Name | Category | Reason |
    Current Status | Previous Status. Pages are extracted top-down with the column header on every
    page. Long team names wrap onto the next line ("Minnesota" / "Timberwolves"), so cells are
    assigned to columns by their horizontal position under the header.

``STATUS_REASON_UPRIGHT`` (2019-20 through the 2022-23 regular season)
    Seven columns: ... | Player Name | Current Status | Reason (category and detail joined by " - ").
    Pages are extracted top-down with the header on every page.

``STATUS_REASON_INVERTED`` (2023 playoffs onward)
    Same seven columns, but ``pypdf`` emits every page bottom-up ("Page N of M" first, the title
    last) and only page 1 carries the column header. Multi-line reasons straddle their row, so
    a reason line that starts with a reason category belongs to the next row in reading order.

The layout is detected from the column header. Text without a recognisable header raises
``InjuryReportLayoutError`` (never guessed: rule 3). Every layout carries forward blank merged
cells (date, time, matchup, team) across rows and page breaks.

``Injury Report: MM/DD/YY HH:MM AM|PM`` is the report's true publication time; the hourly file
names of 2018-2025 (``..._05PM.pdf``) hold the report published at HH:30.
"""
from dataclasses import dataclass, field
from datetime import date, datetime, time
from enum import Enum
import re
from typing import Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from pydantic import BaseModel

EASTERN_TZ = ZoneInfo("America/New_York")

# ESTIMATES to be calibrated against historical game logs and betting market reactions, not empirical facts.
# Represents prior probability of a player suiting up given their designated injury report status.
STATUS_AVAILABILITY_PROBABILITIES: dict[str, float] = {
    "AVAILABLE": 1.0,
    "PROBABLE": 0.75,
    "QUESTIONABLE": 0.50,
    "DOUBTFUL": 0.25,
    "OUT": 0.0,
}

NBA_TEAMS = [
    "Atlanta Hawks",
    "Boston Celtics",
    "Brooklyn Nets",
    "Charlotte Hornets",
    "Chicago Bulls",
    "Cleveland Cavaliers",
    "Dallas Mavericks",
    "Denver Nuggets",
    "Detroit Pistons",
    "Golden State Warriors",
    "Houston Rockets",
    "Indiana Pacers",
    "LA Clippers",
    "Los Angeles Clippers",
    "Los Angeles Lakers",
    "Memphis Grizzlies",
    "Miami Heat",
    "Milwaukee Bucks",
    "Minnesota Timberwolves",
    "New Orleans Pelicans",
    "New York Knicks",
    "Oklahoma City Thunder",
    "Orlando Magic",
    "Philadelphia 76ers",
    "Phoenix Suns",
    "Portland Trail Blazers",
    "Sacramento Kings",
    "San Antonio Spurs",
    "Toronto Raptors",
    "Utah Jazz",
    "Washington Wizards",
]

# Reason categories used by the report. In the inverted layout a continuation line that starts
# with one of them opens the reason of the NEXT row (multi-line cells straddle their row).
REASON_CATEGORY_PREFIXES = (
    "Injury/Illness",
    "G League",
    "Personal Reasons",
    "Personal",
    "Rest",
    "Not With Team",
    "League Suspension",
    "Suspension",
    "Health and Safety Protocols",
    "Health and Safety",
    "Coach's Decision",
    "Concussion Protocol",
)


class InjuryReportLayout(str, Enum):
    CATEGORY_COLUMNS = "category_columns"
    STATUS_REASON_UPRIGHT = "status_reason_upright"
    STATUS_REASON_INVERTED = "status_reason_inverted"


class InjuryReportLayoutError(ValueError):
    """Raised when the text does not match any known injury report layout (rule 3: never guess)."""


class ParsedInjuryRow(BaseModel):
    game_date: str = ""
    game_time: str = ""
    matchup: str = ""
    team: str = ""
    player_name: str = ""
    raw_name: str = ""
    status: str = ""
    reason: str = ""
    availability_prob: Optional[float] = None


@dataclass(frozen=True)
class ParsedGame:
    """A game listed in the report (also games whose teams have NOT YET SUBMITTED)."""

    game_date: str
    game_time: str
    matchup: str


@dataclass
class ParsedInjuryReport:
    layout: InjuryReportLayout
    rows: List[ParsedInjuryRow] = field(default_factory=list)
    report_time_et: Optional[datetime] = None
    games: List[ParsedGame] = field(default_factory=list)


def normalize_player_name(raw_name: str) -> str:
    """
    Normalizes 'Last, First' or 'Last Suffix, First' (e.g. 'Jackson Jr.,Jaren')
    to 'First Last Suffix' (e.g. 'Jaren Jackson Jr.').
    If no comma is found, returns trimmed string.
    """
    if not raw_name:
        return ""
    if "," in raw_name:
        parts = [p.strip() for p in raw_name.split(",", 1)]
        if len(parts) == 2 and parts[1]:
            first = re.sub(r"\s+", " ", parts[1]).strip()
            last = re.sub(r"\s+", " ", parts[0]).strip()
            return f"{first} {last}".strip()
    return re.sub(r"\s+", " ", raw_name).strip()


def _build_team_regex() -> re.Pattern:
    """Builds regex that matches any NBA team even with multiple or varying whitespace."""
    patterns = []
    for t in sorted(NBA_TEAMS, key=len, reverse=True):
        words = t.split()
        pat = r"\s*".join(re.escape(w) for w in words)
        patterns.append(pat)
    joined = "|".join(patterns)
    return re.compile(rf"\b({joined})\b", re.IGNORECASE)


TEAM_REGEX = _build_team_regex()
DATE_REGEX = re.compile(r"(\b\d{2}/\d{2}/\d{4}\b|\b\d{4}-\d{2}-\d{2}\b)")
TIME_REGEX = re.compile(r"(\b\d{1,2}:\d{2}\s*(?:\([A-Za-z]+\))?)")
MATCHUP_REGEX = re.compile(r"(\b[A-Z]{3}@[A-Z]{3}\b)")
STATUS_REGEX = re.compile(r"\b(Available|Probable|Questionable|Doubtful|Out)\b", re.IGNORECASE)
NOT_SUBMITTED_REGEX = re.compile(r"\bNOT\s*YET\s*SUBMITTED\b", re.IGNORECASE)
PAGE_MARKER_REGEX = re.compile(r"Page\s*\d+\s*of\s*\d*", re.IGNORECASE)
PAGE_MARKER_LINE_REGEX = re.compile(r"^\s*Page\s*\d+\s*of\s*\d*\s*$", re.IGNORECASE)
TITLE_REGEX = re.compile(
    r"Injury\s*Report:\s*(\d{1,2})/(\d{1,2})/(\d{2,4})\s+(\d{1,2}):(\d{2})\s*([AP]M)",
    re.IGNORECASE,
)
HEADER_REGEX = re.compile(
    r"Game\s*Date\s+Game\s*Time\s+Matchup\s+Team\s+Player\s*Name\s+(?P<tail>.*\S)",
    re.IGNORECASE,
)
CATEGORY_HEADER_TAIL = re.compile(
    r"^Category\s+Reason\s+Current\s*Status\s+Previous\s*Status$", re.IGNORECASE
)
STATUS_REASON_HEADER_TAIL = re.compile(r"^Current\s*Status\s+Reason$", re.IGNORECASE)
GAME_TIME_REGEX = re.compile(r"^\s*(\d{1,2}):(\d{2})\s*(?:\(\s*ET\s*\))?\s*$", re.IGNORECASE)
CELL_REGEX = re.compile(r"\S+(?: \S+)*")  # cells are separated by 2+ spaces in layout text

_CATEGORY_COLUMNS = (
    "game_date",
    "game_time",
    "matchup",
    "team",
    "player",
    "category",
    "reason",
    "current_status",
    "previous_status",
)
_CATEGORY_HEADER_LABELS = (
    r"Game\s*Date",
    r"Game\s*Time",
    r"Matchup",
    r"Team",
    r"Player\s*Name",
    r"Category",
    r"Reason",
    r"Current\s*Status",
    r"Previous\s*Status",
)
_TEAM_KEYS: Dict[str, str] = {re.sub(r"\s+", "", t).lower(): t for t in NBA_TEAMS}


def canonical_team_name(raw: str) -> str:
    """Maps a (possibly oddly spaced) team cell to its canonical name; unknown text is returned trimmed."""
    key = re.sub(r"\s+", "", raw or "").lower()
    if key in _TEAM_KEYS:
        return _TEAM_KEYS[key]
    return re.sub(r"\s+", " ", raw or "").strip()


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _starts_with_category(text: str) -> bool:
    t = _clean(text).lower()
    return any(t.startswith(p.lower()) for p in REASON_CATEGORY_PREFIXES)


def _is_noise_line(line: str) -> bool:
    s = line.strip()
    if not s or s.startswith("#"):
        return True
    if PAGE_MARKER_LINE_REGEX.match(s) or TITLE_REGEX.search(s):
        return True
    if HEADER_REGEX.search(s):
        return True
    return bool(re.match(r"^(NBA\s+INJURY\s+REPORT|Injury\s*Report:|Report\s+Date:)", s, re.IGNORECASE))


def parse_report_title_time(text: str) -> Optional[datetime]:
    """Returns the 'Injury Report: MM/DD/YY HH:MM AM|PM' publication time (tz-aware Eastern), if present."""
    m = TITLE_REGEX.search(text or "")
    if not m:
        return None
    month, day, year, hour, minute, ampm = m.groups()
    try:
        y = int(year)
        if y < 100:
            y += 2000
        h = int(hour)
        if not 1 <= h <= 12:
            return None
        if ampm.upper() == "PM" and h != 12:
            h += 12
        elif ampm.upper() == "AM" and h == 12:
            h = 0
        return datetime(y, int(month), int(day), h, int(minute), tzinfo=EASTERN_TZ)
    except ValueError:
        return None


def parse_game_tipoff_et(game_date: str, game_time: str) -> Optional[datetime]:
    """
    Converts an entry's ``game_date`` ('MM/DD/YYYY' or 'YYYY-MM-DD') and ``game_time_et``
    ('07:00 (ET)', '01:00  (ET)') into a tz-aware Eastern tip-off datetime.

    The report prints a 12-hour clock without AM/PM. NBA games tip between noon and midnight
    Eastern, so 12:xx is noon and 1:00-11:59 are PM (a '01:00 (ET)' weekend matinee is 13:00).
    Returns ``None`` when either part is missing or malformed (never guessed).
    """
    if not game_date or not game_time:
        return None
    d: Optional[date] = None
    ds = game_date.strip()
    try:
        if re.fullmatch(r"\d{2}/\d{2}/\d{4}", ds):
            d = datetime.strptime(ds, "%m/%d/%Y").date()
        elif re.fullmatch(r"\d{4}-\d{2}-\d{2}", ds):
            d = date.fromisoformat(ds)
    except ValueError:
        return None
    if d is None:
        return None
    m = GAME_TIME_REGEX.match(game_time)
    if not m:
        return None
    hour, minute = int(m.group(1)), int(m.group(2))
    if not 1 <= hour <= 12 or not 0 <= minute <= 59:
        return None
    hour_24 = 12 if hour == 12 else hour + 12
    return datetime.combine(d, time(hour_24, minute), tzinfo=EASTERN_TZ)


def detect_layout(text: str) -> Tuple[InjuryReportLayout, int]:
    """Returns (layout, index of the first header line). Raises InjuryReportLayoutError when unknown."""
    lines = text.splitlines()
    for idx, line in enumerate(lines):
        m = HEADER_REGEX.search(line)
        if not m:
            continue
        tail = _clean(m.group("tail"))
        if CATEGORY_HEADER_TAIL.match(tail):
            return InjuryReportLayout.CATEGORY_COLUMNS, idx
        if STATUS_REASON_HEADER_TAIL.match(tail):
            has_rows_before_header = any(
                STATUS_REGEX.search(l) and not _is_noise_line(l) for l in lines[:idx]
            )
            if has_rows_before_header:
                return InjuryReportLayout.STATUS_REASON_INVERTED, idx
            return InjuryReportLayout.STATUS_REASON_UPRIGHT, idx
        raise InjuryReportLayoutError(f"Unknown injury report column header: {tail!r}")
    raise InjuryReportLayoutError("No injury report column header found")


def _reading_order_lines(text: str, layout: InjuryReportLayout) -> List[str]:
    """Returns lines in visual reading order (inverted pages are reversed page by page)."""
    lines = text.splitlines()
    if layout != InjuryReportLayout.STATUS_REASON_INVERTED:
        return lines
    pages: List[List[str]] = []
    current: List[str] = []
    for line in lines:
        if PAGE_MARKER_LINE_REGEX.match(line) and current:
            pages.append(current)
            current = []
        current.append(line)
    if current:
        pages.append(current)
    ordered: List[str] = []
    for page in pages:
        ordered.extend(reversed(page))
    return ordered


class _Context:
    """Merged-cell state carried across rows and page breaks."""

    def __init__(self) -> None:
        self.game_date = ""
        self.game_time = ""
        self.matchup = ""
        self.team_block: Optional[List[str]] = None  # mutable fragments of the current team cell
        self.games: List[ParsedGame] = []

    def set_game_fields(self, game_date: str, game_time: str, matchup: str) -> None:
        if game_date:
            self.game_date = game_date
        if game_time:
            self.game_time = game_time
        if matchup:
            self.matchup = matchup
        if game_date or game_time or matchup:
            g = ParsedGame(self.game_date, self.game_time, self.matchup)
            if self.matchup and g not in self.games:
                self.games.append(g)

    def new_team(self, team_text: str) -> None:
        self.team_block = [team_text]

    @property
    def team(self) -> str:
        return canonical_team_name(" ".join(self.team_block)) if self.team_block else ""


def _make_row(ctx: _Context, raw_name: str, status_word: str, reason: str) -> Tuple[ParsedInjuryRow, Optional[List[str]]]:
    raw = _clean(raw_name)
    status = status_word.strip().title()
    row = ParsedInjuryRow(
        game_date=ctx.game_date,
        game_time=ctx.game_time,
        matchup=ctx.matchup,
        team=ctx.team,
        player_name=normalize_player_name(raw),
        raw_name=raw,
        status=status,
        reason=_clean(reason),
        availability_prob=STATUS_AVAILABILITY_PROBABILITIES.get(status.upper()),
    )
    return row, ctx.team_block


def _finalize_teams(pairs: List[Tuple[ParsedInjuryRow, Optional[List[str]]]]) -> List[ParsedInjuryRow]:
    """Applies team-cell continuation lines (wrapped team names) to every row of the block."""
    rows = []
    for row, block in pairs:
        if block is not None:
            row.team = canonical_team_name(" ".join(block))
        rows.append(row)
    return rows


def _parse_status_reason(lines: List[str], layout: InjuryReportLayout) -> Tuple[List[ParsedInjuryRow], List[ParsedGame]]:
    inverted = layout == InjuryReportLayout.STATUS_REASON_INVERTED
    ctx = _Context()
    pairs: List[Tuple[ParsedInjuryRow, Optional[List[str]]]] = []
    pending_reason_prefix = ""

    for line in lines:
        if _is_noise_line(line):
            continue
        work = line.strip()

        d_m = DATE_REGEX.search(work)
        t_m = TIME_REGEX.search(work)
        m_m = MATCHUP_REGEX.search(work)
        ctx.set_game_fields(
            d_m.group(1) if d_m else "",
            _clean(t_m.group(1)) if t_m else "",
            m_m.group(1) if m_m else "",
        )
        for m in (d_m, t_m, m_m):
            if m:
                work = work.replace(m.group(0), " ", 1)

        tm_m = TEAM_REGEX.search(work)
        if tm_m:
            ctx.new_team(tm_m.group(1))
            work = work.replace(tm_m.group(0), " ", 1)

        if NOT_SUBMITTED_REGEX.search(work):
            continue

        status_m = STATUS_REGEX.search(work)
        if not status_m:
            text = _clean(work)
            if not text:
                continue
            if not pairs or (inverted and _starts_with_category(text)):
                pending_reason_prefix = _clean(f"{pending_reason_prefix} {text}")
            else:
                last = pairs[-1][0]
                last.reason = _clean(f"{last.reason} {text}")
            continue

        raw_player_name = _clean(work[: status_m.start()])
        if not raw_player_name:
            continue
        inline_reason = work[status_m.end():]
        row, block = _make_row(ctx, raw_player_name, status_m.group(1), f"{pending_reason_prefix} {inline_reason}")
        pending_reason_prefix = ""
        pairs.append((row, block))

    return _finalize_teams(pairs), ctx.games


def _category_column_starts(header_line: str) -> Optional[List[int]]:
    starts: List[int] = []
    pos = 0
    for label in _CATEGORY_HEADER_LABELS:
        m = re.compile(label, re.IGNORECASE).search(header_line, pos)
        if not m:
            return None
        starts.append(m.start())
        pos = m.end()
    return starts


def _cells_by_column(line: str, starts: List[int]) -> Dict[str, str]:
    cells: Dict[str, List[str]] = {}
    for m in CELL_REGEX.finditer(line):
        center_col = min(range(len(starts)), key=lambda i: abs(starts[i] - m.start()))
        cells.setdefault(_CATEGORY_COLUMNS[center_col], []).append(m.group(0))
    return {k: _clean(" ".join(v)) for k, v in cells.items()}


def _parse_category_columns(lines: List[str]) -> Tuple[List[ParsedInjuryRow], List[ParsedGame]]:
    ctx = _Context()
    pairs: List[Tuple[ParsedInjuryRow, Optional[List[str]]]] = []
    starts: Optional[List[int]] = None

    for line in lines:
        if HEADER_REGEX.search(line):
            starts = _category_column_starts(line)
            if starts is None:
                raise InjuryReportLayoutError("Category-column header without all nine columns")
            continue
        if _is_noise_line(line):
            continue
        if starts is None:
            raise InjuryReportLayoutError("Category-column row before any column header")

        if NOT_SUBMITTED_REGEX.search(line):
            head = NOT_SUBMITTED_REGEX.split(line, maxsplit=1)[0]
            cells = _cells_by_column(head, starts)
            ctx.set_game_fields(cells.get("game_date", ""), cells.get("game_time", ""), cells.get("matchup", ""))
            if cells.get("team"):
                ctx.new_team(cells["team"])
            continue

        cells = _cells_by_column(line, starts)
        player = cells.get("player", "")
        status = cells.get("current_status", "")
        ctx.set_game_fields(cells.get("game_date", ""), cells.get("game_time", ""), cells.get("matchup", ""))

        if not player and not status:
            # Continuation line of wrapped cells (team name, reason detail, category).
            if cells.get("team"):
                if ctx.team_block is not None and not TEAM_REGEX.fullmatch(cells["team"]):
                    ctx.team_block.append(cells["team"])
                else:
                    ctx.new_team(cells["team"])
            extra = _clean(" ".join(cells.get(k, "") for k in ("category", "reason")))
            if extra and pairs:
                last = pairs[-1][0]
                last.reason = _clean(f"{last.reason} {extra}")
            continue

        if not player or not STATUS_REGEX.fullmatch(status):
            raise InjuryReportLayoutError(f"Unrecognised category-column row: {_clean(line)!r}")
        if cells.get("team"):
            ctx.new_team(cells["team"])
        category = cells.get("category", "")
        detail = cells.get("reason", "")
        reason = f"{category} - {detail}" if detail and detail != "-" else category
        row, block = _make_row(ctx, player, status, reason)
        pairs.append((row, block))

    return _finalize_teams(pairs), ctx.games


def parse_injury_report(text: str) -> ParsedInjuryReport:
    """
    Parses layout text of an official NBA injury report PDF into rows, the publication time and
    the listed games. Raises ``InjuryReportLayoutError`` for text that matches no known layout.
    """
    layout, _ = detect_layout(text or "")
    lines = _reading_order_lines(text, layout)
    if layout == InjuryReportLayout.CATEGORY_COLUMNS:
        rows, games = _parse_category_columns(lines)
    else:
        rows, games = _parse_status_reason(lines, layout)
    return ParsedInjuryReport(
        layout=layout,
        rows=rows,
        report_time_et=parse_report_title_time(text),
        games=games,
    )


def parse_injury_report_text(text: str) -> List[ParsedInjuryRow]:
    """
    Backwards-compatible wrapper returning only the rows. Empty or header-less text without any
    player status rows yields ``[]``; text with rows but no known layout raises
    ``InjuryReportLayoutError``.
    """
    if not text or not text.strip():
        return []
    try:
        return parse_injury_report(text).rows
    except InjuryReportLayoutError:
        if not any(STATUS_REGEX.search(l) and not _is_noise_line(l) for l in text.splitlines()):
            return []
        raise
