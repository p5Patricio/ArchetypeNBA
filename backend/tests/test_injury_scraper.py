from datetime import datetime, timedelta, timezone
import inspect
import io
from pathlib import Path
import pytest
import httpx
from xhtml2pdf import pisa

from app.config import settings
from app.services import injury_scraper as injury_module
from app.services.injury_scraper import InjuryItem, InjuryReport, InjuryScraperService


def _create_sample_pdf_bytes(text: str) -> bytes:
    buf = io.BytesIO()
    pisa.CreatePDF(f"<html><body>{text}</body></html>", dest=buf)
    return buf.getvalue()


def test_injury_scraper_disabled_by_default(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "INJURY_PDF_ENABLED", False)
    scraper = InjuryScraperService(cache_file=tmp_path / "cache.json")
    report = scraper.fetch_injury_report()

    assert isinstance(report, InjuryReport)
    assert report.available is False
    assert report.reason == "disabled: NBA terms not cleared by the owner"
    assert report.rows == []


def test_no_fabricated_data_in_source_or_output(tmp_path, monkeypatch):
    """Agreements rule 3: never fabricate data."""
    # 1. Structural/source check
    source = inspect.getsource(injury_module)
    assert "_get_fallback_sample_report" not in source
    assert "Dallas Mavericks" not in source or "NBA_TEAMS" in source  # no hardcoded Mavericks Anthony Davis
    assert "LeBron James" not in source
    assert "Anthony Davis" not in source
    assert "Luka Doncic" not in source

    # 2. Method existence check
    scraper = InjuryScraperService(cache_file=tmp_path / "cache.json")
    assert not hasattr(scraper, "_get_fallback_sample_report")

    # 3. Behavioural check: when unavailable, rows is strictly empty
    monkeypatch.setattr(settings, "INJURY_PDF_ENABLED", False)
    report = scraper.fetch_injury_report()
    assert report.rows == []


def test_injury_scraper_enabled_with_mocked_http(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "INJURY_PDF_ENABLED", True)
    cache_file = tmp_path / "cache.json"

    page_html = """
    <html>
      <body>
        <a href="https://ak-static.cms.nba.com/referee/injury/Injury-Report_2026-10-28_05_00PM.pdf">Injury Report 5PM</a>
        <a href="https://ak-static.cms.nba.com/referee/injury/Injury-Report_2026-10-28_01_00PM.pdf">Injury Report 1PM</a>
      </body>
    </html>
    """

    pdf_body = "10/28/2026 07:00 (ET) BOS@DET Boston Celtics Brown, Jaylen Available Hamstring strain"
    pdf_bytes = _create_sample_pdf_bytes(pdf_body)

    requested_urls = []
    user_agents = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        user_agents.append(request.headers.get("User-Agent", ""))
        if "nba-injury-report-2026-27-season" in str(request.url):
            return httpx.Response(200, text=page_html)
        if "Injury-Report_2026-10-28_05_00PM.pdf" in str(request.url):
            return httpx.Response(200, content=pdf_bytes)
        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    scraper = InjuryScraperService(http_client=client, cache_file=cache_file)

    report = scraper.fetch_injury_report()

    assert report.available is True
    assert report.reason is None
    assert len(report.rows) == 1
    assert report.rows[0].player_name == "Jaylen Brown"
    assert report.rows[0].status == "Available"
    assert report.rows[0].availability_prob == 1.0

    # Verify honest user-agent was sent
    assert all("ArchetypeNBA-research/1.0" in ua for ua in user_agents)
    # Verify the newest PDF was chosen (5PM rather than 1PM)
    assert any("05_00PM.pdf" in url for url in requested_urls)
    assert not any("01_00PM.pdf" in url for url in requested_urls)

    # Verify cache file was created on disk
    assert cache_file.exists()


def test_injury_scraper_60_minute_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "INJURY_PDF_ENABLED", True)
    cache_file = tmp_path / "cache.json"

    # Pre-seed cache with a recent timestamp
    now = datetime.now(timezone.utc)
    recent_timestamp = (now - timedelta(minutes=20)).isoformat()
    scraper = InjuryScraperService(cache_file=cache_file)
    pre_report = InjuryReport(
        available=True,
        reason=None,
        fetched_at=datetime.fromisoformat(recent_timestamp),
        rows=[
            InjuryItem(
                game_date="2026-10-28",
                matchup="LAL@GSW",
                team="Golden State Warriors",
                player_name="Stephen Curry",
                status="Questionable",
                reason="Knee soreness",
                availability_prob=0.5,
            )
        ],
    )
    scraper._write_cache(pre_report)

    # An HTTP client that raises if called
    def failing_handler(request):
        raise RuntimeError("Network should not be touched when cache is valid")

    client = httpx.Client(transport=httpx.MockTransport(failing_handler))
    scraper.http_client = client

    # Fetch should read directly from cache without calling network
    cached = scraper.fetch_injury_report()
    assert cached.available is True
    assert len(cached.rows) == 1
    assert cached.rows[0].player_name == "Stephen Curry"


def test_injury_scraper_network_error_returns_unavailable(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "INJURY_PDF_ENABLED", True)
    cache_file = tmp_path / "cache.json"

    def error_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused by test")

    client = httpx.Client(transport=httpx.MockTransport(error_handler))
    scraper = InjuryScraperService(http_client=client, cache_file=cache_file)

    report = scraper.fetch_injury_report()
    assert report.available is False
    assert "error:" in report.reason
    assert report.rows == []
