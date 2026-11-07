"""
Historical pre-game lines: read the raw archive files, map teams to ids, match games, reconcile and upsert into
``historical_game_line``.

The parsing maths is pure and lives in ``app.analytics.historical_lines``; this module owns file reading and the
database side. Matching against ``player_game_log`` uses the same game reconstruction as Elo
(``EloRatingService.load_games``): a line matches the game with the same US date and canonical home/away franchise
ids; for neutral-site rows (SBRO ``N``) a swapped home/away also matches. A matched line whose final score differs
from the box-score total is COUNTED in the reconciliation report, never dropped silently.

Merging the two sources (``merge_lines``) prefers SBRO for the seasons it covers when both agree on the close
spread; disagreements are counted and the SBRO row is still the one used (it is the only one with opening lines).
"""
import csv
import logging
import os
from collections import Counter, defaultdict
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel import Session

from app.analytics import historical_lines as hl
from app.models import Game, HistoricalGameLine, Season, Team
from app.services.elo_service import CURRENT_TEAMS, EloRatingService, HistoricalGame

logger = logging.getLogger(__name__)

_INSERT_CHUNK = 1000
UPDATABLE_COLUMNS = (
    "source_row_key",
    "season_label",
    "neutral_site",
    "game_id",
    "nba_game_id",
    "open_spread_home",
    "close_spread_home",
    "open_total",
    "close_total",
    "open_moneyline_home",
    "open_moneyline_away",
    "close_moneyline_home",
    "close_moneyline_away",
    "home_score",
    "away_score",
)


# ------------------------------------------------------------------------------------------------ files

def read_sbro_dir(sbro_dir: Path) -> Tuple[List[hl.ParsedLine], hl.ParseReport]:
    """Every ``nba-odds-YYYY-YY.html`` page in the directory (other files are ignored)."""
    lines: List[hl.ParsedLine] = []
    report = hl.ParseReport()
    for path in sorted(Path(sbro_dir).glob("nba-odds-*.htm*")):
        season = hl.season_label_from_sbro_name(path.name)
        if season is None:
            continue
        parsed, file_report = hl.parse_sbro_html(path.read_text(encoding="utf-8", errors="replace"), season, path.name)
        lines.extend(parsed)
        report.merge(file_report)
    return lines, report


def read_kaggle_csv(path: Path) -> Tuple[List[hl.ParsedLine], hl.ParseReport]:
    with open(path, newline="", encoding="utf-8") as handle:
        return hl.parse_kaggle_rows(csv.DictReader(handle), Path(path).name)


def read_sources(sbro_dir: Optional[Path], kaggle_csv: Optional[Path]) -> Tuple[List[hl.ParsedLine], Dict[str, hl.ParseReport]]:
    lines: List[hl.ParsedLine] = []
    reports: Dict[str, hl.ParseReport] = {}
    if sbro_dir is not None and Path(sbro_dir).is_dir():
        parsed, reports[hl.SOURCE_SBRO] = read_sbro_dir(Path(sbro_dir))
        lines.extend(parsed)
    if kaggle_csv is not None and Path(kaggle_csv).is_file():
        parsed, reports[hl.SOURCE_KAGGLE] = read_kaggle_csv(Path(kaggle_csv))
        lines.extend(parsed)
    return lines, reports


def default_data_dir() -> Path:
    return Path(os.environ.get("ARCHETYPE_DATA_DIR", str(Path.home() / "ArchetypeNBA-data")))


# ------------------------------------------------------------------------------------------------ teams

def canonical_team_ids(session: Session) -> Dict[str, int]:
    """Current franchise abbreviation -> team id (only the 30 current NBA teams)."""
    rows = session.execute(select(Team.id, Team.abbreviation)).all()
    return {abbr: team_id for team_id, abbr in rows if abbr in CURRENT_TEAMS}


@dataclass(frozen=True)
class ResolvedLine:
    """A parsed line with team ids and, when matched, the player_game_log game."""

    line: hl.ParsedLine
    home_team_id: int
    away_team_id: int
    nba_game_id: Optional[str] = None
    swapped: bool = False  # neutral-site row matched with home/away swapped (lines flipped to the log's home side)
    score_mismatch: bool = False
    date_shift: int = 0  # days between the source date and the matched game (only +-1, only with an equal score)

    @property
    def key(self) -> Tuple[str, date, int, int]:
        return (self.line.source, self.line.game_date, self.home_team_id, self.away_team_id)


def resolve_teams(lines: Iterable[hl.ParsedLine], team_ids: Dict[str, int]) -> Tuple[List[ResolvedLine], Counter]:
    """Lines whose two teams map to ids; the rest are counted by raw team name."""
    resolved: List[ResolvedLine] = []
    unmatched: Counter = Counter()
    for line in lines:
        home = team_ids.get(line.home_abbr or "")
        away = team_ids.get(line.away_abbr or "")
        if home is None or away is None or home == away:
            for raw, team_id in ((line.home_name_raw, home), (line.away_name_raw, away)):
                if team_id is None:
                    unmatched[f"{line.source}:{raw}"] += 1
            continue
        resolved.append(ResolvedLine(line, home, away))
    return resolved, unmatched


def _flip(line: hl.ParsedLine) -> hl.ParsedLine:
    """The same game seen from the other team as home (used only for neutral-site rows)."""
    neg = lambda v: None if v is None else -v  # noqa: E731
    return replace(
        line,
        home_abbr=line.away_abbr,
        away_abbr=line.home_abbr,
        home_name_raw=line.away_name_raw,
        away_name_raw=line.home_name_raw,
        open_spread_home=neg(line.open_spread_home),
        close_spread_home=neg(line.close_spread_home),
        open_moneyline_home=line.open_moneyline_away,
        open_moneyline_away=line.open_moneyline_home,
        close_moneyline_home=line.close_moneyline_away,
        close_moneyline_away=line.close_moneyline_home,
        home_score=line.away_score,
        away_score=line.home_score,
    )


def match_games(resolved: Sequence[ResolvedLine], games: Sequence[HistoricalGame]) -> List[ResolvedLine]:
    """
    Attach ``nba_game_id`` by (date, home id, away id); neutral-site rows may match with the teams swapped. A line
    with no game on its date matches a game of the same teams one day earlier or later ONLY when the final score is
    identical (the archives have a few off-by-one dates, e.g. Christmas games listed on 24 December); such matches
    are counted as ``date_shift``.
    """
    index = {(g.game_date, g.home_team_id, g.away_team_id): g for g in games}
    out: List[ResolvedLine] = []
    for item in resolved:
        line = item.line
        game = index.get((line.game_date, item.home_team_id, item.away_team_id))
        swapped, shift = False, 0
        if game is None and line.neutral_site:
            game = index.get((line.game_date, item.away_team_id, item.home_team_id))
            swapped = game is not None
        if game is None and line.home_score is not None and line.away_score is not None:
            for days in (-1, 1):
                candidate = index.get((line.game_date + timedelta(days=days), item.home_team_id, item.away_team_id))
                if candidate is not None and (candidate.home_pts, candidate.away_pts) == (line.home_score, line.away_score):
                    game, shift = candidate, days
                    break
        if game is None:
            out.append(item)
            continue
        if swapped:
            line = _flip(line)
            item = ResolvedLine(line, item.away_team_id, item.home_team_id, swapped=True)
        mismatch = (
            line.home_score is not None
            and line.away_score is not None
            and (line.home_score, line.away_score) != (game.home_pts, game.away_pts)
        )
        out.append(replace(item, nba_game_id=game.game_id, score_mismatch=mismatch, date_shift=shift))
    return out


# ------------------------------------------------------------------------------------------------ merge

@dataclass
class CrossSourceReport:
    both: int = 0
    agree_close_spread: int = 0
    disagree_close_spread: int = 0
    agree_close_total: int = 0
    disagree_close_total: int = 0
    agree_moneyline: int = 0
    disagree_moneyline: int = 0
    disagree_score: int = 0
    examples: List[str] = field(default_factory=list)


def _same(a, b) -> Optional[bool]:
    if a is None or b is None:
        return None
    return float(a) == float(b)


def merge_lines(resolved: Sequence[ResolvedLine], prefer: str = hl.SOURCE_SBRO) -> Tuple[Dict[Tuple[date, int, int], ResolvedLine], CrossSourceReport]:
    """
    One line per game (date, home id, away id): the ``prefer`` source when present, otherwise the other one.
    Every pair seen in both sources is compared field by field and disagreements are counted.
    """
    by_game: Dict[Tuple[date, int, int], Dict[str, ResolvedLine]] = defaultdict(dict)
    for item in resolved:
        by_game[(item.line.game_date, item.home_team_id, item.away_team_id)][item.line.source] = item
    report = CrossSourceReport()
    merged: Dict[Tuple[date, int, int], ResolvedLine] = {}
    for key, sources in by_game.items():
        if len(sources) > 1 and prefer in sources:
            report.both += 1
            chosen = sources[prefer]
            other = next(v for s, v in sources.items() if s != prefer)
            for attr, ok_name, bad_name in (
                ("close_spread_home", "agree_close_spread", "disagree_close_spread"),
                ("close_total", "agree_close_total", "disagree_close_total"),
                ("close_moneyline_home", "agree_moneyline", "disagree_moneyline"),
            ):
                same = _same(getattr(chosen.line, attr), getattr(other.line, attr))
                if same is True:
                    setattr(report, ok_name, getattr(report, ok_name) + 1)
                elif same is False:
                    setattr(report, bad_name, getattr(report, bad_name) + 1)
                    if len(report.examples) < 10:
                        report.examples.append(
                            f"{key[0]} {chosen.line.away_name_raw}@{chosen.line.home_name_raw} {attr}: "
                            f"{prefer}={getattr(chosen.line, attr)} other={getattr(other.line, attr)}"
                        )
            if (chosen.line.home_score, chosen.line.away_score) != (other.line.home_score, other.line.away_score):
                report.disagree_score += 1
            merged[key] = chosen
        else:
            merged[key] = sources.get(prefer) or next(iter(sources.values()))
    return merged, report


# ------------------------------------------------------------------------------------------------ reconciliation

@dataclass
class ImportReport:
    parse: Dict[str, hl.ParseReport] = field(default_factory=dict)
    rows_by_season: Dict[Tuple[str, str], int] = field(default_factory=dict)  # (source, season) -> rows
    unmatched_teams: Counter = field(default_factory=Counter)
    matched_to_log: Counter = field(default_factory=Counter)  # source -> lines matched to a player_game_log game
    unmatched_to_log: Counter = field(default_factory=Counter)
    unmatched_examples: List[str] = field(default_factory=list)
    neutral_swapped: int = 0
    date_shifted: int = 0
    score_mismatch: Counter = field(default_factory=Counter)  # source -> matched lines with a different final score
    score_mismatch_examples: List[str] = field(default_factory=list)
    duplicate_keys: Counter = field(default_factory=Counter)  # source -> rows sharing (date, home, away) in one source
    cross_source: Optional[CrossSourceReport] = None
    linked_game_rows: int = 0
    rows_to_write: int = 0
    rows_written: int = 0
    dry_run: bool = True

    def format(self) -> str:
        out = ["# Historical lines import" + (" (dry run: nothing written)" if self.dry_run else ""), ""]
        for source, rep in sorted(self.parse.items()):
            out.append(
                f"- parse {source}: {rep.rows} table rows -> {rep.games} games; unpaired rows {rep.unpaired_rows}, "
                f"bad dates {rep.bad_dates}, dates out of order {rep.dates_out_of_order}, NL/empty line cells "
                f"{rep.no_line_cells}, unparseable line cells {rep.bad_cells}, ambiguous open/close columns "
                f"{rep.ambiguous_columns}, unparseable moneylines {rep.bad_moneylines}, unknown team names "
                f"{dict(rep.unknown_teams) or 0}"
            )
        out += ["", "| source | season | rows |", "|---|---|---|"]
        for (source, season), n in sorted(self.rows_by_season.items(), key=lambda kv: (kv[0][1], kv[0][0])):
            out.append(f"| {source} | {season} | {n} |")
        out.append("")
        out.append(f"- unmatched teams: {dict(self.unmatched_teams) or 'none'}")
        for source in sorted(set(self.matched_to_log) | set(self.unmatched_to_log)):
            out.append(
                f"- {source}: matched to a player_game_log game {self.matched_to_log[source]}, not matched "
                f"{self.unmatched_to_log[source]}, final score differs from the box score {self.score_mismatch[source]}, "
                f"duplicate (date, home, away) keys {self.duplicate_keys[source]}"
            )
        out.append(f"- neutral-site rows matched with home/away swapped: {self.neutral_swapped}")
        out.append(f"- rows matched one day off their source date (identical final score): {self.date_shifted}")
        if self.unmatched_examples:
            out.append("- examples not matched: " + "; ".join(self.unmatched_examples))
        if self.score_mismatch_examples:
            out.append("- examples of score disagreements: " + "; ".join(self.score_mismatch_examples))
        if self.cross_source is not None:
            c = self.cross_source
            out.append(
                f"- games in both sources: {c.both}; close spread agree {c.agree_close_spread} / disagree "
                f"{c.disagree_close_spread}; close total agree {c.agree_close_total} / disagree {c.disagree_close_total}; "
                f"close moneyline agree {c.agree_moneyline} / disagree {c.disagree_moneyline}; final score disagree "
                f"{c.disagree_score} (SBRO preferred)"
            )
            if c.examples:
                out.append("- disagreement examples: " + "; ".join(c.examples))
        out.append(f"- rows linked to a quant `game` row: {self.linked_game_rows}")
        out.append(f"- rows to upsert: {self.rows_to_write}; written: {self.rows_written}")
        return "\n".join(out)


def _decimal(value: Optional[float]) -> Optional[Decimal]:
    return None if value is None else Decimal(str(value))


def row_dict(item: ResolvedLine, game_pk: Optional[int]) -> dict:
    line = item.line
    return {
        "source": line.source,
        "source_row_key": line.source_row_key,
        "season_label": line.season_label,
        "game_date": line.game_date,
        "home_team_id": item.home_team_id,
        "away_team_id": item.away_team_id,
        "neutral_site": line.neutral_site,
        "game_id": game_pk,
        "nba_game_id": item.nba_game_id,
        "open_spread_home": _decimal(line.open_spread_home),
        "close_spread_home": _decimal(line.close_spread_home),
        "open_total": _decimal(line.open_total),
        "close_total": _decimal(line.close_total),
        "open_moneyline_home": line.open_moneyline_home,
        "open_moneyline_away": line.open_moneyline_away,
        "close_moneyline_home": line.close_moneyline_home,
        "close_moneyline_away": line.close_moneyline_away,
        "home_score": line.home_score,
        "away_score": line.away_score,
    }


def upsert_rows(session: Session, rows: List[dict]) -> int:
    """Idempotent insert-or-update on (source, game_date, home_team_id, away_team_id)."""
    if not rows:
        return 0
    dialect = session.get_bind().dialect.name
    make_insert = {"postgresql": pg_insert, "sqlite": sqlite_insert}.get(dialect)
    if make_insert is None:
        raise NotImplementedError(f"historical line upsert is not implemented for dialect {dialect!r}")
    table = HistoricalGameLine.__table__
    for start in range(0, len(rows), _INSERT_CHUNK):
        stmt = make_insert(table).values(rows[start : start + _INSERT_CHUNK])
        stmt = stmt.on_conflict_do_update(
            index_elements=["source", "game_date", "home_team_id", "away_team_id"],
            set_={col: getattr(stmt.excluded, col) for col in UPDATABLE_COLUMNS},
        )
        session.execute(stmt)
    return len(rows)


def set_read_only(session: Session) -> None:
    """Make the session's transaction read-only on PostgreSQL (a guard for dry runs and the backtest)."""
    if session.get_bind().dialect.name == "postgresql":
        session.execute(text("SET TRANSACTION READ ONLY"))


def prepare(
    session: Session, lines: Sequence[hl.ParsedLine], reports: Dict[str, hl.ParseReport]
) -> Tuple[List[ResolvedLine], ImportReport, List[HistoricalGame]]:
    """Resolve teams, match player_game_log games and build the reconciliation report (reads only)."""
    report = ImportReport(parse=dict(reports))
    team_ids = canonical_team_ids(session)
    resolved, report.unmatched_teams = resolve_teams(lines, team_ids)
    games = EloRatingService(session).load_games()
    matched = match_games(resolved, games)

    per_source_keys: Dict[str, Counter] = defaultdict(Counter)
    for item in matched:
        source = item.line.source
        report.rows_by_season[(source, item.line.season_label)] = report.rows_by_season.get((source, item.line.season_label), 0) + 1
        per_source_keys[source][item.key] += 1
        if item.nba_game_id is None:
            report.unmatched_to_log[source] += 1
            if len(report.unmatched_examples) < 8:
                report.unmatched_examples.append(f"{source} {item.line.game_date} {item.line.away_name_raw}@{item.line.home_name_raw}")
        else:
            report.matched_to_log[source] += 1
            report.neutral_swapped += int(item.swapped)
            report.date_shifted += int(item.date_shift != 0)
            if item.score_mismatch:
                report.score_mismatch[source] += 1
                if len(report.score_mismatch_examples) < 8:
                    report.score_mismatch_examples.append(
                        f"{source} {item.line.game_date} {item.line.away_name_raw}@{item.line.home_name_raw} "
                        f"{item.line.away_score}-{item.line.home_score} vs log game {item.nba_game_id}"
                    )
    for source, keys in per_source_keys.items():
        report.duplicate_keys[source] = sum(n - 1 for n in keys.values() if n > 1)
    _, report.cross_source = merge_lines(matched)
    return matched, report, games


def import_lines(session: Session, lines: Sequence[hl.ParsedLine], reports: Dict[str, hl.ParseReport], dry_run: bool = True) -> ImportReport:
    """Reconcile and, unless ``dry_run``, upsert every resolved line (the caller commits)."""
    if dry_run:
        set_read_only(session)
    matched, report, _ = prepare(session, lines, reports)
    report.dry_run = dry_run
    nba_to_game = {
        nba_id: pk for pk, nba_id in session.execute(select(Game.id, Game.nba_game_id).where(Game.nba_game_id.is_not(None))).all()
    }
    # one row per unique key: the last parsed row wins inside a source (duplicates are counted above)
    unique: Dict[Tuple[str, date, int, int], dict] = {}
    for item in matched:
        game_pk = nba_to_game.get(item.nba_game_id) if item.nba_game_id else None
        unique[item.key] = row_dict(item, game_pk)
    rows = list(unique.values())
    report.linked_game_rows = sum(1 for r in rows if r["game_id"] is not None)
    report.rows_to_write = len(rows)
    if not dry_run:
        report.rows_written = upsert_rows(session, rows)
    return report


def season_labels(session: Session) -> Dict[int, str]:
    return {sid: label for sid, label in session.execute(select(Season.id, Season.season_label)).all()}
