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
from app.models import Game, InjuryEntry, InjuryReportSnapshot, Player, PlayerGameLog, PlayerSeasonStats, Team
from app.services.injury_report_parser import parse_injury_report_text, ParsedInjuryRow

logger = logging.getLogger(__name__)

EASTERN_TZ = ZoneInfo("America/New_York")
NBA_PDF_BASE_URL = "https://ak-static.cms.nba.com/referee/injury"
ARCHIVE_START_DATE = date(2018, 12, 17)
DEFAULT_SLOT_1_ET = time(17, 0)   # 5:00 PM ET
DEFAULT_SLOT_2_ET = time(19, 30)  # 7:30 PM ET (when tip times are unknown)
DEFAULT_SLOT_3_ET = time(13, 0)   # 1:00 PM ET (when --per-day >= 3)
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


def build_candidate_pdf_urls(
    report_date: date,
    cutoff_time_et: time,
    *,
    base_url: str = NBA_PDF_BASE_URL,
) -> List[str]:
    """
    Builds candidate PDF URLs at or before ``cutoff_time_et`` on ``report_date``, ordered
    newest-first within the 1-hour window ending at ``cutoff_time_et``.
    Includes both the 15-minute naming variant (``HH_MMAM|PM.pdf``) and the 2018-2022
    hourly naming variant (``HHAM|PM.pdf``) at top-of-hour marks.
    All returned URLs have report timestamps strictly <= ``cutoff_time_et`` on ``report_date``.
    """
    floored_minute = (cutoff_time_et.minute // 15) * 15
    base_dt = datetime.combine(
        report_date,
        time(cutoff_time_et.hour, floored_minute),
        tzinfo=EASTERN_TZ,
    )
    urls: List[str] = []
    seen: Set[str] = set()

    for step_minutes in (0, 15, 30, 45):
        cand_dt = base_dt - timedelta(minutes=step_minutes)
        if cand_dt.date() != report_date:
            continue
        cand_time = cand_dt.time()
        u_15 = build_injury_pdf_url(report_date, cand_time, hourly=False, base_url=base_url)
        if u_15 not in seen:
            urls.append(u_15)
            seen.add(u_15)
        if cand_time.minute == 0:
            u_hr = build_injury_pdf_url(report_date, cand_time, hourly=True, base_url=base_url)
            if u_hr not in seen:
                urls.append(u_hr)
                seen.add(u_hr)

    return urls


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
        ts = parse_pdf_filename_timestamp(u)
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
        self._team_player_cache: Dict[int, Tuple[Dict[str, Optional[int]], Dict[str, Optional[int]]]] = {}
        self._global_player_cache: Optional[Tuple[Dict[str, Optional[int]], Dict[str, Optional[int]]]] = None
        self._team_id_by_name: Optional[Dict[str, int]] = None

    def _get_http_client(self) -> httpx.Client:
        if self.http_client is not None:
            return self.http_client
        return httpx.Client(headers=self.headers, timeout=self.timeout, follow_redirects=True)

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
        return self._team_id_by_name.get(team_name.lower())

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

    def resolve_player_id(self, name: str, team_name: Optional[str] = None) -> Optional[int]:
        """Resolves player_id using normalized name, scoped to team when possible."""
        if not name:
            return None

        norm_name = normalize_player_key(name)
        stripped_name = strip_player_suffix(norm_name)

        # 1. Try team-scoped lookup if team is known
        team_id = self._get_team_id(team_name)
        if team_id is not None:
            if team_id not in self._team_player_cache:
                pss_players = self.session.exec(
                    select(Player.id, Player.full_name)
                    .join(PlayerSeasonStats, PlayerSeasonStats.player_id == Player.id)
                    .where(PlayerSeasonStats.team_id == team_id)
                ).all()
                pgl_players = self.session.exec(
                    select(Player.id, Player.full_name)
                    .join(PlayerGameLog, PlayerGameLog.player_id == Player.id)
                    .where(PlayerGameLog.team_id == team_id)
                ).all()
                combined = {int(p_id): str(fn) for p_id, fn in [*pss_players, *pgl_players] if p_id is not None}
                self._team_player_cache[team_id] = self._build_player_maps(list(combined.items()))

            t_exact, t_stripped = self._team_player_cache[team_id]
            if norm_name in t_exact and t_exact[norm_name] is not None:
                return t_exact[norm_name]
            if stripped_name in t_stripped and t_stripped[stripped_name] is not None:
                return t_stripped[stripped_name]

        # 2. Global fallback
        if self._global_player_cache is None:
            all_players = self.session.exec(select(Player.id, Player.full_name)).all()
            candidates = [(int(p_id), str(fn)) for p_id, fn in all_players if p_id is not None]
            self._global_player_cache = self._build_player_maps(candidates)

        g_exact, g_stripped = self._global_player_cache
        if norm_name in g_exact and g_exact[norm_name] is not None:
            return g_exact[norm_name]
        if stripped_name in g_stripped and g_stripped[stripped_name] is not None:
            return g_stripped[stripped_name]

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
        parsed_rows = parse_injury_report_text(pdf_text)

        report_ts = report_timestamp or parse_pdf_filename_timestamp(pdf_url) or now_utc
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
            p_id = self.resolve_player_id(r.player_name, team_name=r.team)
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
            "Stored new injury report snapshot id=%s (%d entries, %d unresolved players).",
            snapshot.id,
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


@dataclass(frozen=True)
class PlannedInjurySlot:
    game_date: date
    cutoff_time_et: time
    candidate_urls: Tuple[str, ...]
    tipoff_known: bool = False

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

    # 1. Dates from player_game_log
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

    # 2. Dates and earliest tip-offs (Eastern Time) from game table
    start_et = datetime.combine(start_date, time(0, 0, 0), tzinfo=EASTERN_TZ)
    end_et = datetime.combine(end_date, time(23, 59, 59), tzinfo=EASTERN_TZ)
    start_utc = start_et.astimezone(timezone.utc)
    end_utc = end_et.astimezone(timezone.utc)

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


def _slot_cutoffs_for_date(
    game_date: date,
    earliest_tipoff_et: Optional[datetime],
    per_day: int = 2,
) -> List[time]:
    """
    Computes up to ``per_day`` report cutoff times (Eastern) for ``game_date``:
      - Slot 1: 5:00 PM ET (17:00)
      - Slot 2: 60 minutes before earliest tip-off when known, else 7:30 PM ET (19:30)
      - Slot 3 (when per_day >= 3): 1:00 PM ET (13:00)
    """
    if per_day <= 0:
        return []

    slot_1 = DEFAULT_SLOT_1_ET
    if earliest_tipoff_et is not None:
        pre_tip = earliest_tipoff_et - timedelta(minutes=60)
        if pre_tip.date() < game_date:
            slot_2 = time(0, 0)
        elif pre_tip.date() > game_date:
            slot_2 = time(23, 45)
        else:
            slot_2 = time(pre_tip.hour, (pre_tip.minute // 15) * 15)
    else:
        slot_2 = DEFAULT_SLOT_2_ET

    if per_day == 1:
        raw_slots = [slot_1]
    elif per_day == 2:
        raw_slots = [slot_1, slot_2]
    else:
        extra_candidates = [
            DEFAULT_SLOT_3_ET,
            time(11, 0),
            time(9, 0),
            time(15, 0),
        ]
        raw_slots = [slot_1, slot_2]
        for extra in extra_candidates:
            if len(raw_slots) >= per_day:
                break
            if extra not in raw_slots:
                raw_slots.append(extra)

    unique_sorted: List[time] = sorted(set(raw_slots[:per_day]))
    return unique_sorted


def plan_backfill_slots(
    session: Session,
    start_date: date = ARCHIVE_START_DATE,
    end_date: Optional[date] = None,
    per_day: int = 2,
    base_url: str = NBA_PDF_BASE_URL,
) -> Tuple[List[PlannedInjurySlot], int, int]:
    """
    Plans historical injury report download slots in ``[start_date, end_date]``, skipping
    slots already present in ``injury_report_snapshot``.
    Returns ``(planned_slots, game_dates_count, skipped_existing_count)``.
    """
    resolved_end = end_date or datetime.now(EASTERN_TZ).date()
    dates_map = discover_game_dates(session, start_date, resolved_end)
    if not dates_map:
        return [], 0, 0

    existing_rows = session.exec(
        select(InjuryReportSnapshot.report_url, InjuryReportSnapshot.report_timestamp)
    ).all()
    existing_urls: Set[str] = set()
    existing_ts_utc: List[datetime] = []
    for r_url, r_ts in existing_rows:
        if r_url:
            existing_urls.add(r_url)
        if r_ts is not None:
            ts_u = r_ts.replace(tzinfo=timezone.utc) if r_ts.tzinfo is None else r_ts.astimezone(timezone.utc)
            existing_ts_utc.append(ts_u)

    planned: List[PlannedInjurySlot] = []
    skipped_existing = 0

    for g_date, earliest_tip_et in dates_map.items():
        cutoffs = _slot_cutoffs_for_date(g_date, earliest_tip_et, per_day=per_day)
        for cutoff in cutoffs:
            cand_urls = build_candidate_pdf_urls(g_date, cutoff, base_url=base_url)
            if not cand_urls:
                continue

            floored_min = (cutoff.minute // 15) * 15
            slot_end_utc = datetime.combine(
                g_date, time(cutoff.hour, floored_min), tzinfo=EASTERN_TZ
            ).astimezone(timezone.utc)
            slot_start_utc = slot_end_utc - timedelta(minutes=45)

            already_stored = any(u in existing_urls for u in cand_urls) or any(
                slot_start_utc <= ts <= slot_end_utc for ts in existing_ts_utc
            )
            if already_stored:
                skipped_existing += 1
                continue

            planned.append(
                PlannedInjurySlot(
                    game_date=g_date,
                    cutoff_time_et=cutoff,
                    candidate_urls=tuple(cand_urls),
                    tipoff_known=earliest_tip_et is not None,
                )
            )

    return planned, len(dates_map), skipped_existing


def backfill_injury_reports(
    session: Session,
    *,
    start_date: date = ARCHIVE_START_DATE,
    end_date: Optional[date] = None,
    per_day: int = 2,
    delay_seconds: float = DEFAULT_BACKFILL_DELAY_SECONDS,
    max_requests: int = DEFAULT_MAX_REQUESTS,
    dry_run: bool = False,
    http_client: Optional[httpx.Client] = None,
    pdf_text_extractor: Optional[Callable[[bytes], str]] = None,
    sleep_fn: Callable[[float], None] = time_module.sleep,
    now: Optional[datetime] = None,
    base_url: str = NBA_PDF_BASE_URL,
) -> BackfillSummary:
    """
    Polite, resumable historical backfill for official NBA injury report PDFs.
    - Enforces minimum 2.0 s delay between HTTP requests (default 4.0 s).
    - Enforces hard ``max_requests`` cap per run (default 300).
    - Skips slots already stored in ``injury_report_snapshot``.
    - In ``dry_run`` mode, plans and lists URLs with zero network calls.
    - Stores snapshots with their true filename ``report_timestamp`` (Eastern -> UTC).
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

    try:
        for slot in planned_slots:
            if summary.requested >= max_requests:
                summary.cap_reached = True
                break

            slot_satisfied = False
            slot_had_failure = False

            for url in slot.candidate_urls:
                if url in attempted_urls:
                    continue
                if summary.requested >= max_requests:
                    summary.cap_reached = True
                    break

                if summary.requested > 0:
                    sleep_fn(effective_delay)

                summary.requested += 1
                attempted_urls.add(url)

                try:
                    res = client.get(url, headers=service.headers)
                except httpx.HTTPError as exc:
                    summary.http_errors += 1
                    slot_had_failure = True
                    logger.warning("HTTP error fetching %s: %s", url, exc)
                    _log_progress_if_due()
                    continue

                if res.status_code in (403, 404):
                    summary.missing += 1
                    logger.debug("Report missing (HTTP %d): %s", res.status_code, url)
                    _log_progress_if_due()
                    continue

                if res.status_code >= 400:
                    summary.http_errors += 1
                    slot_had_failure = True
                    logger.warning("Unexpected HTTP %d fetching %s", res.status_code, url)
                    _log_progress_if_due()
                    continue

                report_ts = parse_pdf_filename_timestamp(url)
                try:
                    _, created, unresolved = service.store_pdf_bytes(
                        pdf_url=url,
                        pdf_bytes=res.content,
                        now=now,
                        report_timestamp=report_ts,
                    )
                except Exception as exc:
                    session.rollback()
                    summary.parse_failures += 1
                    slot_had_failure = True
                    logger.warning("Failed to parse/store injury PDF %s: %s", url, exc)
                    _log_progress_if_due()
                    break

                if created:
                    summary.stored += 1
                    summary.unmatched_player_names += unresolved
                else:
                    summary.duplicates += 1

                slot_satisfied = True
                _log_progress_if_due()
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

