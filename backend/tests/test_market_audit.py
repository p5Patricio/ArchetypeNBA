import importlib.util
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import pytest

from app.models import (
    CAPTURE_CLOSING,
    CAPTURE_CLOSING_PROPS,
    BetSide,
    MarketType,
    OddsHistory,
    OddsSnapshotCapture,
    Player,
)
from app.services.market_audit import (
    audit_closing_totals,
    audit_prop_vig,
    format_market_audit,
    run_market_audit,
)
from tests.test_settlement import (  # noqa: F401 (world fixture)
    CLOSING_AT,
    NOW,
    TIPOFF,
    add_game,
    add_marker,
    add_quote,
    final_game,
    world,
)


def test_market_audit_empty_db_degrades_gracefully(world):
    result = run_market_audit(world)
    assert result.totals.n_games == 0
    assert result.totals.mean_error is None
    assert result.props.n_pairs == 0
    assert result.props.mean_vig is None

    text = format_market_audit(result)
    assert "no data (no settled games with closing totals quotes)" in text
    assert "no data (no over/under closing prop pairs)" in text


def test_market_audit_totals_error(world):
    # Game 1: 110 - 100 = 210, closing total 215.5 -> error -5.5
    g1 = final_game(world, 110, 100, home="BOS", away="LAC", start=TIPOFF)
    add_marker(world, g1, kind=CAPTURE_CLOSING, at=CLOSING_AT)
    add_quote(world, g1, "pinnacle", MarketType.totals, BetSide.over, -110, line=215.5, captured_at=CLOSING_AT)

    # Game 2: 120 - 110 = 230, closing total 225.0 -> error +5.0
    g2 = final_game(world, 120, 110, home="NYK", away="LAL", start=TIPOFF)
    add_marker(world, g2, kind=CAPTURE_CLOSING, at=CLOSING_AT)
    add_quote(world, g2, "pinnacle", MarketType.totals, BetSide.over, -110, line=225.0, captured_at=CLOSING_AT)

    # Game 3: not final (scheduled) -> excluded
    g3 = add_game(world, "LAC", "NYK", start=TIPOFF)
    add_marker(world, g3, kind=CAPTURE_CLOSING, at=CLOSING_AT)
    add_quote(world, g3, "pinnacle", MarketType.totals, BetSide.over, -110, line=220.0, captured_at=CLOSING_AT)

    totals = audit_closing_totals(world)
    assert totals.n_games == 2
    assert totals.mean_error == pytest.approx((-5.5 + 5.0) / 2.0)
    assert totals.std_dev is not None

    text = format_market_audit(run_market_audit(world))
    assert "n = 2 games" in text
    assert "mean error = -0.25 pts" in text


def test_market_audit_prop_vig(world):
    game = add_game(world, "BOS", "LAC", start=TIPOFF)
    add_marker(world, game, kind=CAPTURE_CLOSING_PROPS, at=CLOSING_AT)

    player = Player(full_name="Jayson Tatum")
    world.add(player)
    world.commit()

    # Over 25.5 points at -110, Under 25.5 points at -110
    q_over = OddsHistory(
        game_id=game.id,
        sportsbook_id=world.books["pinnacle"].id,
        market=MarketType.player_points if hasattr(MarketType, "player_points") else "player_points",
        side=BetSide.over,
        line=Decimal("25.5"),
        price_american=-110,
        player_id=player.id,
        captured_at=CLOSING_AT,
        book_last_update=CLOSING_AT,
    )
    q_under = OddsHistory(
        game_id=game.id,
        sportsbook_id=world.books["pinnacle"].id,
        market=MarketType.player_points if hasattr(MarketType, "player_points") else "player_points",
        side=BetSide.under,
        line=Decimal("25.5"),
        price_american=-110,
        player_id=player.id,
        captured_at=CLOSING_AT,
        book_last_update=CLOSING_AT,
    )
    world.add_all([q_over, q_under])
    world.commit()

    props = audit_prop_vig(world)
    assert props.n_pairs == 1
    # -110 is decimal 1.909: (1/1.909 + 1/1.909) - 1.0 = 0.04766...
    expected_vig = (1.0 / 1.909 + 1.0 / 1.909) - 1.0
    assert props.mean_vig == pytest.approx(expected_vig, abs=1e-4)
    assert props.median_vig == pytest.approx(expected_vig, abs=1e-4)

    text = format_market_audit(run_market_audit(world))
    assert "n = 1 pairs" in text
    assert "mean vig = 4.77%" in text


def test_market_audit_cli_main(world, capsys):
    spec = importlib.util.spec_from_file_location(
        "market_audit_cli", Path(__file__).resolve().parent.parent / "scripts" / "market_audit.py"
    )
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)

    assert cli.main(session_factory=lambda: nullcontext(world)) == 0
    out = capsys.readouterr().out
    assert "Market Audit Report" in out
    assert "Closing-total error" in out
    assert "Player-prop closing quotes" in out
