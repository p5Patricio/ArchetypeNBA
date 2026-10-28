import re
from typing import List, Optional
from pydantic import BaseModel, Field

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
    Normalizes 'Last, First' (or 'Last, First Middle') to 'First Last'.
    If no comma is found, returns trimmed string.
    """
    if not raw_name:
        return ""
    if "," in raw_name:
        parts = [p.strip() for p in raw_name.split(",", 1)]
        if len(parts) == 2 and parts[1]:
            return f"{parts[1]} {parts[0]}".strip()
    return raw_name.strip()


def parse_injury_report_text(text: str) -> List[ParsedInjuryRow]:
    """
    Parses raw text extracted from an official NBA Injury Report PDF into structured ParsedInjuryRow objects.
    Tolerates repeated/omitted cells (date, time, matchup, team) across consecutive rows and multi-line wrapped reasons.
    """
    if not text:
        return []

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return []

    rows: List[ParsedInjuryRow] = []

    current_date = ""
    current_time = ""
    current_matchup = ""
    current_team = ""

    # Patterns
    date_regex = re.compile(r"(\b\d{2}/\d{2}/\d{4}\b|\b\d{4}-\d{2}-\d{2}\b)")
    time_regex = re.compile(r"(\b\d{1,2}:\d{2}(?:\s*(?:\([A-Za-z]+\)|[A-Za-z]{2,3}))?)")
    matchup_regex = re.compile(r"(\b[A-Z]{3}@[A-Z]{3}\b)")
    status_regex = re.compile(r"\b(Available|Probable|Questionable|Doubtful|Out)\b", re.IGNORECASE)

    # Team regex matching any known NBA team name sorted by length descending
    teams_sorted = sorted(NBA_TEAMS, key=len, reverse=True)
    teams_pattern = "|".join(re.escape(t) for t in teams_sorted)
    team_regex = re.compile(rf"\b({teams_pattern})\b", re.IGNORECASE)

    # Header patterns to ignore completely
    ignore_patterns = [
        re.compile(r"^NBA INJURY REPORT", re.IGNORECASE),
        re.compile(r"^Report Date:", re.IGNORECASE),
        re.compile(r"^Game Date\s+Game Time", re.IGNORECASE),
        re.compile(r"^Page\s+\d+\s+of\s+\d+", re.IGNORECASE),
        re.compile(r"^NOT (?:YET )?SUBMITTED", re.IGNORECASE),
    ]

    for line in lines:
        # Check if line is an ignored header/disclaimer
        if any(p.search(line) for p in ignore_patterns):
            continue

        status_match = status_regex.search(line)
        if not status_match:
            # If no status found on this line, check if it's a wrapped reason continuation for the previous row
            if rows and not team_regex.search(line) and not matchup_regex.search(line):
                rows[-1].reason = f"{rows[-1].reason} {line}".strip()
            continue

        # This line contains a player status entry
        status_word = status_match.group(1).title()  # e.g. "Available", "Questionable"
        status_start = status_match.start()
        status_end = status_match.end()

        prefix = line[:status_start].strip()
        reason = line[status_end:].strip()

        # Check prefix for Date, Time, Matchup, Team
        d_match = date_regex.search(prefix)
        if d_match:
            current_date = d_match.group(1)
            prefix = prefix[:d_match.start()] + prefix[d_match.end():]

        t_match = time_regex.search(prefix)
        if t_match:
            current_time = t_match.group(1)
            prefix = prefix[:t_match.start()] + prefix[t_match.end():]

        m_match = matchup_regex.search(prefix)
        if m_match:
            current_matchup = m_match.group(1)
            prefix = prefix[:m_match.start()] + prefix[m_match.end():]

        tm_match = team_regex.search(prefix)
        if tm_match:
            # Match the canonical team name
            matched_name = tm_match.group(1)
            for canon in NBA_TEAMS:
                if canon.lower() == matched_name.lower():
                    current_team = canon
                    break
            else:
                current_team = matched_name
            prefix = prefix[:tm_match.start()] + prefix[tm_match.end():]

        # The remainder of prefix is the player name (e.g. "Brown, Jaylen")
        raw_player_name = re.sub(r"\s+", " ", prefix).strip()
        if not raw_player_name:
            continue

        player_name = normalize_player_name(raw_player_name)
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
            reason=reason,
            availability_prob=prob,
        )
        rows.append(row)

    return rows
