from dataclasses import dataclass, field
from datetime import datetime, timezone
import io
import json
import logging
from pathlib import Path
import re
from typing import List, Optional

import httpx
from pydantic import BaseModel
import pypdf

from app.config import settings
from app.services.injury_report_parser import (
    ParsedInjuryRow,
    parse_injury_report_text,
)

logger = logging.getLogger(__name__)


class InjuryItem(BaseModel):
    game_date: str = ""
    matchup: str = ""
    team: str = ""
    player_name: str = ""
    status: str = ""  # Out, Questionable, Doubtful, Probable, Available
    reason: str = ""
    game_time: Optional[str] = None
    availability_prob: Optional[float] = None


@dataclass
class InjuryReport:
    available: bool
    reason: Optional[str] = None
    fetched_at: Optional[datetime] = None
    rows: List[InjuryItem] = field(default_factory=list)


def _parse_pdf_filename_timestamp(url: str) -> Optional[datetime]:
    """Extracts timestamp from NBA PDF naming pattern, e.g. Injury-Report_2026-10-28_05_00PM.pdf."""
    m = re.search(r"Injury-Report_(\d{4}-\d{2}-\d{2})_(\d{1,2})_(\d{2})([AP]M)", url, re.IGNORECASE)
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
        return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)
    except Exception:
        return None


class InjuryScraperService:
    """Scrapes and parses official NBA injury reports without data fabrication."""

    NBA_OFFICIAL_INJURY_PAGE_URL = "https://official.nba.com/nba-injury-report-2026-27-season/"
    USER_AGENT = "ArchetypeNBA-research/1.0 (personal, low frequency)"
    CACHE_TTL_SECONDS = 3600  # at most one download per 60 minutes

    def __init__(
        self,
        timeout: float = 30.0,
        http_client: Optional[httpx.Client] = None,
        cache_file: Optional[Path] = None,
    ):
        self.timeout = timeout
        self.http_client = http_client
        self.headers = {
            "User-Agent": self.USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/pdf,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        if cache_file is not None:
            self.cache_file = cache_file
        else:
            # Default to logs/last_injury_report.json relative to repository root
            repo_root = Path(__file__).resolve().parents[3]
            self.cache_file = repo_root / "logs" / "last_injury_report.json"

    def fetch_injury_report(self) -> InjuryReport:
        """
        Fetches the official NBA injury report PDF if enabled by configuration.
        Returns an explicit InjuryReport object with available=False and a truthful reason if disabled or failing.
        Never invents or fabricates injury records.
        """
        now = datetime.now(timezone.utc)

        # Terms gating
        if not settings.INJURY_PDF_ENABLED:
            return InjuryReport(
                available=False,
                reason="disabled: NBA terms not cleared by the owner",
                fetched_at=now,
                rows=[],
            )

        # Check 60-minute rate limit cache
        cached_report = self._read_cache(now)
        if cached_report is not None:
            logger.info("InjuryScraper: Returning cached injury report within 60-minute TTL.")
            return cached_report

        try:
            return self._download_and_parse(now)
        except Exception as e:
            logger.warning(f"InjuryScraper: Error fetching injury report: {e}")
            return InjuryReport(
                available=False,
                reason=f"error: {e}",
                fetched_at=now,
                rows=[],
            )

    def _read_cache(self, now: datetime) -> Optional[InjuryReport]:
        if not self.cache_file or not self.cache_file.exists():
            return None
        try:
            with open(self.cache_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            fetched_at_str = data.get("fetched_at")
            if not fetched_at_str:
                return None
            fetched_at = datetime.fromisoformat(fetched_at_str)
            age = (now - fetched_at).total_seconds()
            if age < self.CACHE_TTL_SECONDS:
                rows = [InjuryItem(**r) for r in data.get("rows", [])]
                return InjuryReport(
                    available=data.get("available", True),
                    reason=data.get("reason"),
                    fetched_at=fetched_at,
                    rows=rows,
                )
        except Exception as e:
            logger.warning(f"InjuryScraper: Could not read cache file {self.cache_file}: {e}")
        return None

    def _write_cache(self, report: InjuryReport) -> None:
        if not self.cache_file:
            return
        try:
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "available": report.available,
                "reason": report.reason,
                "fetched_at": report.fetched_at.isoformat() if report.fetched_at else None,
                "rows": [r.model_dump() for r in report.rows],
            }
            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"InjuryScraper: Could not write cache to {self.cache_file}: {e}")

    def _get_http_client(self) -> httpx.Client:
        if self.http_client is not None:
            return self.http_client
        return httpx.Client(headers=self.headers, timeout=self.timeout, follow_redirects=True)

    def _download_and_parse(self, now: datetime) -> InjuryReport:
        client = self._get_http_client()
        close_client = self.http_client is None

        try:
            # 1. Fetch main injury report page
            page_res = client.get(self.NBA_OFFICIAL_INJURY_PAGE_URL, headers=self.headers)
            page_res.raise_for_status()
            page_html = page_res.text

            # 2. Extract PDF links
            pdf_url = self._select_newest_pdf_url(page_html)
            if not pdf_url:
                return InjuryReport(
                    available=False,
                    reason="no PDF links found on official injury report page",
                    fetched_at=now,
                    rows=[],
                )

            # 3. Download the PDF
            pdf_res = client.get(pdf_url, headers=self.headers)
            pdf_res.raise_for_status()
            pdf_bytes = pdf_res.content

            # 4. Extract text via pypdf
            pdf_text = self._extract_pdf_text(pdf_bytes)

            # 5. Parse structured rows
            parsed_rows = parse_injury_report_text(pdf_text)
            items = [
                InjuryItem(
                    game_date=r.game_date,
                    matchup=r.matchup,
                    team=r.team,
                    player_name=r.player_name,
                    status=r.status,
                    reason=r.reason,
                    game_time=r.game_time,
                    availability_prob=r.availability_prob,
                )
                for r in parsed_rows
            ]

            report = InjuryReport(
                available=True,
                reason=None,
                fetched_at=now,
                rows=items,
            )

            # 6. Save on-disk cache
            self._write_cache(report)
            return report

        finally:
            if close_client:
                client.close()

    def _select_newest_pdf_url(self, html: str) -> Optional[str]:
        """Finds all injury report PDF links and returns the URL of the newest one."""
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
            ts = _parse_pdf_filename_timestamp(u)
            if ts:
                return (1, ts.timestamp())
            return (0, u)

        sorted_candidates = sorted(candidates, key=sort_key, reverse=True)
        return sorted_candidates[0]

    def _extract_pdf_text(self, pdf_bytes: bytes) -> str:
        """Extracts plain text from PDF bytes using pypdf."""
        reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
        pages_text = []
        for page in reader.pages:
            t = page.extract_text()
            if t:
                pages_text.append(t)
        return "\n".join(pages_text)
