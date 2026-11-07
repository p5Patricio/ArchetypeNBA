from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
import hashlib
import io
import logging
import re
import time as time_module
from typing import Callable, Dict, List, Optional, Sequence, Set, Tuple
from zoneinfo import ZoneInfo
from decimal import Decimal

import httpx
from sqlmodel import Session, select

from app.analytics.props_engine import normalize_player_key, strip_player_suffix
from app.config import settings
from app.models import Game, InjuryEntry, InjuryReportSnapshot, Player, PlayerGameLog, PlayerSeasonStats, Season, Team
from app.services.injury_report_parser import (
    InjuryReportLayoutError,
    ParsedInjuryReport,
    ParsedInjuryRow,
    parse_game_tipoff_et,
    parse_injury_report,
    parse_injury_report_text,
)

logger = logging.getLogger(__name__)

EASTERN_TZ = ZoneInfo("America/New_York")
NBA_PDF_BASE_URL = "https://ak-static.cms.nba.com/referee/injury"
ARCHIVE_START_DATE = date(2018, 12, 17)
DEFAULT_SLOT_1_ET = time(17, 0)   # the report labelled 5:00 PM ET
DEFAULT_SLOT_2_ET = time(19, 30)  # 7:30 PM ET (when tip times are unknown)
DEFAULT_SLOT_3_ET = time(13, 0)   # 1:00 PM ET (when --per-day >= 3)
PRE_TIP_MARGIN = timedelta(minutes=60)
# File naming eras, verified against the archive on 2026-11-06: hourly names
# (``Injury-Report_YYYY-MM-DD_05PM.pdf``) through 2025-12-21, quarter-hour names
# (``..._05_00PM.pdf``) from 2025-12-22. An hourly file labelled HH holds the report
# published at HH:30 (its PDF title says so), so its publication time is label + 30 min.
QUARTER_HOUR_NAMING_START = date(2025, 12, 22)
HOURLY_PUBLICATION_OFFSET = timedelta(minutes=30)
NAMING_BOUNDARY_SLACK_DAYS = 2
MAX_GUESSED_CANDIDATES = 3
SEASON_INDEX_URL_TEMPLATE = "https://official.nba.com/nba-injury-report-{season}-season/"
DEFAULT_BACKFILL_DELAY_SECONDS = 4.0
MIN_BACKFILL_DELAY_SECONDS = 2.0
DEFAULT_MAX_REQUESTS = 300
PROGRESS_LOG_INTERVAL = 25


def parse_pdf_filename_timestamp(url: str) -> Optional[datetime]:
    """
    Extracts timestamp from NBA PDF naming patterns:
      - 15-minute variant: Injury-Report_2026-10-28_05_00PM.pdf
      - 2018-2022 hourly variant: Injury-Report_2018-12-17_05PM.pdf
    Converts Eastern time to UTC tz-aware datetime.
    """
    m = re.search(
        r"Injury-Report_(\d{4}-\d{2}-\d{2})_(\d{1,2})(?:_(\d{2}))?([AP]M)(?=\.pdf|$)",
        url,
        re.IGNORECASE,
    )
    if not m:
        return None
    date_str, hour_str, min_str, ampm_str = m.groups()
    try:
        hour = int(hour_str)
        minute = int(min_str) if min_str is not None else 0
        if hour < 1 or hour > 12 or minute < 0 or minute > 59:
            return None
        ampm = ampm_str.upper()
        if ampm == "PM" and hour != 12:
            hour += 12
        elif ampm == "AM" and hour == 12:
            hour = 0
        year, month, day = [int(p) for p in date_str.split("-")]
        dt_eastern = datetime(year, month, day, hour, minute, tzinfo=EASTERN_TZ)
        return dt_eastern.astimezone(timezone.utc)
    except Exception as e:
        logger.warning("Could not parse PDF timestamp from url '%s': %s", url, e)
        return None


def build_injury_pdf_url(
    report_date: date,
    report_time: time,
    *,
    hourly: bool = False,
    base_url: str = NBA_PDF_BASE_URL,
) -> str:
    """
    Builds an official NBA injury report PDF URL for ``report_date`` and ``report_time`` (Eastern Time).
    - ``hourly=False``: ``.../Injury-Report_YYYY-MM-DD_HH_MMAM|PM.pdf`` (current 15-minute naming)
    - ``hourly=True``:  ``.../Injury-Report_YYYY-MM-DD_HHAM|PM.pdf`` (2018-2022 hourly naming)
    """
    hour_24 = report_time.hour
    minute = report_time.minute
    if hour_24 == 0:
        hour_12, ampm = 12, "AM"
    elif hour_24 < 12:
        hour_12, ampm = hour_24, "AM"
    elif hour_24 == 12:
        hour_12, ampm = 12, "PM"
    else:
        hour_12, ampm = hour_24 - 12, "PM"

    prefix = f"{base_url.rstrip('/')}/Injury-Report_{report_date.isoformat()}_{hour_12:02d}"
    if hourly:
        return f"{prefix}{ampm}.pdf"
    return f"{prefix}_{minute:02d}{ampm}.pdf"


def is_hourly_pdf_url(url: str) -> bool:
    """True for the hourly naming variant (``..._05PM.pdf``), False for ``..._05_00PM.pdf``."""
    return bool(re.search(r"Injury-Report_\d{4}-\d{2}-\d{2}_\d{1,2}[AP]M\.pdf", url, re.IGNORECASE))


def report_publication_time_from_url(url: str) -> Optional[datetime]:
    """
    Publication time (UTC) implied by a report file name: the label for quarter-hour names,
    label + 30 minutes for hourly names (an ``_05PM`` file is the 5:30 PM report).
    Use the PDF title (``parse_report_title_time``) when the content is available.
    """
    ts = parse_pdf_filename_timestamp(url)
    if ts is None:
        return None
    return ts + HOURLY_PUBLICATION_OFFSET if is_hourly_pdf_url(url) else ts


def naming_is_hourly(report_date: date) -> bool:
    """Preferred file naming variant for ``report_date`` (see ``QUARTER_HOUR_NAMING_START``)."""
    return report_date < QUARTER_HOUR_NAMING_START


def build_candidate_pdf_urls(
    report_date: date,
    cutoff_time_et: time,
    *,
    by_publication: bool = False,
    base_url: str = NBA_PDF_BASE_URL,
    max_candidates: int = MAX_GUESSED_CANDIDATES,
) -> List[str]:
    """
    Guessed PDF URLs for the latest report on ``report_date`` at or before ``cutoff_time_et``,
    newest first, used only when no index page lists the real files for that date.

    Only the naming variant of the date's era is guessed (hourly before
    ``QUARTER_HOUR_NAMING_START``, quarter-hour from it), stepping back one label at a time
    (hours or quarter hours) for at most ``max_candidates`` guesses; within
    ``NAMING_BOUNDARY_SLACK_DAYS`` of the switch the other variant's newest label is appended.

    ``by_publication=False`` compares the file label with the cutoff (the "5:00 PM report" is
    ``_05PM`` / ``_05_00PM``); ``by_publication=True`` compares the real publication time
    (label + 30 min for hourly names), which is what pre-tip slots need to stay leak-free.
    """
    def labels(hourly: bool) -> List[time]:
        step = 60 if hourly else 15
        offset = HOURLY_PUBLICATION_OFFSET if (hourly and by_publication) else timedelta(0)
        limit = datetime.combine(report_date, cutoff_time_et, tzinfo=EASTERN_TZ) - offset
        minute = (limit.minute // step) * step if step == 15 else 0
        cur = limit.replace(minute=minute, second=0, microsecond=0)
        out: List[time] = []
        while cur.date() == report_date and len(out) < max(1, max_candidates):
            out.append(cur.time())
            cur -= timedelta(minutes=step)
        return out

    hourly = naming_is_hourly(report_date)
    urls = [
        build_injury_pdf_url(report_date, t, hourly=hourly, base_url=base_url) for t in labels(hourly)
    ]
    if abs((report_date - QUARTER_HOUR_NAMING_START).days) <= NAMING_BOUNDARY_SLACK_DAYS:
        other = labels(not hourly)
        if other:
            alt = build_injury_pdf_url(report_date, other[0], hourly=not hourly, base_url=base_url)
            if alt not in urls:
                urls.append(alt)
    return urls


def season_label_for_date(d: date) -> str:
    """NBA season label ('2019-20') of a game date; the 2020 bubble (Jul-Oct 2020) belongs to 2019-20."""
    if d.year == 2020 and d.month <= 11:
        start = 2019
    else:
        start = d.year if d.month >= 10 else d.year - 1
    return f"{start}-{(start + 1) % 100:02d}"


def season_index_page_url(season_label: str) -> str:
    return SEASON_INDEX_URL_TEMPLATE.format(season=season_label)


def index_page_season(html: str) -> Optional[str]:
    """Season label the page really serves (canonical link or title); old season URLs redirect to the current page."""
    m = re.search(r'rel=["\']canonical["\'][^>]*href=["\'][^"\']*nba-injury-report-(\d{4}-\d{2})-season', html, re.I)
    if not m:
        m = re.search(r'href=["\'][^"\']*nba-injury-report-(\d{4}-\d{2})-season[^"\']*["\'][^>]*rel=["\']canonical', html, re.I)
    if not m:
        m = re.search(r"<title>[^<]*?(\d{4}-\d{2})\s+Season", html, re.I)
    return m.group(1) if m else None


def parse_injury_index_links(html: str) -> Dict[date, List[str]]:
    """
    All injury report PDF links on an official index page, grouped by report date and sorted
    oldest-first by publication time. Links whose file name has no timestamp are ignored.
    """
    found: Set[str] = set()
    for match in re.findall(r'href=["\']([^"\']*Injury-Report_[^"\']*\.pdf)["\']', html or "", re.IGNORECASE):
        url = match.strip()
        if not url.startswith("http"):
            url = f"https://official.nba.com{url}" if url.startswith("/") else f"{NBA_PDF_BASE_URL}/{url}"
        found.add(url)
    by_date: Dict[date, List[Tuple[datetime, str]]] = {}
    for url in found:
        pub = report_publication_time_from_url(url)
        ts = parse_pdf_filename_timestamp(url)
        if pub is None or ts is None:
            continue
        by_date.setdefault(ts.astimezone(EASTERN_TZ).date(), []).append((pub, url))
    return {d: [u for _, u in sorted(items)] for d, items in sorted(by_date.items())}


def select_listed_pdf_url(
    listed_urls: Sequence[str],
    report_date: date,
    cutoff_time_et: time,
    *,
    by_publication: bool = False,
) -> Optional[str]:
    """Latest listed URL at or before the cutoff (label or publication time, see ``build_candidate_pdf_urls``)."""
    cutoff = datetime.combine(report_date, cutoff_time_et, tzinfo=EASTERN_TZ).astimezone(timezone.utc)
    best: Optional[Tuple[datetime, str]] = None
    for url in listed_urls:
        ts = report_publication_time_from_url(url) if by_publication else parse_pdf_filename_timestamp(url)
        if ts is None or ts > cutoff:
            continue
        if best is None or ts > best[0]:
            best = (ts, url)
    return best[1] if best else None


def select_newest_pdf_url(html: str) -> Optional[str]:
    """Finds all injury report PDF links in official index page HTML and returns newest."""
    patterns = [
        r'href=["\']([^"\']*Injury-Report[^"\']*\.pdf)["\']',
        r'(https?://ak-static\.cms\.nba\.com/referee/injury/Injury-Report_[^\s"\'<>]+\.pdf)',
    ]
    candidates = set()
    for pat in patterns:
        for match in re.findall(pat, html, re.IGNORECASE):
            url = match.strip()
            if not url.startswith("http"):
                if url.startswith("/"):
                    url = f"https://official.nba.com{url}"
                else:
                    url = f"https://ak-static.cms.nba.com/referee/injury/{url}"
            candidates.add(url)

    if not candidates:
        return None

    def sort_key(u: str):
        ts = report_publication_time_from_url(u)
        if ts:
            return (1, ts.timestamp())
        return (0, u)

    sorted_candidates = sorted(candidates, key=sort_key, reverse=True)
    return sorted_candidates[0]


def default_pdf_text_extractor(pdf_bytes: bytes) -> str:
    """Extracts layout-mode text from PDF bytes using pypdf."""
    import pypdf

    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    pages_text = []
    for page in reader.pages:
        txt = page.extract_text(extraction_mode="layout")
        if txt:
            pages_text.append(txt)
    return "\n".join(pages_text)


def injury_fetch_due(
    now_local: datetime,
    games_today_commence_times: Sequence[datetime],
    downloads_today_local_times: Sequence[datetime],
    max_per_day: int = 3,
) -> bool:
    """
    Decides when a download is due on a GAME DAY only:
      1. First download after 09:00 local.
      2. Second download after 14:00 local.
      3. Third download when the first tip-off is within 60-120 minutes.
    Rules:
      - Zero downloads on days without games.
      - At most max_per_day downloads per day.
      - Never two downloads closer than 60 minutes.
    """
    # Rule: zero on days without games
    if not games_today_commence_times:
        return False

    # Rule: at most max_per_day downloads per day
    download_count = len(downloads_today_local_times)
    if download_count >= max_per_day:
        return False

    # Rule: never two downloads closer than 60 minutes
    for d in downloads_today_local_times:
        elapsed_seconds = (now_local - d).total_seconds()
        if elapsed_seconds < 3600.0:
            return False

    # Evaluate slots
    current_time = now_local.time()

    # Slot 1: first after 09:00 local
    if download_count == 0 and current_time >= time(9, 0):
        return True

    # Slot 2: second after 14:00 local
    if download_count <= 1 and current_time >= time(14, 0):
        return True

    # Slot 3: third (or before game) when the first tip-off is within 60-120 minutes
    # Convert games commence times to tz-aware matching now_local
    normalized_commence = []
    for g in games_today_commence_times:
        if g.tzinfo is None:
            g = g.replace(tzinfo=now_local.tzinfo)
        else:
            g = g.astimezone(now_local.tzinfo)
        normalized_commence.append(g)

    earliest_tipoff = min(normalized_commence)
    minutes_to_tipoff = (earliest_tipoff - now_local).total_seconds() / 60.0

    if 60.0 <= minutes_to_tipoff <= 120.0 and download_count < max_per_day:
        return True

    return False


class InjuryReportService:
    """Service to fetch, parse, and store official NBA injury reports in the database."""

    NBA_OFFICIAL_INJURY_PAGE_URL = "https://official.nba.com/nba-injury-report-2026-27-season/"
    USER_AGENT = "ArchetypeNBA-research/1.0 (personal, low frequency)"

    def __init__(
        self,
        session: Session,
        http_client: Optional[httpx.Client] = None,
        pdf_text_extractor: Optional[Callable[[bytes], str]] = None,
        timeout: float = 30.0,
        user_agent: Optional[str] = None,
    ):
        self.session = session
        self.http_client = http_client
        self.pdf_text_extractor = pdf_text_extractor or default_pdf_text_extractor
        self.timeout = timeout
        self.user_agent = user_agent or getattr(settings, "INJURY_USER_AGENT", self.USER_AGENT) or self.USER_AGENT
        self.headers = {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/pdf,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        self._name_map_cache: Dict[Tuple[str, Optional[int], Optional[int]], Tuple[Dict[str, Optional[int]], Dict[str, Optional[int]]]] = {}
        self._season_by_date: Dict[date, Optional[int]] = {}
        self._team_id_by_name: Optional[Dict[str, int]] = None
        self.last_parsed_report: Optional[ParsedInjuryReport] = None

    def _get_http_client(self) -> httpx.Client:
        if self.http_client is not None:
            return self.http_client
        return httpx.Client(headers=self.headers, timeout=self.timeout, follow_redirects=True)

    # The report says "LA Clippers" in recent seasons and "Los Angeles Clippers" in some older ones.
    TEAM_NAME_ALIASES = {"los angeles clippers": "la clippers"}

    def _get_team_id(self, team_name: Optional[str]) -> Optional[int]:
        if not team_name:
            return None
        if self._team_id_by_name is None:
            self._team_id_by_name = {}
            teams = self.session.exec(select(Team)).all()
            for t in teams:
                if t.id is not None:
                    self._team_id_by_name[t.full_name.lower()] = t.id
                    self._team_id_by_name[t.abbreviation.lower()] = t.id
        key = re.sub(r"\s+", " ", team_name).strip().lower()
        key = self.TEAM_NAME_ALIASES.get(key, key)
        return self._team_id_by_name.get(key)

    def _build_player_maps(
        self, candidates: Sequence[Tuple[int, str]]
    ) -> Tuple[Dict[str, Optional[int]], Dict[str, Optional[int]]]:
        exact_map: Dict[str, Optional[int]] = {}
        stripped_map: Dict[str, Optional[int]] = {}
        for player_id, full_name in candidates:
            if not full_name:
                continue
            norm = normalize_player_key(full_name)
            stripped = strip_player_suffix(norm)
            exact_map[norm] = None if norm in exact_map and exact_map[norm] != player_id else player_id
            stripped_map[stripped] = (
                None if stripped in stripped_map and stripped_map[stripped] != player_id else player_id
            )
        return exact_map, stripped_map

    def season_id_for_game_date(self, game_date: Optional[object]) -> Optional[int]:
        """
        Season of a report's game date ('MM/DD/YYYY', 'YYYY-MM-DD' or ``date``), taken from
        ``player_game_log`` rows of that date (exact, also for the 2020 bubble), else from the
        season row whose label matches ``season_label_for_date``. ``None`` when unknown.
        """
        d: Optional[date] = None
        if isinstance(game_date, datetime):
            d = game_date.date()
        elif isinstance(game_date, date):
            d = game_date
        elif isinstance(game_date, str) and game_date.strip():
            gs = game_date.strip()
            try:
                d = datetime.strptime(gs, "%m/%d/%Y").date() if "/" in gs else date.fromisoformat(gs)
            except ValueError:
                d = None
        if d is None:
            return None
        if d not in self._season_by_date:
            sid = self.session.exec(
                select(PlayerGameLog.season_id).where(PlayerGameLog.game_date == d).limit(1)
            ).first()
            if sid is None:
                sid = self.session.exec(
                    select(Season.id).where(Season.season_label == season_label_for_date(d))
                ).first()
            self._season_by_date[d] = int(sid) if sid is not None else None
        return self._season_by_date[d]

    def _name_maps(
        self, scope: str, team_id: Optional[int] = None, season_id: Optional[int] = None
    ) -> Tuple[Dict[str, Optional[int]], Dict[str, Optional[int]]]:
        key = (scope, team_id, season_id)
        if key in self._name_map_cache:
            return self._name_map_cache[key]
        if scope == "global":
            rows = self.session.exec(select(Player.id, Player.full_name)).all()
        else:
            pss = select(Player.id, Player.full_name).join(
                PlayerSeasonStats, PlayerSeasonStats.player_id == Player.id
            )
            pgl = select(Player.id, Player.full_name).join(
                PlayerGameLog, PlayerGameLog.player_id == Player.id
            )
            if team_id is not None:
                pss = pss.where(PlayerSeasonStats.team_id == team_id)
                pgl = pgl.where(PlayerGameLog.team_id == team_id)
            if season_id is not None:
                pss = pss.where(PlayerSeasonStats.season_id == season_id)
                pgl = pgl.where(PlayerGameLog.season_id == season_id)
            rows = [*self.session.exec(pss.distinct()).all(), *self.session.exec(pgl.distinct()).all()]
        combined = {int(p_id): str(fn) for p_id, fn in rows if p_id is not None}
        maps = self._build_player_maps(list(combined.items()))
        self._name_map_cache[key] = maps
        return maps

    def resolve_player_id(
        self,
        name: str,
        team_name: Optional[str] = None,
        game_date: Optional[object] = None,
    ) -> Optional[int]:
        """
        Resolves player_id by normalized name, narrowest scope first:
          1. team roster of the game date's season (``player_game_log`` / ``player_season_stats``),
          2. any team in that season (traded or not-yet-debuted players),
          3. the team across all seasons,
          4. every player.
        A name that matches two different players within a scope is ambiguous and is never
        resolved by a broader scope (``None``, counted as unresolved).
        """
        if not name:
            return None

        norm_name = normalize_player_key(name)
        stripped_name = strip_player_suffix(norm_name)
        team_id = self._get_team_id(team_name)
        season_id = self.season_id_for_game_date(game_date)

        scopes: List[Tuple[str, Optional[int], Optional[int]]] = []
        if season_id is not None:
            if team_id is not None:
                scopes.append(("roster", team_id, season_id))
            scopes.append(("roster", None, season_id))
        if team_id is not None:
            scopes.append(("roster", team_id, None))
        scopes.append(("global", None, None))

        for scope, t_id, s_id in scopes:
            exact, stripped = self._name_maps(scope, t_id, s_id)
            if norm_name in exact:
                return exact[norm_name]
            if stripped_name in stripped:
                return stripped[stripped_name]
        return None

    def store_pdf_bytes(
        self,
        pdf_url: str,
        pdf_bytes: bytes,
        now: Optional[datetime] = None,
        report_timestamp: Optional[datetime] = None,
    ) -> Tuple[InjuryReportSnapshot, bool, int]:
        """
        Extracts layout text from ``pdf_bytes``, parses injury entries, and stores an
        ``InjuryReportSnapshot`` plus ``InjuryEntry`` rows idempotently by sha256.
        Shared by both live fetches and historical backfill.

        ``report_timestamp`` defaults to the publication time printed in the PDF title
        ("Injury Report: 01/15/19 05:30 PM"), else the one implied by the file name
        (``report_publication_time_from_url``), else ``now``.
        Raises ``InjuryReportLayoutError`` (nothing stored) when the layout is unknown.
        Returns:
          (snapshot, created: bool, unresolved_player_count: int)
        """
        now_utc = now or datetime.now(timezone.utc)
        if now_utc.tzinfo is None:
            now_utc = now_utc.replace(tzinfo=timezone.utc)
        else:
            now_utc = now_utc.astimezone(timezone.utc)

        sha256_hash = hashlib.sha256(pdf_bytes).hexdigest()
        existing_snap = self.session.exec(
            select(InjuryReportSnapshot).where(InjuryReportSnapshot.sha256 == sha256_hash)
        ).first()
        if existing_snap is not None:
            logger.info(
                "Injury report snapshot sha256=%s already stored (id=%s). Skipping.",
                sha256_hash,
                existing_snap.id,
            )
            return existing_snap, False, 0

        pdf_text = self.pdf_text_extractor(pdf_bytes)
        if not pdf_text or not pdf_text.strip():
            raise InjuryReportLayoutError("PDF text extraction returned no text")
        report = parse_injury_report(pdf_text)
        self.last_parsed_report = report
        parsed_rows = report.rows

        report_ts = (
            report_timestamp
            or report.report_time_et
            or report_publication_time_from_url(pdf_url)
            or now_utc
        )
        if report_ts.tzinfo is None:
            report_ts = report_ts.replace(tzinfo=timezone.utc)
        else:
            report_ts = report_ts.astimezone(timezone.utc)

        snapshot = InjuryReportSnapshot(
            source="nba_official_pdf",
            report_url=pdf_url,
            report_timestamp=report_ts,
            fetched_at=now_utc,
            sha256=sha256_hash,
            entries_count=len(parsed_rows),
        )
        self.session.add(snapshot)
        self.session.flush()

        unresolved_count = 0
        for r in parsed_rows:
            p_id = self.resolve_player_id(r.player_name, team_name=r.team, game_date=r.game_date)
            if p_id is None:
                unresolved_count += 1

            prob_decimal = Decimal(str(r.availability_prob)) if r.availability_prob is not None else None

            entry = InjuryEntry(
                snapshot_id=snapshot.id,  # type: ignore
                game_date=r.game_date,
                game_time_et=r.game_time or None,
                matchup=r.matchup or None,
                team_name=r.team or None,
                player_name_raw=r.raw_name,
                player_id=p_id,
                status=r.status,
                reason=r.reason or None,
                availability_prob=prob_decimal,
            )
            self.session.add(entry)

        self.session.commit()
        logger.info(
            "Stored new injury report snapshot id=%s (%s layout, %d entries, %d unresolved players).",
            snapshot.id,
            report.layout.value,
            len(parsed_rows),
            unresolved_count,
        )
        return snapshot, True, unresolved_count

    def fetch_and_store_snapshot(
        self, now: Optional[datetime] = None
    ) -> Tuple[Optional[InjuryReportSnapshot], bool, int]:
        """
        Fetches the newest NBA injury report PDF, extracts text, and stores snapshot and entries.
        Idempotent by sha256 (identical report again = no new rows).
        Returns:
          (snapshot, created: bool, unresolved_player_count: int)
        """
        now_utc = now or datetime.now(timezone.utc)
        client = self._get_http_client()
        close_client = self.http_client is None

        try:
            # 1. Fetch main injury report page
            page_res = client.get(self.NBA_OFFICIAL_INJURY_PAGE_URL, headers=self.headers)
            page_res.raise_for_status()
            page_html = page_res.text

            # 2. Extract PDF links
            pdf_url = select_newest_pdf_url(page_html)
            if not pdf_url:
                logger.warning("No PDF links found on official injury report page.")
                return None, False, 0

            # 3. Download the PDF
            pdf_res = client.get(pdf_url, headers=self.headers)
            pdf_res.raise_for_status()
            pdf_bytes = pdf_res.content

            # 4. Parse and store via shared path
            return self.store_pdf_bytes(pdf_url, pdf_bytes, now=now_utc)

        finally:
            if close_client:
                client.close()


def injury_entry_tipoff_utc(entry: InjuryEntry) -> Optional[datetime]:
    """Tip-off (UTC) of the game an injury entry refers to, from its ``game_date`` and ``game_time_et``."""
    tip_et = parse_game_tipoff_et(entry.game_date or "", entry.game_time_et or "")
    return tip_et.astimezone(timezone.utc) if tip_et is not None else None


def snapshot_is_pre_tip(report_timestamp: datetime, tipoff: datetime) -> bool:
    """True only when the report was published STRICTLY before tip-off (leak-free use for that game)."""
    r = report_timestamp.replace(tzinfo=timezone.utc) if report_timestamp.tzinfo is None else report_timestamp
    t = tipoff.replace(tzinfo=timezone.utc) if tipoff.tzinfo is None else tipoff
    return r < t


def latest_snapshot_before_tipoff(
    session: Session,
    tipoff: datetime,
    max_age: Optional[timedelta] = None,
) -> Optional[InjuryReportSnapshot]:
    """
    Newest ``injury_report_snapshot`` with ``report_timestamp`` strictly before ``tipoff``
    (and not older than ``max_age`` when given). Models and backtests must select injury
    information for a game through this helper (or ``snapshot_is_pre_tip``) with that game's
    real tip-off, e.g. ``injury_entry_tipoff_utc``: a weekend 1 PM ET matinee tips before the
    5:00 PM report, which must then not be used for it.
    """
    tip_utc = tipoff.replace(tzinfo=timezone.utc) if tipoff.tzinfo is None else tipoff.astimezone(timezone.utc)
    stmt = (
        select(InjuryReportSnapshot)
        .where(InjuryReportSnapshot.report_timestamp < tip_utc)
        .order_by(InjuryReportSnapshot.report_timestamp.desc(), InjuryReportSnapshot.id.desc())  # type: ignore[union-attr]
    )
    if max_age is not None:
        stmt = stmt.where(InjuryReportSnapshot.report_timestamp >= tip_utc - max_age)
    return session.exec(stmt.limit(1)).first()


SLOT_FIVE_PM = "five_pm"
SLOT_PRE_TIP = "pre_tip"
SLOT_EXTRA = "extra"


@dataclass(frozen=True)
class PlannedInjurySlot:
    game_date: date
    cutoff_time_et: time
    candidate_urls: Tuple[str, ...]
    tipoff_known: bool = False
    kind: str = SLOT_FIVE_PM
    by_publication: bool = False
    listed: bool = False  # candidate_urls come from an official index page (exact files)

    @property
    def primary_url(self) -> str:
        return self.candidate_urls[0] if self.candidate_urls else ""


@dataclass
class BackfillSummary:
    start_date: date
    end_date: date
    game_dates_found: int = 0
    slots_planned: int = 0
    skipped_existing: int = 0
    planned_urls: List[str] = field(default_factory=list)
    planned_slots: List[PlannedInjurySlot] = field(default_factory=list)
    requested: int = 0
    stored: int = 0
    duplicates: int = 0
    missing: int = 0
    missing_slots: int = 0
    parse_failures: int = 0
    http_errors: int = 0
    unmatched_player_names: int = 0
    entries_stored: int = 0
    reused_slots: int = 0
    index_pages_requested: int = 0
    index_seasons_unavailable: List[str] = field(default_factory=list)
    index_dates_listed: int = 0
    estimated_requests: int = 0  # upper planning estimate: one request per planned slot (+ index pages)
    estimated_requests_min: int = 0  # lower estimate: hourly-era pre-tip slots planned without a tip collapse into the 5 PM file
    effective_delay_seconds: float = DEFAULT_BACKFILL_DELAY_SECONDS
    max_requests: int = DEFAULT_MAX_REQUESTS
    dry_run: bool = False
    interrupted: bool = False
    cap_reached: bool = False


def discover_game_dates(
    session: Session,
    start_date: date,
    end_date: date,
) -> Dict[date, Optional[datetime]]:
    """
    Finds all NBA game dates in ``[start_date, end_date]`` from ``player_game_log`` and ``game``.
    Returns a sorted dictionary mapping ``game_date -> earliest_tipoff_et`` (``None`` when the date
    comes only from ``player_game_log`` and exact tip-off time is unknown).
    Non-game days, postponed games, and NBA preseason (001) / All-Star (003) games are skipped.
    """
    if end_date < start_date:
        return {}

    dates_to_tipoff: Dict[date, Optional[datetime]] = {}

    pgl_rows = session.exec(
        select(PlayerGameLog.game_date, PlayerGameLog.game_id)
        .where(
            PlayerGameLog.game_date.is_not(None),  # type: ignore[union-attr]
            PlayerGameLog.game_date >= start_date,  # type: ignore[operator]
            PlayerGameLog.game_date <= end_date,  # type: ignore[operator]
        )
        .distinct()
    ).all()
    for g_date, g_id in pgl_rows:
        if g_date is None:
            continue
        if g_id and len(g_id) == 10 and g_id.isdigit() and g_id[2] in ("1", "3"):
            continue
        dates_to_tipoff.setdefault(g_date, None)

    start_utc = datetime.combine(start_date, time(0, 0, 0), tzinfo=EASTERN_TZ).astimezone(timezone.utc)
    end_utc = datetime.combine(end_date, time(23, 59, 59), tzinfo=EASTERN_TZ).astimezone(timezone.utc)
    game_commence_times = session.exec(
        select(Game.commence_time).where(
            Game.commence_time >= start_utc,
            Game.commence_time <= end_utc,
            Game.status != "postponed",
        )
    ).all()
    for ct in game_commence_times:
        if ct is None:
            continue
        ct_utc = ct.replace(tzinfo=timezone.utc) if ct.tzinfo is None else ct.astimezone(timezone.utc)
        ct_et = ct_utc.astimezone(EASTERN_TZ)
        g_date = ct_et.date()
        if start_date <= g_date <= end_date:
            current_min = dates_to_tipoff.get(g_date)
            if current_min is None or ct_et < current_min:
                dates_to_tipoff[g_date] = ct_et

    return {d: dates_to_tipoff[d] for d in sorted(dates_to_tipoff.keys())}


def earliest_tipoffs_from_entries(
    session: Session,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> Dict[date, datetime]:
    """Earliest tip-off (Eastern) per game date printed in already stored reports (``game_time_et``)."""
    rows = session.exec(select(InjuryEntry.game_date, InjuryEntry.game_time_et).distinct()).all()
    out: Dict[date, datetime] = {}
    for g_date, g_time in rows:
        tip = parse_game_tipoff_et(g_date or "", g_time or "")
        if tip is None:
            continue
        d = tip.date()
        if (start_date and d < start_date) or (end_date and d > end_date):
            continue
        if d not in out or tip < out[d]:
            out[d] = tip
    return out


def _slot_specs_for_date(
    game_date: date,
    earliest_tipoff_et: Optional[datetime],
    per_day: int = 2,
) -> List[Tuple[str, time, bool]]:
    """
    ``(kind, cutoff_et, by_publication)`` per slot for ``game_date``:
      - five_pm: the report labelled 5:00 PM ET (hourly era: ``_05PM``, published 5:30 PM)
      - pre_tip: latest report PUBLISHED at or before earliest tip-off - 60 min
        (7:30 PM ET when the tip-off is unknown at planning time)
      - extra (per_day >= 3): 1:00 PM, 11:00 AM, 9:00 AM, 3:00 PM ET by publication time
    """
    if per_day <= 0:
        return []
    specs: List[Tuple[str, time, bool]] = [(SLOT_FIVE_PM, DEFAULT_SLOT_1_ET, False)]
    if per_day >= 2:
        if earliest_tipoff_et is not None:
            pre_tip = earliest_tipoff_et.astimezone(EASTERN_TZ) - PRE_TIP_MARGIN
            if pre_tip.date() < game_date:
                cutoff = time(0, 0)
            elif pre_tip.date() > game_date:
                cutoff = time(23, 59)
            else:
                cutoff = time(pre_tip.hour, pre_tip.minute)
        else:
            cutoff = DEFAULT_SLOT_2_ET
        specs.append((SLOT_PRE_TIP, cutoff, True))
    for extra in (DEFAULT_SLOT_3_ET, time(11, 0), time(9, 0), time(15, 0)):
        if len(specs) >= per_day:
            break
        specs.append((SLOT_EXTRA, extra, True))
    return specs


def _build_slot(
    game_date: date,
    kind: str,
    cutoff: time,
    by_publication: bool,
    tipoff_known: bool,
    listed_urls_by_date: Optional[Dict[date, List[str]]],
    base_url: str,
) -> PlannedInjurySlot:
    if listed_urls_by_date is not None and game_date in listed_urls_by_date:
        url = select_listed_pdf_url(
            listed_urls_by_date[game_date], game_date, cutoff, by_publication=by_publication
        )
        candidates: Tuple[str, ...] = (url,) if url else ()
        listed = True
    else:
        candidates = tuple(
            build_candidate_pdf_urls(game_date, cutoff, by_publication=by_publication, base_url=base_url)
        )
        listed = False
    return PlannedInjurySlot(
        game_date=game_date,
        cutoff_time_et=cutoff,
        candidate_urls=candidates,
        tipoff_known=tipoff_known,
        kind=kind,
        by_publication=by_publication,
        listed=listed,
    )


def _stored_report_urls(session: Session) -> Set[str]:
    return {u for u in session.exec(select(InjuryReportSnapshot.report_url)).all() if u}


def _slot_already_stored(
    slot: PlannedInjurySlot,
    stored_urls: Set[str],
    stored_by_date: Dict[date, List[Tuple[datetime, datetime]]],
) -> bool:
    """
    A slot is stored when one of its candidates is stored, or a stored report of that date
    falls in the slot's 1-hour window (label time for the 5 PM slot, publication time otherwise).
    """
    if any(u in stored_urls for u in slot.candidate_urls):
        return True
    cutoff = datetime.combine(slot.game_date, slot.cutoff_time_et, tzinfo=EASTERN_TZ).astimezone(timezone.utc)
    window_start = cutoff - timedelta(minutes=60)
    for label_ts, pub_ts in stored_by_date.get(slot.game_date, []):
        ts = pub_ts if slot.by_publication else label_ts
        if window_start < ts <= cutoff:
            return True
    return False


def plan_backfill_slots(
    session: Session,
    start_date: date = ARCHIVE_START_DATE,
    end_date: Optional[date] = None,
    per_day: int = 2,
    base_url: str = NBA_PDF_BASE_URL,
    listed_urls_by_date: Optional[Dict[date, List[str]]] = None,
) -> Tuple[List[PlannedInjurySlot], int, int]:
    """
    Plans historical injury report download slots in ``[start_date, end_date]``, skipping
    slots already present in ``injury_report_snapshot``. Dates listed on an official index
    page use the exact listed file (one request); other dates use guessed names
    (``build_candidate_pdf_urls``). A pre-tip slot that resolves to the same file as the 5 PM
    slot is dropped (no second request for the same report).
    Returns ``(planned_slots, game_dates_count, skipped_existing_count)``.
    """
    resolved_end = end_date or datetime.now(EASTERN_TZ).date()
    dates_map = discover_game_dates(session, start_date, resolved_end)
    if not dates_map:
        return [], 0, 0
    entry_tips = earliest_tipoffs_from_entries(session, start_date, resolved_end)

    stored_urls: Set[str] = set()
    stored_by_date: Dict[date, List[Tuple[datetime, datetime]]] = {}
    for r_url, r_ts in session.exec(
        select(InjuryReportSnapshot.report_url, InjuryReportSnapshot.report_timestamp)
    ).all():
        if r_url:
            stored_urls.add(r_url)
        label_ts = parse_pdf_filename_timestamp(r_url or "")
        pub_ts = report_publication_time_from_url(r_url or "")
        if label_ts is None and r_ts is not None:
            label_ts = pub_ts = r_ts.replace(tzinfo=timezone.utc) if r_ts.tzinfo is None else r_ts.astimezone(timezone.utc)
        if label_ts is not None and pub_ts is not None:
            stored_by_date.setdefault(label_ts.astimezone(EASTERN_TZ).date(), []).append((label_ts, pub_ts))

    planned: List[PlannedInjurySlot] = []
    skipped_existing = 0
    for g_date, game_tip in dates_map.items():
        tip = game_tip or entry_tips.get(g_date)
        date_slots: List[PlannedInjurySlot] = []
        for kind, cutoff, by_pub in _slot_specs_for_date(g_date, tip, per_day=per_day):
            slot = _build_slot(g_date, kind, cutoff, by_pub, tip is not None, listed_urls_by_date, base_url)
            if not slot.candidate_urls and not slot.listed:
                continue
            if slot.candidate_urls and any(s.primary_url == slot.primary_url for s in date_slots):
                continue
            date_slots.append(slot)
        for slot in date_slots:
            if _slot_already_stored(slot, stored_urls, stored_by_date):
                skipped_existing += 1
                continue
            planned.append(slot)

    return planned, len(dates_map), skipped_existing


def fetch_listed_report_urls(
    season_labels: Sequence[str],
    request_fn: Callable[[str], Optional[httpx.Response]],
    summary: BackfillSummary,
) -> Dict[date, List[str]]:
    """
    Downloads each season's official index page once and returns the listed PDF URLs by date.
    The NBA site redirects past season URLs to the current season's page (which lists only the
    current day's reports); such seasons are recorded in ``summary.index_seasons_unavailable``
    and their dates fall back to guessed file names.
    """
    listed: Dict[date, List[str]] = {}
    for label in season_labels:
        res = request_fn(season_index_page_url(label))
        if res is None:
            break
        summary.index_pages_requested += 1
        if res.status_code >= 400:
            summary.index_seasons_unavailable.append(label)
            continue
        html = res.text
        served = index_page_season(html)
        if served != label:
            summary.index_seasons_unavailable.append(label)
        for d, urls in parse_injury_index_links(html).items():
            merged = set(listed.get(d, [])) | set(urls)
            listed[d] = sorted(merged, key=lambda u: report_publication_time_from_url(u) or datetime.min.replace(tzinfo=timezone.utc))
    summary.index_dates_listed = len(listed)
    return listed


def backfill_injury_reports(
    session: Session,
    *,
    start_date: date = ARCHIVE_START_DATE,
    end_date: Optional[date] = None,
    per_day: int = 2,
    delay_seconds: float = DEFAULT_BACKFILL_DELAY_SECONDS,
    max_requests: int = DEFAULT_MAX_REQUESTS,
    dry_run: bool = False,
    use_index_pages: bool = True,
    http_client: Optional[httpx.Client] = None,
    pdf_text_extractor: Optional[Callable[[bytes], str]] = None,
    sleep_fn: Callable[[float], None] = time_module.sleep,
    now: Optional[datetime] = None,
    base_url: str = NBA_PDF_BASE_URL,
) -> BackfillSummary:
    """
    Polite, resumable historical backfill for official NBA injury report PDFs.
    - Discovers exact file URLs from the official season index pages (one request per season)
      when ``use_index_pages``; dates not listed there use guessed names of the date's naming era.
    - Enforces minimum 2.0 s delay between HTTP requests (default 4.0 s) and a hard
      ``max_requests`` cap per run (index pages included).
    - Skips slots already stored in ``injury_report_snapshot``; a pre-tip slot whose tip-off
      was unknown at planning time is re-planned from the game times printed in the stored
      5 PM report of that date, and is satisfied without a request when it resolves to a file
      already stored.
    - In ``dry_run`` mode, plans and lists URLs with zero network calls.
    - Stores snapshots with the publication time printed in the PDF title.
    """
    resolved_end = end_date or (
        now.astimezone(EASTERN_TZ).date()
        if (now is not None and now.tzinfo is not None)
        else datetime.now(EASTERN_TZ).date()
    )
    effective_delay = max(MIN_BACKFILL_DELAY_SECONDS, float(delay_seconds))
    if float(delay_seconds) < MIN_BACKFILL_DELAY_SECONDS:
        logger.warning(
            "Requested delay %.2fs is below minimum %.2fs; clamping to %.2fs.",
            delay_seconds,
            MIN_BACKFILL_DELAY_SECONDS,
            effective_delay,
        )

    planned_slots, game_dates_count, skipped_existing = plan_backfill_slots(
        session=session,
        start_date=start_date,
        end_date=resolved_end,
        per_day=per_day,
        base_url=base_url,
    )
    season_labels: List[str] = []
    for d in sorted({s.game_date for s in planned_slots}, reverse=True):
        label = season_label_for_date(d)
        if label not in season_labels:
            season_labels.append(label)

    summary = BackfillSummary(
        start_date=start_date,
        end_date=resolved_end,
        game_dates_found=game_dates_count,
        slots_planned=len(planned_slots),
        skipped_existing=skipped_existing,
        planned_slots=planned_slots,
        planned_urls=[s.primary_url for s in planned_slots[: max(0, max_requests)]],
        effective_delay_seconds=effective_delay,
        max_requests=max_requests,
        dry_run=dry_run,
        estimated_requests=len(planned_slots) + (len(season_labels) if use_index_pages else 0),
        estimated_requests_min=sum(
            1
            for s in planned_slots
            if not (s.kind == SLOT_PRE_TIP and not s.tipoff_known and naming_is_hourly(s.game_date))
        )
        + (len(season_labels) if use_index_pages else 0),
    )

    if dry_run or max_requests <= 0 or not planned_slots:
        if not dry_run and max_requests <= 0 and planned_slots:
            summary.cap_reached = True
        return summary

    service = InjuryReportService(
        session=session,
        http_client=http_client,
        pdf_text_extractor=pdf_text_extractor,
    )
    client = service._get_http_client()
    close_client = http_client is None
    attempted_urls: Set[str] = set()

    def _log_progress_if_due() -> None:
        if summary.requested > 0 and summary.requested % PROGRESS_LOG_INTERVAL == 0:
            logger.info(
                "Backfill progress: requested=%d/%d stored=%d missing=%d parse_failures=%d unmatched_players=%d",
                summary.requested,
                max_requests,
                summary.stored,
                summary.missing,
                summary.parse_failures,
                summary.unmatched_player_names,
            )

    def _request(url: str) -> Optional[httpx.Response]:
        """One polite GET (delay before every request but the first); None when the cap is reached."""
        if summary.requested >= max_requests:
            summary.cap_reached = True
            return None
        if summary.requested > 0:
            sleep_fn(effective_delay)
        summary.requested += 1
        try:
            return client.get(url, headers=service.headers)
        finally:
            _log_progress_if_due()

    try:
        if use_index_pages and season_labels:

            def _index_request(url: str) -> Optional[httpx.Response]:
                try:
                    return _request(url)
                except httpx.HTTPError as exc:
                    summary.http_errors += 1
                    logger.warning("HTTP error fetching index page %s: %s", url, exc)
                    return httpx.Response(599)

            listed = fetch_listed_report_urls(season_labels, _index_request, summary)
            if listed:
                planned_slots, _, skipped_existing = plan_backfill_slots(
                    session=session,
                    start_date=start_date,
                    end_date=resolved_end,
                    per_day=per_day,
                    base_url=base_url,
                    listed_urls_by_date=listed,
                )
                summary.planned_slots = planned_slots
                summary.slots_planned = len(planned_slots)
                summary.skipped_existing = skipped_existing
        else:
            listed = {}

        stored_urls = _stored_report_urls(session)

        for slot in planned_slots:
            if summary.cap_reached or summary.requested >= max_requests:
                summary.cap_reached = True
                break

            if slot.kind == SLOT_PRE_TIP and not slot.tipoff_known:
                tip = earliest_tipoffs_from_entries(session, slot.game_date, slot.game_date).get(slot.game_date)
                if tip is not None:
                    specs = [s for s in _slot_specs_for_date(slot.game_date, tip, per_day=2) if s[0] == SLOT_PRE_TIP]
                    _, cutoff, by_pub = specs[0]
                    slot = _build_slot(slot.game_date, SLOT_PRE_TIP, cutoff, by_pub, True, listed or None, base_url)

            slot_satisfied = False
            slot_had_failure = False

            for url in slot.candidate_urls:
                if url in stored_urls:
                    summary.reused_slots += 1
                    slot_satisfied = True
                    break
                if url in attempted_urls:
                    continue
                attempted_urls.add(url)
                try:
                    res = _request(url)
                except httpx.HTTPError as exc:
                    summary.http_errors += 1
                    slot_had_failure = True
                    logger.warning("HTTP error fetching %s: %s", url, exc)
                    continue
                if res is None:
                    break

                if res.status_code in (403, 404):
                    summary.missing += 1
                    logger.debug("Report missing (HTTP %d): %s", res.status_code, url)
                    continue

                if res.status_code >= 400:
                    summary.http_errors += 1
                    slot_had_failure = True
                    logger.warning("Unexpected HTTP %d fetching %s", res.status_code, url)
                    continue

                try:
                    snap, created, unresolved = service.store_pdf_bytes(
                        pdf_url=url,
                        pdf_bytes=res.content,
                        now=now,
                    )
                except Exception as exc:
                    session.rollback()
                    summary.parse_failures += 1
                    slot_had_failure = True
                    logger.warning("Failed to parse/store injury PDF %s: %s", url, exc)
                    break

                stored_urls.add(url)
                if created:
                    summary.stored += 1
                    summary.entries_stored += snap.entries_count
                    summary.unmatched_player_names += unresolved
                else:
                    summary.duplicates += 1
                slot_satisfied = True
                break

            if not slot_satisfied and not slot_had_failure and not summary.cap_reached:
                summary.missing_slots += 1

    except KeyboardInterrupt:
        session.rollback()
        summary.interrupted = True
        logger.info(
            "Interrupted by user (Ctrl-C) after %d requests (%d stored). Stopping gracefully.",
            summary.requested,
            summary.stored,
        )
    finally:
        if close_client:
            client.close()

    return summary
