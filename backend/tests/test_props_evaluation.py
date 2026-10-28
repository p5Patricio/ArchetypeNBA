from datetime import datetime, timedelta, timezone
from decimal import Decimal
import pytest
from sqlmodel import select

from app.models import (
    CAPTURE_CLOSING_PROPS,
    BetSide,
    MarketType,
    ModelPrediction,
    ModelVersion,
    OddsHistory,
    OddsSnapshotCapture,
    Player,
    PlayerGameLog,
)
from app.services.market_audit import (
    audit_props_shadow,
    format_market_audit,
    run_market_audit,
)
from app.services.model_registry import ensure_props_shadow_model, get_champion, list_active
from app.services import model_promotion, league_report
from app.services.paper_report import build_report, format_report
from tests.test_settlement import (  # noqa: F401 (world fixture)
    CLOSING_AT,
    NOW,
    TIPOFF,
    add_game,
    add_marker,
    final_game,
    world,
)


def test_props_shadow_evaluation_hand_calculated_synthetic(world):
    """
    Verification of settlement-free props evaluation with hand-calculated exact numbers:
    - Player 1: pts line 20.5, book -110/-110 (fair=0.50), model 0.60, actual 25 -> y=1 (over)
      Brier model = (0.60-1)^2 = 0.1600, Brier book = (0.50-1)^2 = 0.2500
    - Player 2: reb line 7.5, book +100/-120 (fair=0.478261), model 0.40, actual 5 -> y=0 (under)
      Brier model = (0.40-0)^2 = 0.1600, Brier book = (0.478261-0)^2 = 0.228733
    - Player 3: ast line 5.0, actual 5 -> push (excluded from Brier/log loss)
    - Player 4: pra line 35.5, no game log -> VOID
    - Player 5: pts line 15.5, game log min=0 -> VOID
    - Unmatched capture marker: quotes_seen=10, quotes_inserted=8 -> 2 unmatched names
    """
    shadow = ensure_props_shadow_model(world)
    g = final_game(world, 110, 100, home="BOS", away="LAC", start=TIPOFF)
    g.nba_game_id = "0022600001"
    world.add(g)

    # Marker with uninserted quotes (unmatched names)
    add_marker(world, g, kind=CAPTURE_CLOSING_PROPS, at=CLOSING_AT)
    marker = world.execute(
        select(OddsSnapshotCapture)
        .where(OddsSnapshotCapture.game_id == g.id)
        .where(OddsSnapshotCapture.kind == CAPTURE_CLOSING_PROPS)
    ).scalar_one()
    marker.quotes_seen = 10
    marker.quotes_inserted = 8
    world.add(marker)

    # Create players
    p1 = Player(full_name="Player One")
    p2 = Player(full_name="Player Two")
    p3 = Player(full_name="Player Three")
    p4 = Player(full_name="Player Four")
    p5 = Player(full_name="Player Five")
    world.add_all([p1, p2, p3, p4, p5])
    world.commit()

    # Create player game logs
    # Player 1: played 32 min, 25 pts
    log1 = PlayerGameLog(
        player_id=p1.id,
        team_id=world.teams["BOS"].id,
        season_id=world.season.id,
        game_id=g.nba_game_id,
        min=32,
        pts=25,
        reb=5,
        ast=3,
    )
    # Player 2: played 28 min, 5 reb
    log2 = PlayerGameLog(
        player_id=p2.id,
        team_id=world.teams["LAC"].id,
        season_id=world.season.id,
        game_id=g.nba_game_id,
        min=28,
        pts=12,
        reb=5,
        ast=2,
    )
    # Player 3: played 30 min, 5 ast (push on line 5.0)
    log3 = PlayerGameLog(
        player_id=p3.id,
        team_id=world.teams["BOS"].id,
        season_id=world.season.id,
        game_id=g.nba_game_id,
        min=30,
        pts=15,
        reb=4,
        ast=5,
    )
    # Player 5: played 0 min (DNP / VOID)
    log5 = PlayerGameLog(
        player_id=p5.id,
        team_id=world.teams["LAC"].id,
        season_id=world.season.id,
        game_id=g.nba_game_id,
        min=0,
        pts=0,
        reb=0,
        ast=0,
    )
    # Player 4 has NO log (DNP / VOID)
    world.add_all([log1, log2, log3, log5])
    world.commit()

    book = world.books["pinnacle"]

    # 1. Player 1: pts line 20.5 (-110/-110)
    world.add_all([
        OddsHistory(
            game_id=g.id,
            sportsbook_id=book.id,
            market=MarketType.player_points,
            side=BetSide.over,
            line=Decimal("20.5"),
            price_american=-110,
            player_id=p1.id,
            captured_at=CLOSING_AT,
            book_last_update=CLOSING_AT,
        ),
        OddsHistory(
            game_id=g.id,
            sportsbook_id=book.id,
            market=MarketType.player_points,
            side=BetSide.under,
            line=Decimal("20.5"),
            price_american=-110,
            player_id=p1.id,
            captured_at=CLOSING_AT,
            book_last_update=CLOSING_AT,
        ),
        ModelPrediction(
            model_version_id=shadow.id,
            game_id=g.id,
            market=MarketType.player_points,
            player_id=p1.id,
            side=BetSide.over,
            line=Decimal("20.5"),
            model_prob=Decimal("0.60000"),
        ),
        ModelPrediction(
            model_version_id=shadow.id,
            game_id=g.id,
            market=MarketType.player_points,
            player_id=p1.id,
            side=BetSide.under,
            line=Decimal("20.5"),
            model_prob=Decimal("0.40000"),
        ),
    ])

    # 2. Player 2: reb line 7.5 (+100/-120)
    world.add_all([
        OddsHistory(
            game_id=g.id,
            sportsbook_id=book.id,
            market=MarketType.player_rebounds,
            side=BetSide.over,
            line=Decimal("7.5"),
            price_american=100,
            player_id=p2.id,
            captured_at=CLOSING_AT,
            book_last_update=CLOSING_AT,
        ),
        OddsHistory(
            game_id=g.id,
            sportsbook_id=book.id,
            market=MarketType.player_rebounds,
            side=BetSide.under,
            line=Decimal("7.5"),
            price_american=-120,
            player_id=p2.id,
            captured_at=CLOSING_AT,
            book_last_update=CLOSING_AT,
        ),
        ModelPrediction(
            model_version_id=shadow.id,
            game_id=g.id,
            market=MarketType.player_rebounds,
            player_id=p2.id,
            side=BetSide.over,
            line=Decimal("7.5"),
            model_prob=Decimal("0.40000"),
        ),
        ModelPrediction(
            model_version_id=shadow.id,
            game_id=g.id,
            market=MarketType.player_rebounds,
            player_id=p2.id,
            side=BetSide.under,
            line=Decimal("7.5"),
            model_prob=Decimal("0.60000"),
        ),
    ])

    # 3. Player 3: ast line 5.0 (push)
    world.add_all([
        OddsHistory(
            game_id=g.id,
            sportsbook_id=book.id,
            market=MarketType.player_assists,
            side=BetSide.over,
            line=Decimal("5.0"),
            price_american=-110,
            player_id=p3.id,
            captured_at=CLOSING_AT,
            book_last_update=CLOSING_AT,
        ),
        OddsHistory(
            game_id=g.id,
            sportsbook_id=book.id,
            market=MarketType.player_assists,
            side=BetSide.under,
            line=Decimal("5.0"),
            price_american=-110,
            player_id=p3.id,
            captured_at=CLOSING_AT,
            book_last_update=CLOSING_AT,
        ),
        ModelPrediction(
            model_version_id=shadow.id,
            game_id=g.id,
            market=MarketType.player_assists,
            player_id=p3.id,
            side=BetSide.over,
            line=Decimal("5.0"),
            model_prob=Decimal("0.55000"),
        ),
    ])

    # 4. Player 4: pra line 35.5 (no log -> VOID)
    world.add_all([
        OddsHistory(
            game_id=g.id,
            sportsbook_id=book.id,
            market=MarketType.player_pra,
            side=BetSide.over,
            line=Decimal("35.5"),
            price_american=-110,
            player_id=p4.id,
            captured_at=CLOSING_AT,
            book_last_update=CLOSING_AT,
        ),
        OddsHistory(
            game_id=g.id,
            sportsbook_id=book.id,
            market=MarketType.player_pra,
            side=BetSide.under,
            line=Decimal("35.5"),
            price_american=-110,
            player_id=p4.id,
            captured_at=CLOSING_AT,
            book_last_update=CLOSING_AT,
        ),
        ModelPrediction(
            model_version_id=shadow.id,
            game_id=g.id,
            market=MarketType.player_pra,
            player_id=p4.id,
            side=BetSide.over,
            line=Decimal("35.5"),
            model_prob=Decimal("0.50000"),
        ),
    ])

    # 5. Player 5: pts line 15.5 (0 min -> VOID)
    world.add_all([
        OddsHistory(
            game_id=g.id,
            sportsbook_id=book.id,
            market=MarketType.player_points,
            side=BetSide.over,
            line=Decimal("15.5"),
            price_american=-110,
            player_id=p5.id,
            captured_at=CLOSING_AT,
            book_last_update=CLOSING_AT,
        ),
        OddsHistory(
            game_id=g.id,
            sportsbook_id=book.id,
            market=MarketType.player_points,
            side=BetSide.under,
            line=Decimal("15.5"),
            price_american=-110,
            player_id=p5.id,
            captured_at=CLOSING_AT,
            book_last_update=CLOSING_AT,
        ),
        ModelPrediction(
            model_version_id=shadow.id,
            game_id=g.id,
            market=MarketType.player_points,
            player_id=p5.id,
            side=BetSide.over,
            line=Decimal("15.5"),
            model_prob=Decimal("0.50000"),
        ),
    ])
    world.commit()

    audit = audit_props_shadow(world)
    assert audit.n == 2
    assert audit.void_count == 2
    assert audit.unmatched_name_count == 2

    # Expected hand-calculated numbers:
    # Model Briers: 0.1600, 0.1600 -> mean 0.1600
    assert audit.brier_model == pytest.approx(0.1600, abs=1e-4)

    # Book Briers: (0.50 - 1.0)^2 = 0.2500, (0.478261 - 0.0)^2 = 0.228733 -> mean 0.239367
    expected_book_brier = (0.2500 + (0.5 / (0.5 + 1.0 / 1.8333333333333333)) ** 2) / 2.0
    assert audit.brier_book == pytest.approx(expected_book_brier, abs=1e-4)
    assert audit.brier_diff == pytest.approx(0.1600 - expected_book_brier, abs=1e-4)

    # Log losses:
    import math
    expected_ll_m = (-math.log(0.60) + -math.log(0.60)) / 2.0
    p_b2 = 0.5 / (0.5 + 1.0 / 1.8333333333333333)
    expected_ll_b = (-math.log(0.50) + -math.log(1.0 - p_b2)) / 2.0
    assert audit.log_loss_model == pytest.approx(expected_ll_m, abs=1e-4)
    assert audit.log_loss_book == pytest.approx(expected_ll_b, abs=1e-4)
    assert audit.log_loss_diff == pytest.approx(expected_ll_m - expected_ll_b, abs=1e-4)

    # CIs exist
    assert audit.brier_diff_ci_low is not None
    assert audit.brier_diff_ci_high is not None
    assert audit.log_loss_diff_ci_low is not None
    assert audit.log_loss_diff_ci_high is not None

    # Check format in market_audit
    text_market = format_market_audit(run_market_audit(world))
    assert "4. Props shadow model vs book close:" in text_market
    assert "insufficient data (n = 2 < 30)" in text_market
    assert "Brier: model 0.1600" in text_market
    assert "voids = 2 | unmatched names = 2" in text_market

    # Check format in paper_report
    text_paper = format_report(build_report(world, NOW))
    assert "Props shadow model vs book close" in text_paper
    assert "insufficient data (n = 2 < 30)" in text_paper
    assert "Brier model 0.1600" in text_paper
    assert "voids = 2 | unmatched names = 2" in text_paper


def test_props_shadow_league_isolation(world):
    """
    Verifies that props_nb (role='shadow') remains completely isolated:
    - invisible to list_active
    - invisible to league_rows
    - cannot be manually promoted or retired
    - invisible to league report and /api/v1/league
    - does not count toward champion's prediction or bet totals
    """
    shadow = ensure_props_shadow_model(world)
    assert shadow.role == "shadow"
    assert shadow.name == "props_nb"

    # list_active should NOT contain shadow
    active = list_active(world)
    active_ids = [m.id for m in active]
    assert shadow.id not in active_ids

    # league_rows should NOT contain shadow
    rows = model_promotion.league_rows(world)
    row_ids = [r.model_id for r in rows]
    assert shadow.id not in row_ids

    # manual_promote / manual_retire refuse shadow model
    now = datetime(2026, 10, 28, tzinfo=timezone.utc)
    with pytest.raises(model_promotion.ManualOverrideRefused, match="is a shadow model"):
        model_promotion.manual_promote(world, shadow.id, "test promote", now)
    with pytest.raises(model_promotion.ManualOverrideRefused, match="is a shadow model"):
        model_promotion.manual_retire(world, shadow.id, "test retire", now)

    # build_league should NOT contain shadow
    league = league_report.build_league(world, now)
    assert league is not None
    challenger_ids = [c.model_id for c in league.challengers]
    assert shadow.id not in challenger_ids


def test_paper_summary_api_includes_props_shadow(world):
    """
    Verifies GET /api/v1/paper/summary contract includes props_shadow when populated.
    """
    from fastapi.testclient import TestClient
    from app.main import app
    from app.deps import get_db_session

    shadow = ensure_props_shadow_model(world)
    g = final_game(world, 105, 98, home="BOS", away="LAC", start=TIPOFF)
    g.nba_game_id = "0022600002"
    world.add(g)

    p = Player(full_name="Jaylen Brown")
    world.add(p)
    world.commit()

    world.add(
        PlayerGameLog(
            player_id=p.id,
            team_id=world.teams["BOS"].id,
            season_id=world.season.id,
            game_id=g.nba_game_id,
            min=35,
            pts=28,
            reb=6,
            ast=4,
        )
    )
    book = world.books["pinnacle"]
    world.add_all([
        OddsHistory(
            game_id=g.id,
            sportsbook_id=book.id,
            market=MarketType.player_points,
            side=BetSide.over,
            line=Decimal("22.5"),
            price_american=-110,
            player_id=p.id,
            captured_at=CLOSING_AT,
            book_last_update=CLOSING_AT,
        ),
        OddsHistory(
            game_id=g.id,
            sportsbook_id=book.id,
            market=MarketType.player_points,
            side=BetSide.under,
            line=Decimal("22.5"),
            price_american=-110,
            player_id=p.id,
            captured_at=CLOSING_AT,
            book_last_update=CLOSING_AT,
        ),
        ModelPrediction(
            model_version_id=shadow.id,
            game_id=g.id,
            market=MarketType.player_points,
            player_id=p.id,
            side=BetSide.over,
            line=Decimal("22.5"),
            model_prob=Decimal("0.65000"),
        ),
    ])
    world.commit()

    def get_test_db():
        yield world

    old_override = app.dependency_overrides.get(get_db_session)
    app.dependency_overrides[get_db_session] = get_test_db
    try:
        client = TestClient(app)
        res = client.get("/api/v1/paper/summary")
        assert res.status_code == 200
        data = res.json()
        assert "props_shadow" in data
        assert data["props_shadow"] is not None
        assert data["props_shadow"]["n"] == 1
        assert data["props_shadow"]["brier_model"] is not None
        assert data["props_shadow"]["brier_book"] is not None
    finally:
        if old_override is not None:
            app.dependency_overrides[get_db_session] = old_override
        else:
            app.dependency_overrides.pop(get_db_session, None)
