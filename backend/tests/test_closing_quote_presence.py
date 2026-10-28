from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlmodel import select

from app.models import (
    CAPTURE_CLOSING,
    CAPTURE_OPENING,
    BetSide,
    MarketType,
    OddsCapturePresence,
    OddsHistory,
    OddsSnapshotCapture,
    SimulatedBet,
    StakingStrategy,
)
from app.services.clv_report import build_pinnacle_clv_report
from app.services.odds_api_service import GameQuote
from app.services.odds_ingestion import OddsIngestionService
from app.services.odds_snapshot import run_snapshot
from app.services.paper_report import build_report, format_report
from app.services.settlement import fill_clv
from tests.test_odds_snapshot import NOW as SNAPSHOT_NOW, FakeService, _event
from tests.test_settlement import (  # noqa: F401 (world fixture)
    CLOSING_AT,
    NOW,
    PLACED,
    TIPOFF,
    add_game,
    add_marker,
    add_quote,
    place_bet,
    reload,
    world,
)


def _presence_rows(session, capture_id=None):
    stmt = select(OddsCapturePresence)
    if capture_id is not None:
        stmt = stmt.where(OddsCapturePresence.capture_id == capture_id)
    return session.exec(stmt).all()


def test_presence_rows_written_for_closing_capture_only(world):
    events = [_event("g1", 10)]
    service = FakeService(events)

    # Opening run: no presence rows should be written
    run_snapshot(world, service, "opening", props_events=0, now=SNAPSHOT_NOW)
    assert len(_presence_rows(world)) == 0

    # Closing run: presence rows should be written for quotes seen in the payload
    second = FakeService(events)
    run_snapshot(world, second, "closing", props_events=0, now=SNAPSHOT_NOW + timedelta(minutes=1))

    closing_markers = world.exec(
        select(OddsSnapshotCapture).where(OddsSnapshotCapture.kind == CAPTURE_CLOSING)
    ).all()
    assert len(closing_markers) == 1
    presence = _presence_rows(world, closing_markers[0].id)
    # FakeService provides 2 quotes for the event: home (-150) and away (130) h2h Pinnacle
    assert len(presence) == 2
    assert {p.side for p in presence} == {BetSide.home, BetSide.away}
    assert all(p.market == MarketType.h2h and p.line is None for p in presence)


def test_presence_reingest_is_idempotent(world):
    events = [_event("g1", 10)]
    service = FakeService(events)
    run_snapshot(world, service, "closing", props_events=0, now=SNAPSHOT_NOW)

    closing_markers = world.exec(
        select(OddsSnapshotCapture).where(OddsSnapshotCapture.kind == CAPTURE_CLOSING)
    ).all()
    assert len(closing_markers) == 1
    initial_count = len(_presence_rows(world, closing_markers[0].id))
    assert initial_count == 2

    # Re-ingest the exact same payload through OddsIngestionService directly
    ingestion = OddsIngestionService(world)
    quotes = service.fetch_game_lines()
    inserted = ingestion.ingest_capture_presence(closing_markers[0].id, closing_markers[0].game_id, quotes)
    assert inserted == 0
    assert len(_presence_rows(world, closing_markers[0].id)) == initial_count


def test_absent_quote_at_close_leaves_clv_null_and_counts_in_settlement(world):
    game = add_game(world)
    # Bet placed at FanDuel on h2h home
    bet = place_bet(world, game, MarketType.h2h, BetSide.home, book="fanduel", price="2.0000", placed_at=PLACED)

    # Game has a closing marker
    add_marker(world, game, kind=CAPTURE_CLOSING, at=CLOSING_AT)
    closing_marker = world.exec(
        select(OddsSnapshotCapture).where(
            OddsSnapshotCapture.game_id == game.id, OddsSnapshotCapture.kind == CAPTURE_CLOSING
        )
    ).first()

    # Presence rows exist for the closing capture, but ONLY Pinnacle was present (FanDuel dropped the market)
    world.add(
        OddsCapturePresence(
            capture_id=closing_marker.id,
            game_id=game.id,
            sportsbook_id=world.books["pinnacle"].id,
            market=MarketType.h2h,
            side=BetSide.home,
            line=None,
        )
    )
    world.commit()

    # Old quote of FanDuel exists in odds_history (from when the bet was placed)
    summary = fill_clv(world, NOW)

    assert summary.absent_at_close == 1
    assert summary.filled == 0
    bet = reload(world, bet)
    assert bet.closing_price is None
    assert bet.closing_line is None
    assert bet.clv_pct is None


def test_present_quote_at_close_calculates_clv_unchanged(world):
    game = add_game(world)
    bet = place_bet(world, game, MarketType.h2h, BetSide.home, book="pinnacle", price="2.0000", placed_at=PLACED)
    add_quote(world, game, "pinnacle", MarketType.h2h, BetSide.home, -125, captured_at=CLOSING_AT)

    add_marker(world, game, kind=CAPTURE_CLOSING, at=CLOSING_AT)
    closing_marker = world.exec(
        select(OddsSnapshotCapture).where(
            OddsSnapshotCapture.game_id == game.id, OddsSnapshotCapture.kind == CAPTURE_CLOSING
        )
    ).first()

    # Presence records that Pinnacle h2h home WAS present in the closing capture
    world.add(
        OddsCapturePresence(
            capture_id=closing_marker.id,
            game_id=game.id,
            sportsbook_id=world.books["pinnacle"].id,
            market=MarketType.h2h,
            side=BetSide.home,
            line=None,
        )
    )
    world.commit()

    summary = fill_clv(world, NOW)
    assert summary.filled == 1
    assert summary.absent_at_close == 0
    bet = reload(world, bet)
    assert bet.closing_price == Decimal("1.8000")
    assert bet.clv_pct is not None


def test_legacy_capture_without_presence_rows_keeps_old_behavior(world):
    # A capture made before this release has NO presence rows at all
    game = add_game(world)
    bet = place_bet(world, game, MarketType.h2h, BetSide.home, book="pinnacle", price="2.0000", placed_at=PLACED)
    add_quote(world, game, "pinnacle", MarketType.h2h, BetSide.home, -125, captured_at=CLOSING_AT)
    add_marker(world, game, kind=CAPTURE_CLOSING, at=CLOSING_AT)

    # Verify no presence rows exist
    assert len(_presence_rows(world)) == 0

    summary = fill_clv(world, NOW)
    assert summary.filled == 1
    assert summary.absent_at_close == 0
    bet = reload(world, bet)
    assert bet.closing_price == Decimal("1.8000")


def test_pinnacle_clv_report_counts_absent_at_close_exclusion(world):
    game = add_game(world, "BOS", "LAC", start=TIPOFF)
    add_marker(world, game, at=CLOSING_AT)
    closing_marker = world.exec(
        select(OddsSnapshotCapture).where(
            OddsSnapshotCapture.game_id == game.id, OddsSnapshotCapture.kind == CAPTURE_CLOSING
        )
    ).first()

    place_bet(world, game, MarketType.h2h, BetSide.home, price="2.0000", placed_at=PLACED)
    # Pinnacle had quotes in history earlier
    add_quote(world, game, "pinnacle", MarketType.h2h, BetSide.home, -200, captured_at=CLOSING_AT - timedelta(hours=2))
    add_quote(world, game, "pinnacle", MarketType.h2h, BetSide.away, 170, captured_at=CLOSING_AT - timedelta(hours=2))

    # But at closing, presence rows exist for this capture and Pinnacle did NOT quote h2h (e.g. only spreads)
    world.add(
        OddsCapturePresence(
            capture_id=closing_marker.id,
            game_id=game.id,
            sportsbook_id=world.books["pinnacle"].id,
            market=MarketType.spreads,
            side=BetSide.home,
            line=Decimal("-3.5"),
        )
    )
    world.commit()

    report = build_pinnacle_clv_report(world, NOW)
    assert report.total_bets == 1
    assert report.games_count == 0
    assert report.exclusions.absent_at_close == 1
    assert report.exclusions.total == 1


def test_paper_report_coverage_section_displays_absent_at_close(world):
    game = add_game(world, "BOS", "LAC", start=TIPOFF)
    add_marker(world, game, at=CLOSING_AT)
    closing_marker = world.exec(
        select(OddsSnapshotCapture).where(
            OddsSnapshotCapture.game_id == game.id, OddsSnapshotCapture.kind == CAPTURE_CLOSING
        )
    ).first()

    # Bet placed at FanDuel
    place_bet(world, game, MarketType.h2h, BetSide.home, book="fanduel", price="2.0000", placed_at=PLACED)

    # Presence rows exist for the game, but FanDuel h2h home is absent
    world.add(
        OddsCapturePresence(
            capture_id=closing_marker.id,
            game_id=game.id,
            sportsbook_id=world.books["pinnacle"].id,
            market=MarketType.h2h,
            side=BetSide.home,
            line=None,
        )
    )
    world.commit()

    # Run fill_clv
    fill_clv(world, NOW)

    report = build_report(world, NOW)
    assert report.clv.bets_absent_at_close == 1
    text = format_report(report)
    assert "Quotes absent at close: 1 bet(s) dropped before tip-off." in text


def test_migration_sql_generates_offline():
    import os
    import subprocess
    import sys
    from pathlib import Path

    backend_dir = Path(__file__).resolve().parents[1]
    res = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "e3f8b1a4c9d2:head", "--sql"],
        cwd=backend_dir,
        capture_output=True,
        text=True,
        env={**os.environ, "DATABASE_URL": "postgresql://dummy:dummy@localhost:5432/dummy"},
    )
    assert res.returncode == 0, f"Alembic failed: {res.stderr}"
    assert "CREATE TABLE odds_capture_presence" in res.stdout
    assert "uq_odds_capture_presence_quote" in res.stdout
    assert "v_closing_odds" in res.stdout

