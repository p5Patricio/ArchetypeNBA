from datetime import datetime, time, timezone
import hashlib
import io
import logging
import re
from typing import Callable, Dict, List, Optional, Sequence, Tuple
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


def parse_pdf_filename_timestamp(url: str) -> Optional[datetime]:
    """
    Extracts timestamp from NBA PDF naming pattern, e.g. Injury-Report_2026-10-28_05_00PM.pdf.
    Converts Eastern time to UTC tz-aware datetime.
    """
    m = re.search(
        r"Injury-Report_(\d{4}-\d{2}-\d{2})_(\d{1,2})_(\d{2})([AP]M)",
        url,
        re.IGNORECASE,
    )
    if not m:
        return None
    date_str, hour_str, min_str, ampm_str = m.groups()
    try:
        hour = int(hour_str)
        minute = int(min_str)
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
    ):
        self.session = session
        self.http_client = http_client
        self.pdf_text_extractor = pdf_text_extractor or default_pdf_text_extractor
        self.timeout = timeout
        self.headers = {
            "User-Agent": self.USER_AGENT,
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

            # 4. Check sha256 idempotency
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

            # 5. Extract text and parse rows
            pdf_text = self.pdf_text_extractor(pdf_bytes)
            parsed_rows = parse_injury_report_text(pdf_text)

            # 6. Parse report timestamp
            report_ts = parse_pdf_filename_timestamp(pdf_url) or now_utc

            # 7. Create snapshot
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

            # 8. Create entries
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

        finally:
            if close_client:
                client.close()
