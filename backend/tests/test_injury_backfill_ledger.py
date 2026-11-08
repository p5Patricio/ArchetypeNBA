import importlib.util
import os
import subprocess
import sys
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import List

import httpx
import pytest
from sqlmodel import Session, select

from app.models import (
    InjuryBackfillSlot,
    Player,
    PlayerGameLog,
    Season,
    Team,
)
from app.services.injury_report_service import (
    backfill_injury_reports,
    build_injury_pdf_url,
    plan_backfill,
)
from scripts.backfill_injuries import build_parser, format_summary

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
LAYOUT_FIXTURES_DIR = FIXTURES_DIR / "injury_layouts"

PARSE_FAIL_TEXT = (
    "Game Date Game Time Matchup Team Player Name Status Notes\n"
    "01/15/2019 07:00 (ET) MIN@PHI Minnesota Timberwolves Covington, Robert Out Knee\n"
)

NOW = datetime(2026, 11, 7, 12, 0, tzinfo=timezone.utc)


def _load_layout_fixture(name: str) -> str:
    return (LAYOUT_FIXTURES_DIR / name).read_text(encoding="utf-8")


def _seed_game_day(
    session: Session,
    game_date: date = date(2019, 1, 15),
    game_id: str = "0021800640",
) -> None:
    season = session.exec(select(Season).where(Season.season_label == "2018-19")).first()
    if not season:
        season = Season(season_label="2018-19", is_active=False)
        session.add(season)

    min_team = session.exec(select(Team).where(Team.abbreviation == "MIN")).first()
    if not min_team:
        min_team = Team(
            abbreviation="MIN",
            full_name="Minnesota Timberwolves",
            city="Minneapolis",
            conference="West",
            division="NW",
        )
        session.add(min_team)

    phi_team = session.exec(select(Team).where(Team.abbreviation == "PHI")).first()
    if not phi_team:
        phi_team = Team(
            abbreviation="PHI",
            full_name="Philadelphia 76ers",
            city="Philadelphia",
            conference="East",
            division="Atlantic",
        )
        session.add(phi_team)

    covington = session.exec(select(Player).where(Player.full_name == "Robert Covington")).first()
    if not covington:
        covington = Player(full_name="Robert Covington")
        session.add(covington)

    session.flush()

    session.add(
        PlayerGameLog(
            player_id=covington.id,
            team_id=min_team.id,
            season_id=season.id,
            game_id=game_id,
            game_date=game_date,
            matchup="MIN @ PHI",
            min=34,
        )
    )
    session.commit()


def test_parse_failure_recorded_then_skipped_then_retried(db_session: Session):
    session = db_session
    target_date = date(2019, 1, 15)
    _seed_game_day(session, game_date=target_date)

    requested_urls: List[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url_str = str(request.url)
        requested_urls.append(url_str)
        if url_str.endswith("_2019-01-15_05PM.pdf"):
            return httpx.Response(200, content=b"%PDF fake")
        return httpx.Response(403, content=b"Forbidden")

    mock_client = httpx.Client(transport=httpx.MockTransport(handler))
    valid_text = _load_layout_fixture("category_columns_2019-01-15.txt")

    # Run 1: parse failure on 05PM; pre_tip reuses 05PM without a new request
    summary1 = backfill_injury_reports(
        session=session,
        start_date=target_date,
        end_date=target_date,
        per_day=2,
        use_index_pages=False,
        http_client=mock_client,
        pdf_text_extractor=lambda _: PARSE_FAIL_TEXT,
        sleep_fn=lambda _: None,
        now=NOW,
    )
    assert summary1.parse_failures == 1
    assert summary1.requested == 3
    assert len(requested_urls) == 3

    ledger1 = session.exec(
        select(InjuryBackfillSlot).where(InjuryBackfillSlot.game_date == target_date)
    ).all()
    assert len(ledger1) == 2
    for row in ledger1:
        assert row.outcome == "parse_failed"
        assert row.url is not None and row.url.endswith("_05PM.pdf")
        assert row.layout_header == "Status Notes"
        assert row.attempts == 1
        assert row.last_attempted_at is not None

    # Run 2: same extractor, skipped parse failed slots
    requested_urls.clear()
    summary2 = backfill_injury_reports(
        session=session,
        start_date=target_date,
        end_date=target_date,
        per_day=2,
        use_index_pages=False,
        http_client=mock_client,
        pdf_text_extractor=lambda _: PARSE_FAIL_TEXT,
        sleep_fn=lambda _: None,
        now=NOW,
    )
    assert summary2.requested == 0
    assert summary2.skipped_parse_failed == 2
    assert summary2.coverage["2018-19"].failed == 2
    assert summary2.coverage["2018-19"].remaining == 0

    # Run 3: retry_failed=True with valid fixture extractor
    requested_urls.clear()
    summary3 = backfill_injury_reports(
        session=session,
        start_date=target_date,
        end_date=target_date,
        per_day=2,
        use_index_pages=False,
        retry_failed=True,
        http_client=mock_client,
        pdf_text_extractor=lambda _: valid_text,
        sleep_fn=lambda _: None,
        now=NOW,
    )
    assert summary3.requested == 1
    assert summary3.stored == 1

    ledger3 = session.exec(
        select(InjuryBackfillSlot).where(InjuryBackfillSlot.game_date == target_date)
    ).all()
    assert len(ledger3) == 2
    for row in ledger3:
        assert row.outcome == "stored"
        assert row.snapshot_id is not None
        assert row.attempts == 2

    # Under app/services/injury_report_service.py:996-998 and 1032-1033, once the 5 PM report is stored
    # and reveals the 19:00 ET tip-off, the pre-tip slot resolves to the same 5 PM file (_05PM.pdf) and is
    # dropped during planning. Thus the refreshed plan has 1 planned slot for 2018-19, yielding stored == 1.
    assert summary3.coverage["2018-19"].stored == 1

    # Run 4: no flags, already stored
    requested_urls.clear()
    summary4 = backfill_injury_reports(
        session=session,
        start_date=target_date,
        end_date=target_date,
        per_day=2,
        use_index_pages=False,
        http_client=mock_client,
        pdf_text_extractor=lambda _: valid_text,
        sleep_fn=lambda _: None,
        now=NOW,
    )
    assert summary4.requested == 0


def test_missing_slots_skipped_unless_retry_missing(db_session: Session):
    session = db_session
    target_date = date(2019, 1, 15)
    _seed_game_day(session, game_date=target_date)

    requested_urls: List[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        return httpx.Response(403, content=b"Forbidden")

    mock_client = httpx.Client(transport=httpx.MockTransport(handler))

    # Run 1
    summary1 = backfill_injury_reports(
        session=session,
        start_date=target_date,
        end_date=target_date,
        per_day=2,
        use_index_pages=False,
        http_client=mock_client,
        sleep_fn=lambda _: None,
        now=NOW,
    )
    assert summary1.requested == 5
    assert summary1.missing_slots == 2

    ledger1 = session.exec(
        select(InjuryBackfillSlot).where(InjuryBackfillSlot.game_date == target_date)
    ).all()
    assert len(ledger1) == 2
    for row in ledger1:
        assert row.outcome == "missing"
        assert row.http_status == 403
        assert row.url is not None and row.url.endswith(".pdf")
        assert row.attempts == 1

    # Run 2: skipped without flags
    requested_urls.clear()
    summary2 = backfill_injury_reports(
        session=session,
        start_date=target_date,
        end_date=target_date,
        per_day=2,
        use_index_pages=False,
        http_client=mock_client,
        sleep_fn=lambda _: None,
        now=NOW,
    )
    assert summary2.requested == 0
    assert summary2.skipped_missing == 2
    assert summary2.coverage["2018-19"].missing == 2

    # Run 3: retry_failed=True only does not retry missing
    requested_urls.clear()
    summary3 = backfill_injury_reports(
        session=session,
        start_date=target_date,
        end_date=target_date,
        per_day=2,
        use_index_pages=False,
        retry_failed=True,
        http_client=mock_client,
        sleep_fn=lambda _: None,
        now=NOW,
    )
    assert summary3.requested == 0

    # Run 4: retry_missing=True retries all missing slots
    requested_urls.clear()
    summary4 = backfill_injury_reports(
        session=session,
        start_date=target_date,
        end_date=target_date,
        per_day=2,
        use_index_pages=False,
        retry_missing=True,
        http_client=mock_client,
        sleep_fn=lambda _: None,
        now=NOW,
    )
    assert summary4.requested == 5
    assert summary4.retried_missing == 2

    ledger4 = session.exec(
        select(InjuryBackfillSlot).where(InjuryBackfillSlot.game_date == target_date)
    ).all()
    assert len(ledger4) == 2
    for row in ledger4:
        assert row.attempts == 2


def test_http_error_slots_are_retried_automatically(db_session: Session):
    session = db_session
    target_date = date(2019, 1, 15)
    _seed_game_day(session, game_date=target_date)

    def handler(request: httpx.Request) -> httpx.Response:
        url_str = str(request.url)
        if "_2019-01-15_05PM" in url_str:
            raise httpx.ConnectTimeout("t")
        return httpx.Response(404)

    mock_client = httpx.Client(transport=httpx.MockTransport(handler))

    # Run 1: per_day=1
    summary1 = backfill_injury_reports(
        session=session,
        start_date=target_date,
        end_date=target_date,
        per_day=1,
        use_index_pages=False,
        http_client=mock_client,
        sleep_fn=lambda _: None,
        now=NOW,
    )
    assert summary1.http_errors == 1

    row = session.exec(
        select(InjuryBackfillSlot).where(
            InjuryBackfillSlot.game_date == target_date,
            InjuryBackfillSlot.slot == "five_pm",
        )
    ).first()
    assert row is not None
    assert row.outcome == "http_error"

    # Run 2: no flags, same handler
    summary2 = backfill_injury_reports(
        session=session,
        start_date=target_date,
        end_date=target_date,
        per_day=1,
        use_index_pages=False,
        http_client=mock_client,
        sleep_fn=lambda _: None,
        now=NOW,
    )
    assert summary2.retried_http_error == 1
    assert summary2.requested >= 1


def test_reparse_failed_only_plans_only_parse_failures(db_session: Session):
    session = db_session
    _seed_game_day(session, game_date=date(2019, 1, 14), game_id="0021800641")
    _seed_game_day(session, game_date=date(2019, 1, 15), game_id="0021800642")
    _seed_game_day(session, game_date=date(2019, 1, 16), game_id="0021800643")

    url_14 = build_injury_pdf_url(date(2019, 1, 14), time(17, 0), hourly=True)
    slot_14 = InjuryBackfillSlot(
        game_date=date(2019, 1, 14),
        slot="five_pm",
        outcome="parse_failed",
        url=url_14,
        attempts=1,
        first_attempted_at=NOW,
        last_attempted_at=NOW,
    )
    slot_15 = InjuryBackfillSlot(
        game_date=date(2019, 1, 15),
        slot="five_pm",
        outcome="missing",
        attempts=1,
        first_attempted_at=NOW,
        last_attempted_at=NOW,
    )
    session.add_all([slot_14, slot_15])
    session.commit()

    # With reparse_failed_only=True
    plan1 = plan_backfill(
        session,
        start_date=date(2019, 1, 14),
        end_date=date(2019, 1, 16),
        per_day=1,
        reparse_failed_only=True,
    )
    assert len(plan1.slots) == 1
    assert plan1.slots[0].game_date == date(2019, 1, 14)
    assert plan1.slots[0].primary_url == url_14

    cov = plan1.coverage["2018-19"]
    assert cov.failed == 1
    assert cov.missing == 1
    assert cov.remaining == 1

    # Without flags: only 2019-01-16 planned
    plan2 = plan_backfill(
        session,
        start_date=date(2019, 1, 14),
        end_date=date(2019, 1, 16),
        per_day=1,
    )
    assert len(plan2.slots) == 1
    assert plan2.slots[0].game_date == date(2019, 1, 16)


def test_cap_reached_mid_slot_records_nothing(db_session: Session):
    session = db_session
    target_date = date(2019, 1, 15)
    _seed_game_day(session, game_date=target_date)

    mock_client = httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(403)))

    summary1 = backfill_injury_reports(
        session=session,
        start_date=target_date,
        end_date=target_date,
        per_day=1,
        max_requests=2,
        use_index_pages=False,
        http_client=mock_client,
        sleep_fn=lambda _: None,
        now=NOW,
    )
    assert summary1.cap_reached is True
    ledger1 = session.exec(select(InjuryBackfillSlot)).all()
    assert len(ledger1) == 0

    summary2 = backfill_injury_reports(
        session=session,
        start_date=target_date,
        end_date=target_date,
        per_day=1,
        max_requests=3,
        use_index_pages=False,
        http_client=mock_client,
        sleep_fn=lambda _: None,
        now=NOW,
    )
    ledger2 = session.exec(select(InjuryBackfillSlot)).all()
    assert len(ledger2) == 1
    assert ledger2[0].outcome == "missing"


def test_dry_run_writes_no_ledger_rows(db_session: Session):
    session = db_session
    target_date = date(2019, 1, 15)
    _seed_game_day(session, game_date=target_date)

    def failing_handler(request: httpx.Request) -> httpx.Response:
        pytest.fail("HTTP handler should not be called in dry run")

    mock_client = httpx.Client(transport=httpx.MockTransport(failing_handler))

    summary = backfill_injury_reports(
        session=session,
        start_date=target_date,
        end_date=target_date,
        per_day=2,
        dry_run=True,
        use_index_pages=False,
        http_client=mock_client,
        sleep_fn=lambda _: None,
        now=NOW,
    )
    ledger = session.exec(select(InjuryBackfillSlot)).all()
    assert len(ledger) == 0
    assert summary.coverage["2018-19"].remaining == 2


def test_cli_flags_and_coverage_summary(db_session: Session):
    parser = build_parser()
    defaults = parser.parse_args([])
    assert defaults.retry_failed is False
    assert defaults.retry_missing is False
    assert defaults.reparse_failed_only is False

    args = parser.parse_args(["--retry-failed", "--retry-missing", "--reparse-failed-only"])
    assert args.retry_failed is True
    assert args.retry_missing is True
    assert args.reparse_failed_only is True

    session = db_session
    target_date = date(2019, 1, 15)
    _seed_game_day(session, game_date=target_date)

    def failing_handler(request: httpx.Request) -> httpx.Response:
        pytest.fail("HTTP handler should not be called in dry run")

    mock_client = httpx.Client(transport=httpx.MockTransport(failing_handler))

    summary = backfill_injury_reports(
        session=session,
        start_date=target_date,
        end_date=target_date,
        per_day=2,
        dry_run=True,
        use_index_pages=False,
        http_client=mock_client,
        sleep_fn=lambda _: None,
        now=NOW,
    )

    formatted = format_summary(summary)
    assert "Coverage by season" in formatted
    lines = [line for line in formatted.splitlines() if line.startswith("    2018-19")]
    assert len(lines) >= 1


def test_migration_revision_chain():
    backend_dir = Path(__file__).resolve().parents[1]
    migration_path = backend_dir / "alembic" / "versions" / "a4d6f8b0c3e5_add_injury_backfill_slot.py"

    spec = importlib.util.spec_from_file_location("migration_a4d6f8b0c3e5", migration_path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    assert mod.revision == "a4d6f8b0c3e5"
    assert mod.down_revision == "f3c5e7a9b2d4"

    res = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "f3c5e7a9b2d4:head", "--sql"],
        cwd=backend_dir,
        capture_output=True,
        text=True,
        env={**os.environ, "DATABASE_URL": "postgresql://dummy:dummy@localhost:5432/dummy"},
    )
    assert res.returncode == 0, f"Alembic failed: {res.stderr}"
    assert "CREATE TABLE injury_backfill_slot" in res.stdout
    assert "uq_injury_backfill_slot" in res.stdout
    assert "ck_injury_backfill_slot_outcome" in res.stdout
