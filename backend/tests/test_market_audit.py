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
    assert "Totals shadow model vs Pinnacle's close" in out


def test_market_audit_totals_shadow_model_section(world):
    from app.models import ModelPrediction, ModelVersion
    from app.services.model_registry import ensure_totals_shadow_model

    shadow = ensure_totals_shadow_model(world)

    # Game 1: 115 - 105 = 220 total points
    g1 = final_game(world, 115, 105, home="BOS", away="LAC", start=TIPOFF)
    add_marker(world, g1, kind=CAPTURE_CLOSING, at=CLOSING_AT)
    add_quote(world, g1, "pinnacle", MarketType.totals, BetSide.over, -110, line=215.5, captured_at=CLOSING_AT)
    add_quote(world, g1, "pinnacle", MarketType.totals, BetSide.under, -110, line=215.5, captured_at=CLOSING_AT)
    # Model predicted over 215.5 with prob 0.60, projection 222.0 -> actual 220, error = 220 - 222 = -2.0
    p1_over = ModelPrediction(
        model_version_id=shadow.id,
        game_id=g1.id,
        market=MarketType.totals,
        side=BetSide.over,
        line=Decimal("215.5"),
        model_prob=Decimal("0.60000"),
        projection=Decimal("222.00"),
    )
    p1_under = ModelPrediction(
        model_version_id=shadow.id,
        game_id=g1.id,
        market=MarketType.totals,
        side=BetSide.under,
        line=Decimal("215.5"),
        model_prob=Decimal("0.40000"),
        projection=Decimal("222.00"),
    )

    # Game 2: 100 - 95 = 195 total points
    g2 = final_game(world, 100, 95, home="NYK", away="LAL", start=TIPOFF)
    add_marker(world, g2, kind=CAPTURE_CLOSING, at=CLOSING_AT)
    add_quote(world, g2, "pinnacle", MarketType.totals, BetSide.over, -110, line=205.5, captured_at=CLOSING_AT)
    add_quote(world, g2, "pinnacle", MarketType.totals, BetSide.under, -110, line=205.5, captured_at=CLOSING_AT)
    # Model predicted over 205.5 with prob 0.35, projection 200.0 -> actual 195, error = 195 - 200 = -5.0
    p2_over = ModelPrediction(
        model_version_id=shadow.id,
        game_id=g2.id,
        market=MarketType.totals,
        side=BetSide.over,
        line=Decimal("205.5"),
        model_prob=Decimal("0.35000"),
        projection=Decimal("200.00"),
    )
    p2_under = ModelPrediction(
        model_version_id=shadow.id,
        game_id=g2.id,
        market=MarketType.totals,
        side=BetSide.under,
        line=Decimal("205.5"),
        model_prob=Decimal("0.65000"),
        projection=Decimal("200.00"),
    )
    world.add_all([p1_over, p1_under, p2_over, p2_under])
    world.commit()

    from app.services.market_audit import audit_totals_shadow
    shadow_audit = audit_totals_shadow(world)
    assert shadow_audit.n_games == 2
    assert shadow_audit.brier_model is not None
    assert shadow_audit.brier_pinnacle is not None
    assert shadow_audit.mean_total_error == pytest.approx((-2.0 + -5.0) / 2.0)
    assert shadow_audit.sd_total_error is not None

    text = format_market_audit(run_market_audit(world))
    assert "3. Totals shadow model vs Pinnacle's close:" in text
    assert "insufficient data (n = 2 < 30)" in text
    assert "Brier: model" in text
    assert "Model total error (actual - mu): mean = -3.50 pts" in text


def test_market_audit_totals_shadow_30_games_shows_full_ci(world):
    from app.models import ModelPrediction
    from app.services.model_registry import ensure_totals_shadow_model

    shadow = ensure_totals_shadow_model(world)
    # Create 30 settled games
    preds = []
    for i in range(30):
        total = 210 + (i % 20)
        h_score = total // 2
        a_score = total - h_score
        t_start = TIPOFF + timedelta(days=i + 1)
        t_closing = t_start - timedelta(minutes=15)
        g = final_game(world, h_score, a_score, home="BOS", away="LAC", start=t_start)
        add_marker(world, g, kind=CAPTURE_CLOSING, at=t_closing)
        line = 215.5
        add_quote(world, g, "pinnacle", MarketType.totals, BetSide.over, -110, line=line, captured_at=t_closing)
        add_quote(world, g, "pinnacle", MarketType.totals, BetSide.under, -110, line=line, captured_at=t_closing)
        p_over = ModelPrediction(
            model_version_id=shadow.id,
            game_id=g.id,
            market=MarketType.totals,
            side=BetSide.over,
            line=Decimal(str(line)),
            model_prob=Decimal("0.55000"),
            projection=Decimal("218.00"),
        )
        p_under = ModelPrediction(
            model_version_id=shadow.id,
            game_id=g.id,
            market=MarketType.totals,
            side=BetSide.under,
            line=Decimal(str(line)),
            model_prob=Decimal("0.45000"),
            projection=Decimal("218.00"),
        )
        preds.extend([p_over, p_under])
    world.add_all(preds)
    world.commit()

    text = format_market_audit(run_market_audit(world))
    assert "n = 30 games" in text
    assert "95% CI" in text
    assert "insufficient data" not in text
