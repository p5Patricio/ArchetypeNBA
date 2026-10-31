import re
from typing import List, Optional
from pydantic import BaseModel

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
PAGE_MARKER_REGEX = re.compile(r"Page\s*\d+\s*of\s*\d+", re.IGNORECASE)


def _split_into_page_chunks(text: str) -> List[List[str]]:
    """Splits full text into chunks representing individual PDF pages."""
    lines = text.splitlines()
    if not lines:
        return []

    pages: List[List[str]] = []
    current_page: List[str] = []

    for line in lines:
        if PAGE_MARKER_REGEX.search(line):
            if current_page:
                pages.append(current_page)
                current_page = []
        current_page.append(line)

    if current_page:
        pages.append(current_page)

    return pages


def _is_page_inverted(page_lines: List[str]) -> bool:
    """
    Checks if page lines were extracted from top-of-page to bottom-of-page
    in a PDF table rendered bottom-to-top (i.e. header/start is at the bottom).
    """
    non_empty = [l.strip() for l in page_lines if l.strip()]
    if not non_empty:
        return False

    # In inverted layout mode:
    # 1. 'Page X of Y' is at index 0 (top of page).
    # 2. 'Injury Report:' or 'Game Date Game Time' header is near the bottom.
    top_has_page_marker = bool(PAGE_MARKER_REGEX.search(non_empty[0]))
    bottom_has_header = any(
        "Game Date" in l or "Injury Report" in l for l in non_empty[-3:]
    )

    return top_has_page_marker or bottom_has_header


def parse_injury_report_text(text: str) -> List[ParsedInjuryRow]:
    """
    Parses raw layout text extracted from official NBA Injury Report PDFs into structured ParsedInjuryRow objects.
    Restores correct reading order across inverted pages, carries forward blank cells (date, time, matchup, team)
    across consecutive rows and page breaks, combines multi-line wrapped reasons, and handles NOT YET SUBMITTED rows.
    """
    if not text:
        return []

    # 1. Split into pages and restore chronological reading order
    page_chunks = _split_into_page_chunks(text)
    ordered_lines: List[str] = []

    if page_chunks:
        for chunk in page_chunks:
            if _is_page_inverted(chunk):
                ordered_lines.extend(reversed(chunk))
            else:
                ordered_lines.extend(chunk)
    else:
        ordered_lines = text.splitlines()

    rows: List[ParsedInjuryRow] = []

    current_date = ""
    current_time = ""
    current_matchup = ""
    current_team = ""
    pending_reason_prefix = ""

    for line in ordered_lines:
        line_clean = line.strip()
        if not line_clean:
            continue

        # Ignore standard header / footer / comment lines
        if line_clean.startswith("#") or any(
            re.search(p, line_clean, re.IGNORECASE)
            for p in [
                r"^Injury\s+Report:",
                r"^Game\s+Date\s+Game\s+Time",
                r"^Page\s*\d+\s*of\s*\d+",
                r"^NBA\s+INJURY\s+REPORT",
            ]
        ):
            continue

        # Extract headers if present on this line
        d_m = DATE_REGEX.search(line_clean)
        if d_m:
            current_date = d_m.group(1)

        t_m = TIME_REGEX.search(line_clean)
        if t_m:
            current_time = t_m.group(1).strip()

        m_m = MATCHUP_REGEX.search(line_clean)
        if m_m:
            current_matchup = m_m.group(1)

        tm_m = TEAM_REGEX.search(line_clean)
        if tm_m:
            matched_clean = re.sub(r"\s+", " ", tm_m.group(1)).strip().lower()
            for canon in NBA_TEAMS:
                if canon.lower() == matched_clean:
                    current_team = canon
                    break
            else:
                current_team = tm_m.group(1).strip()

        # Check for team submission status: "NOT YET SUBMITTED"
        if NOT_SUBMITTED_REGEX.search(line_clean):
            # Team / matchup updated, no player row created
            continue

        status_m = STATUS_REGEX.search(line_clean)
        if not status_m:
            # Line without status: check if reason prefix for upcoming player or suffix for previous player
            if (
                line_clean.startswith("Injury/Illness")
                or line_clean.startswith("G League")
                or line_clean.startswith("Personal")
                or line_clean.startswith("Rest")
                or not rows
            ):
                pending_reason_prefix = re.sub(
                    r"\s+", " ", f"{pending_reason_prefix} {line_clean}"
                ).strip()
            else:
                rows[-1].reason = re.sub(
                    r"\s+", " ", f"{rows[-1].reason} {line_clean}"
                ).strip()
            continue

        # This line contains a player status entry
        status_word = status_m.group(1).title()  # e.g. "Available", "Questionable", "Out"
        prefix = line_clean[: status_m.start()].strip()
        inline_reason = line_clean[status_m.end() :].strip()

        # Remove Date, Time, Matchup, Team from prefix if present
        if d_m:
            prefix = prefix.replace(d_m.group(0), "").strip()
        if t_m:
            prefix = prefix.replace(t_m.group(0), "").strip()
        if m_m:
            prefix = prefix.replace(m_m.group(0), "").strip()
        if tm_m:
            prefix = prefix.replace(tm_m.group(0), "").strip()

        raw_player_name = re.sub(r"\s+", " ", prefix).strip()
        if not raw_player_name:
            continue

        player_name = normalize_player_name(raw_player_name)
        full_reason = re.sub(
            r"\s+", " ", f"{pending_reason_prefix} {inline_reason}"
        ).strip()
        pending_reason_prefix = ""

        status_upper = status_word.upper()
        prob = STATUS_AVAILABILITY_PROBABILITIES.get(status_upper)

        row = ParsedInjuryRow(
            game_date=current_date,
            game_time=current_time,
            matchup=current_matchup,
            team=current_team,
            player_name=player_name,
            raw_name=raw_player_name,
            status=status_word,
            reason=full_reason,
            availability_prob=prob,
        )
        rows.append(row)

    return rows
