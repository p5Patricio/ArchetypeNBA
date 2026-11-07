"""
Unit and integration tests for the OddsPapi client, parser, mapper, storage, planner and tick step (D-70).
"""
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional
import unittest.mock

import httpx
import pytest
from sqlmodel import Session, func, select

from app.config import settings
from app.models import (
    CAPTURE_CLOSING,
    CAPTURE_CLOSING_ODDSPAPI,
    BetSide,
    Game,
    MarketType,
    OddsHistory,
    OddsPapiFixture,
    OddsPapiQuote,
    OddsPapiRequest,
    OddsSnapshotCapture,
    Player,
    PlayerGameLog,
    Season,
    Sportsbook,
    Team,
)
from app.services import clv_report, market_close
from app.services.oddspapi import (
    FixtureMapper,
    MarketSpec,
    _aware,
    close_cutoff,
    decimal_to_american,
    main_line_path,
    open_close,
    parse_fixtures,
    plan_paths,
    plan_run,
    recover_missed_closes,
    run_oddspapi,
    store_path,
    upsert_fixtures,
)
from app.services.oddspapi_client import (
    BudgetExceeded,
    DbRequestLedger,
    MemoryLedger,
    OddsPapiClient,
    OddsPapiError,
    QuotaExhausted,
    mask_secret,
)
from app.services.tick import TickContext, default_steps, oddspapi_step
import scripts.oddspapi_backfill

NOW = datetime(2026, 11, 7, 18, 0, tzinfo=timezone.utc)
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "oddspapi"


def make_world(session: Session) -> Dict[str, object]:
    """Helper factory setting up a season, core teams and default games."""
    season = Season(season_label="2026-27", is_active=False)
    session.add(season)
    session.flush()

    teams = {
        "DET": Team(abbreviation="DET", full_name="Detroit Pistons", city="Detroit", conference="East", division="Central"),
        "BOS": Team(abbreviation="BOS", full_name="Boston Celtics", city="Boston", conference="East", division="Atlantic"),
        "NYK": Team(abbreviation="NYK", full_name="New York Knicks", city="New York", conference="East", division="Atlantic"),
        "PHI": Team(abbreviation="PHI", full_name="Philadelphia 76ers", city="Philadelphia", conference="East", division="Atlantic"),
    }
    for t in teams.values():
        session.add(t)
    session.flush()

    games = {
        "DET_BOS": Game(season_id=season.id, home_team_id=teams["DET"].id, away_team_id=teams["BOS"].id,
                        commence_time=datetime(2026, 10, 20, 19, 10, tzinfo=timezone.utc), status="final"),
        "PHI_NYK": Game(season_id=season.id, home_team_id=teams["PHI"].id, away_team_id=teams["NYK"].id,
                        commence_time=datetime(2026, 10, 20, 23, 10, tzinfo=timezone.utc), status="final"),
    }
    for g in games.values():
        session.add(g)
    session.commit()
    return {"season": season, "teams": teams, "games": games}


# ==============================================================================
# CLIENT TESTS (1 - 7)
# ==============================================================================

def test_mask_secret_removes_key():
    url = "https://x/v4/a?apiKey=SECRET-KEY-123&b=1"
    masked = mask_secret(url, "SECRET-KEY-123")
    assert "SECRET-KEY-123" not in masked
    assert "apiKey=***" in masked


def test_client_secret_leak_prevention(caplog):
    caplog.set_level(logging.DEBUG)
    key = "SECRET-KEY-123"
    ledger = MemoryLedger()

    c1 = OddsPapiClient(ledger, api_key=key, transport=httpx.MockTransport(lambda r: httpx.Response(500, text=f"error apiKey={key}")),
                        sleep=lambda s: None, clock=lambda: 0.0, now=lambda: NOW)
    with pytest.raises(OddsPapiError) as exc1:
        c1.account()
    assert key not in str(exc1.value)

    def err_handler(r):
        raise httpx.ConnectError(f"boom apiKey={key}")

    c2 = OddsPapiClient(ledger, api_key=key, transport=httpx.MockTransport(err_handler),
                        sleep=lambda s: None, clock=lambda: 0.0, now=lambda: NOW)
    with pytest.raises(OddsPapiError) as exc2:
        c2.account()
    assert key not in str(exc2.value)

    assert key not in caplog.text
    for row in ledger.rows:
        for col in ("endpoint", "fixture_id", "label", "source"):
            val = getattr(row, col)
            if isinstance(val, str):
                assert key not in val


def test_client_cooldowns_per_endpoint():
    slept: List[float] = []
    fake_time = [1000.0]

    def handler(req: httpx.Request):
        if req.url.path == "/v4/account":
            return httpx.Response(200, json={"subscriptions": []})
        if req.url.path == "/v4/fixtures":
            return httpx.Response(200, json=[])
        return httpx.Response(200, json={"fixtureId": "fix1"})

    client = OddsPapiClient(MemoryLedger(), api_key="KEY", transport=httpx.MockTransport(handler),
                            sleep=slept.append, clock=lambda: fake_time[0], now=lambda: NOW)

    client.historical_odds("fix1", ["pinnacle"])
    assert len(slept) == 0
    client.historical_odds("fix1", ["pinnacle"])
    assert len(slept) == 1 and pytest.approx(5.5, abs=0.1) == slept[0]

    slept.clear()
    client.list_fixtures(132, NOW, NOW + timedelta(days=1))
    assert len(slept) == 0
    client.list_fixtures(132, NOW, NOW + timedelta(days=1))
    assert len(slept) == 1 and pytest.approx(2.5, abs=0.1) == slept[0]

    slept.clear()
    fake_time[0] = 2000.0
    client.historical_odds("fix1", ["pinnacle"])
    client.account()
    assert len(slept) == 0


def test_client_monthly_budget_enforced(db_session):
    prev_month = NOW.replace(day=1) - timedelta(days=1)
    db_session.add(OddsPapiRequest(requested_at=prev_month, endpoint="/v4/fixtures", billable=True, status_code=200))
    db_session.commit()

    call_count = [0]
    def handler(req: httpx.Request):
        call_count[0] += 1
        return httpx.Response(200, json=[])

    ledger = DbRequestLedger(db_session)
    c1 = OddsPapiClient(ledger, api_key="KEY", transport=httpx.MockTransport(handler),
                        sleep=lambda s: None, clock=lambda: 0.0, now=lambda: NOW, monthly_budget=3)

    for _ in range(3):
        c1.list_fixtures(132, NOW, NOW + timedelta(days=1))
    assert call_count[0] == 3

    for _ in range(2):
        with pytest.raises(BudgetExceeded):
            c1.list_fixtures(132, NOW, NOW + timedelta(days=1))
    assert call_count[0] == 3

    c2 = OddsPapiClient(ledger, api_key="KEY", transport=httpx.MockTransport(handler),
                        sleep=lambda s: None, clock=lambda: 0.0, now=lambda: NOW, monthly_budget=3)
    with pytest.raises(BudgetExceeded):
        c2.list_fixtures(132, NOW, NOW + timedelta(days=1))
    assert call_count[0] == 3


def test_client_budget_zero_and_historical_billable(db_session):
    reached: List[str] = []
    def handler(req: httpx.Request):
        reached.append(req.url.path)
        if req.url.path == "/v4/account":
            return httpx.Response(200, json={"subscriptions": []})
        return httpx.Response(200, json={"fixtureId": "f1"})

    ledger = DbRequestLedger(db_session)
    c1 = OddsPapiClient(ledger, api_key="KEY", transport=httpx.MockTransport(handler),
                        sleep=lambda s: None, clock=lambda: 0.0, now=lambda: NOW, monthly_budget=0, historical_billable=False)
    c1.historical_odds("f1", ["pinnacle"])
    c1.account()

    rows = db_session.execute(select(OddsPapiRequest)).scalars().all()
    assert len(rows) == 2 and all(r.billable is False for r in rows)

    with pytest.raises(BudgetExceeded):
        c1.list_fixtures(132, NOW, NOW + timedelta(days=1))
    assert "/v4/fixtures" not in reached

    c2 = OddsPapiClient(ledger, api_key="KEY", transport=httpx.MockTransport(handler),
                        sleep=lambda s: None, clock=lambda: 0.0, now=lambda: NOW, monthly_budget=1, historical_billable=True)
    c2.historical_odds("f1", ["pinnacle"])
    with pytest.raises(BudgetExceeded):
        c2.historical_odds("f1", ["pinnacle"])


def test_client_status_handling():
    not_found_text = (FIXTURES_DIR / "historical_not_found.json").read_text(encoding="utf-8")
    def handler(req: httpx.Request):
        fid = req.url.params.get("fixtureId", "")
        if "rate-limit" in fid:
            return httpx.Response(429, text="Rate limit exceeded")
        if "not-found" in fid:
            return httpx.Response(404, text=not_found_text)
        if req.headers.get("If-None-Match") == '"abc"':
            return httpx.Response(304, headers={"etag": '"abc"'})
        return httpx.Response(200, json={"ok": True}, headers={"etag": '"e1"'})

    c = OddsPapiClient(MemoryLedger(), api_key="KEY", transport=httpx.MockTransport(handler),
                        sleep=lambda s: None, clock=lambda: 0.0, now=lambda: NOW)

    with pytest.raises(QuotaExhausted):
        c.historical_odds("rate-limit", ["pinnacle"])

    resp_404 = c.historical_odds("not-found", ["pinnacle"])
    assert resp_404.not_found is True and resp_404.data is None

    assert c.historical_odds("fix1", ["pinnacle"], etag='"abc"').not_modified is True
    assert c.historical_odds("fix1", ["pinnacle"]).etag == '"e1"'


def test_client_limits_validation_and_account():
    acct_json = json.loads((FIXTURES_DIR / "account.json").read_text(encoding="utf-8"))
    def handler(req: httpx.Request):
        if req.url.path == "/v4/account":
            return httpx.Response(200, json=acct_json)
        return httpx.Response(200, json=[])

    ledger = MemoryLedger()
    c = OddsPapiClient(ledger, api_key="KEY", transport=httpx.MockTransport(handler),
                       sleep=lambda s: None, clock=lambda: 0.0, now=lambda: NOW, max_requests=2)
    c.account()
    c.list_fixtures(132, NOW, NOW + timedelta(days=1), label="season")
    with pytest.raises(BudgetExceeded):
        c.account()

    with pytest.raises(ValueError, match="1..3 bookmakers"):
        c.historical_odds("f1", ["b1", "b2", "b3", "b4"])

    fix_row = next(r for r in ledger.rows if r.endpoint == "/v4/fixtures")
    assert fix_row.billable is True and fix_row.status_code == 200 and fix_row.label == "season"

    c_acct = OddsPapiClient(MemoryLedger(), api_key="KEY", transport=httpx.MockTransport(handler),
                            sleep=lambda s: None, clock=lambda: 0.0, now=lambda: NOW)
    assert c_acct.account() == {"request_limit": 250, "request_count": 4}


# ==============================================================================
# PARSING TESTS (8 - 11)
# ==============================================================================

def test_main_line_path_det_bos():
    payload = json.loads((FIXTURES_DIR / "historical_det_bos_pinnacle.json").read_text(encoding="utf-8"))
    cutoff = datetime(2026, 10, 20, 19, 0, 54, tzinfo=timezone.utc)
    quotes, stats = main_line_path(payload, cutoff)

    assert stats.post_cutoff_entries == 28 and stats.prematch_entries == 98 and len(quotes) == 26
    assert all(q.created_at <= cutoff and q.bookmaker == "pinnacle" for q in quotes)

    h2h = [q for q in quotes if q.market == MarketType.h2h]
    assert h2h[0].side == BetSide.home and h2h[0].price_decimal == 1.793
    assert h2h[1].side == BetSide.away and h2h[1].price_decimal == 2.12
    assert h2h[0].created_at == datetime(2026, 9, 28, 1, 44, 36, 46000, tzinfo=timezone.utc)
    assert h2h[-2].side == BetSide.home and h2h[-2].price_decimal == 2.1
    assert h2h[-1].side == BetSide.away and h2h[-1].price_decimal == 1.84

    spreads = [q for q in quotes if q.market == MarketType.spreads]
    assert spreads[-2].line == 1.5 and spreads[-2].price_decimal == 1.99
    assert spreads[-1].line == -1.5 and spreads[-1].price_decimal == 1.934

    totals = [q for q in quotes if q.market == MarketType.totals]
    assert totals[-2].line == 220.5 and totals[-2].side == BetSide.over and totals[-2].price_decimal == 1.925
    assert totals[-1].line == 220.5 and totals[-1].side == BetSide.under and totals[-1].price_decimal == 1.961
    assert totals[-1].created_at == datetime(2026, 10, 20, 18, 57, 15, 967000, tzinfo=timezone.utc)


def test_main_line_path_live_only():
    payload = json.loads((FIXTURES_DIR / "historical_live_only_pinnacle.json").read_text(encoding="utf-8"))
    quotes, stats = main_line_path(payload, datetime(2026, 1, 25, 0, 8, 50, tzinfo=timezone.utc))
    assert len(quotes) == 0 and stats.prematch_entries == 0 and stats.post_cutoff_entries == 4


def test_main_line_path_synthetic_catalog_and_selection():
    catalog = {
        "m1": MarketSpec("spreads", -2.5, {"o1": "1", "o2": "2"}),
        "m2": MarketSpec("spreads", -3.5, {"o3": "1", "o4": "2"}),
    }
    t0, t1, t2 = "2026-10-20T10:00:00.000Z", "2026-10-20T11:00:00.000Z", "2026-10-20T12:00:00.000Z"
    payload = {
        "bookmakers": {"pinnacle": {"markets": {
            "m1": {"outcomes": {
                "o1": {"players": {"0": [{"createdAt": t0, "price": 1.95, "active": True}, {"createdAt": t1, "price": 1.95, "active": False}],
                                   "ign": [{"createdAt": t0, "price": 1.5, "active": True}]}},
                "o2": {"players": {"0": [{"createdAt": t0, "price": 1.95, "active": True}]}},
            }},
            "m2": {"outcomes": {
                "o3": {"players": {"0": [{"createdAt": t0, "price": 2.20, "active": True}, {"createdAt": t2, "price": 2.20, "active": True}]}},
                "o4": {"players": {"0": [{"createdAt": t0, "price": 1.70, "active": True}, {"createdAt": t2, "price": 1.70, "active": True}]}},
            }},
            "m_unk": {"outcomes": {"ox": {"players": {"0": [{"createdAt": t0, "price": 1.9, "active": True}]}}}},
        }}}
    }
    quotes, stats = main_line_path(payload, datetime(2026, 10, 20, 13, 0, tzinfo=timezone.utc), catalog=catalog)
    assert len(quotes) == 4
    assert quotes[0].line == -2.5 and quotes[0].price_decimal == 1.95 and quotes[1].line == 2.5
    assert quotes[2].line == -3.5 and quotes[2].price_decimal == 2.20 and quotes[3].line == 3.5
    assert stats.unknown_markets >= 1


def test_close_cutoff_decimal_to_american_open_close():
    start = datetime(2026, 10, 20, 19, 0, 0, tzinfo=timezone.utc)
    commence = datetime(2026, 10, 20, 19, 10, 0, tzinfo=timezone.utc)

    assert close_cutoff(start, start + timedelta(seconds=54), commence) == start + timedelta(seconds=54)
    assert close_cutoff(start, start + timedelta(hours=5), commence) == min(start, commence)
    assert close_cutoff(start, None, commence) == min(start, commence)

    assert decimal_to_american(2.1) == 110 and decimal_to_american(1.84) == -119
    assert decimal_to_american(2.0) == 100 and decimal_to_american(1.909) == -110
    assert decimal_to_american(1.01) == -10000
    with pytest.raises(ValueError):
        decimal_to_american(1.0)

    rows = [("h2h", "home", None, 1.80, start), ("h2h", "away", None, 2.10, start),
            ("h2h", "home", None, 1.90, start + timedelta(hours=1)), ("h2h", "away", None, 1.95, start + timedelta(hours=1))]
    oc = open_close(rows)
    assert oc["h2h"].open_prices == (1.80, 2.10) and oc["h2h"].close_prices == (1.90, 1.95)


# ==============================================================================
# MAPPING TESTS (12 - 13)
# ==============================================================================

def test_upsert_fixtures_mapping_and_idempotence(db_session):
    world = make_world(db_session)
    game_det_bos = world["games"]["DET_BOS"]

    payload = json.loads((FIXTURES_DIR / "fixtures_nba_sample.json").read_text(encoding="utf-8"))
    fixtures, _ = parse_fixtures(payload)

    stats1 = upsert_fixtures(db_session, fixtures, NOW)
    assert stats1.seen == 5 and stats1.mapped_game == 1 and stats1.unmatched == 4

    rows = {r.fixture_id: r for r in db_session.execute(select(OddsPapiFixture)).scalars().all()}
    assert rows["id1100013273682354"].game_id == game_det_bos.id
    assert rows["id1100013273682356"].unmatched_reason == "home_away_mismatch" and rows["id1100013273682356"].game_id is None
    assert rows["id1100013273682414"].unmatched_reason == "team_unresolved"
    assert rows["id1100013273719332"].unmatched_reason == "team_unresolved"

    ind_den = rows["id1100013273722402"]
    assert ind_den.status_id == 0 and ind_den.unmatched_reason == "team_unresolved" and ind_den.nba_game_id is None

    upsert_fixtures(db_session, fixtures, NOW)
    assert db_session.execute(select(func.count(OddsPapiFixture.id))).scalar_one() == 5


def test_fixture_mapper_nba_game_for(db_session):
    world = make_world(db_session)
    season = world["season"]
    mia = Team(abbreviation="MIA", full_name="Miami Heat", city="Miami", conference="East", division="Southeast")
    orl = Team(abbreviation="ORL", full_name="Orlando Magic", city="Orlando", conference="East", division="Southeast")
    p1, p2 = Player(full_name="Player One"), Player(full_name="Player Two")
    db_session.add_all([mia, orl, p1, p2])
    db_session.flush()

    log_mia = PlayerGameLog(player_id=p1.id, team_id=mia.id, season_id=season.id, game_id="0022500700",
                            game_date=date(2026, 3, 14), matchup="MIA vs. ORL")
    log_orl = PlayerGameLog(player_id=p2.id, team_id=orl.id, season_id=season.id, game_id="0022500700",
                            game_date=date(2026, 3, 14), matchup="ORL @ MIA")
    db_session.add_all([log_mia, log_orl])
    db_session.commit()

    start = datetime(2026, 3, 15, 0, 11, tzinfo=timezone.utc)
    mapper = FixtureMapper(db_session)
    gid, reason = mapper.nba_game_for(mia.id, orl.id, start)
    assert gid == "0022500700" and reason is None

    log_mia.matchup = "MIA @ ORL"
    db_session.add(log_mia)
    db_session.commit()

    gid2, reason2 = mapper.nba_game_for(mia.id, orl.id, start)
    assert gid2 is None and reason2 == "home_away_mismatch"


# ==============================================================================
# STORAGE AND RECOVERY TESTS (14 - 16)
# ==============================================================================

def test_store_path_odds_history_for_game(db_session):
    world = make_world(db_session)
    game = world["games"]["DET_BOS"]

    fixture = OddsPapiFixture(
        fixture_id="id1100013273682354", tournament_id=132, status_id=2,
        start_time=datetime(2026, 10, 20, 19, 0, tzinfo=timezone.utc),
        true_start_time=datetime(2026, 10, 20, 19, 0, 54, tzinfo=timezone.utc),
        home_name="Detroit Pistons", away_name="Boston Celtics", listed_at=NOW, game_id=game.id,
    )
    db_session.add(fixture)
    db_session.commit()

    payload = json.loads((FIXTURES_DIR / "historical_det_bos_pinnacle.json").read_text(encoding="utf-8"))
    res1 = store_path(db_session, fixture, payload, NOW)
    assert res1.status == "stored" and res1.inserted == 26
    assert fixture.path_status == "stored" and fixture.quotes_stored == 26

    sb = db_session.execute(select(Sportsbook).where(Sportsbook.key == "op_pinnacle")).scalar_one()
    assert sb.is_sharp is False and sb.region == "eu"

    quotes = db_session.execute(select(OddsHistory)).scalars().all()
    assert len(quotes) == 26 and all(q.captured_at == q.book_last_update and q.sportsbook_id == sb.id for q in quotes)
    assert db_session.execute(select(Sportsbook).where(Sportsbook.key == "pinnacle")).scalar() is None

    res2 = store_path(db_session, fixture, payload, NOW)
    assert res2.inserted == 0 and res2.duplicate == 26


def test_store_path_quotes_for_nba_game(db_session):
    fixture = OddsPapiFixture(
        fixture_id="f_nba", tournament_id=132, status_id=2,
        start_time=datetime(2026, 10, 20, 19, 0, tzinfo=timezone.utc),
        true_start_time=datetime(2026, 10, 20, 19, 0, 54, tzinfo=timezone.utc),
        home_name="DET", away_name="BOS", listed_at=NOW, nba_game_id="0022500700", game_id=None,
    )
    db_session.add(fixture)
    db_session.commit()

    payload = json.loads((FIXTURES_DIR / "historical_det_bos_pinnacle.json").read_text(encoding="utf-8"))
    res1 = store_path(db_session, fixture, payload, NOW)
    assert res1.status == "stored" and res1.target == "oddspapi_quote" and res1.inserted == 26

    quotes = db_session.execute(select(OddsPapiQuote)).scalars().all()
    assert len(quotes) == 26 and any(q.price_decimal == Decimal("1.9900") for q in quotes)
    assert db_session.execute(select(func.count(OddsHistory.id))).scalar_one() == 0

    res2 = store_path(db_session, fixture, payload, NOW)
    assert res2.inserted == 0 and res2.duplicate == 26


def test_recover_missed_closes_and_market_close(db_session):
    world = make_world(db_session)
    season, t1, t2 = world["season"], world["teams"]["DET"], world["teams"]["BOS"]

    g1 = Game(season_id=season.id, home_team_id=t1.id, away_team_id=t2.id, commence_time=datetime(2026, 10, 20, 19, 10, tzinfo=timezone.utc), status="final")
    g2 = Game(season_id=season.id, home_team_id=t1.id, away_team_id=t2.id, commence_time=datetime(2026, 10, 21, 19, 10, tzinfo=timezone.utc), status="final")
    db_session.add_all([g1, g2])
    db_session.flush()

    db_session.add(OddsSnapshotCapture(game_id=g2.id, kind=CAPTURE_CLOSING, captured_at=g2.commence_time))
    db_session.commit()

    payload = json.loads((FIXTURES_DIR / "historical_det_bos_pinnacle.json").read_text(encoding="utf-8"))
    f1 = OddsPapiFixture(fixture_id="f1", tournament_id=132, status_id=2, start_time=g1.commence_time,
                         true_start_time=datetime(2026, 10, 20, 19, 0, 54, tzinfo=timezone.utc),
                         home_name="DET", away_name="BOS", listed_at=NOW, game_id=g1.id)
    f2 = OddsPapiFixture(fixture_id="f2", tournament_id=132, status_id=2, start_time=g2.commence_time,
                         true_start_time=datetime(2026, 10, 21, 19, 0, 54, tzinfo=timezone.utc),
                         home_name="DET", away_name="BOS", listed_at=NOW, game_id=g2.id)
    db_session.add_all([f1, f2])
    db_session.commit()

    store_path(db_session, f1, payload, NOW)
    store_path(db_session, f2, payload, NOW)

    assert recover_missed_closes(db_session, NOW) == [g1.id]
    assert recover_missed_closes(db_session, NOW) == []

    probs, rec_ids = market_close.closing_home_probs_with_recovery(db_session, {g1.id: g1.commence_time}, [g1.id])
    assert rec_ids == {g1.id} and pytest.approx(0.4670, abs=1e-3) == probs[g1.id]

    db_session.add(Sportsbook(key="pinnacle", name="Pinnacle", region="eu", is_sharp=True))
    db_session.commit()
    assert market_close.sharp_closing_home_probs(db_session, {g1.id: g1.commence_time}, [g1.id]) == {}

    assert clv_report.build_pinnacle_clv_report(db_session, include_recovered=False).total_bets == 0


# ==============================================================================
# PLANNER TESTS (17 - 18)
# ==============================================================================

def test_plan_paths_priorities_filtering_and_sorting(db_session):
    world = make_world(db_session)
    season, t1, t2 = world["season"], world["teams"]["DET"], world["teams"]["BOS"]

    g_a = Game(season_id=season.id, home_team_id=t1.id, away_team_id=t2.id, commence_time=datetime(2026, 10, 20, 19, 0, tzinfo=timezone.utc), status="final")
    g_b = Game(season_id=season.id, home_team_id=t1.id, away_team_id=t2.id, commence_time=datetime(2026, 10, 25, 19, 0, tzinfo=timezone.utc), status="final")
    g_c1 = Game(season_id=season.id, home_team_id=t1.id, away_team_id=t2.id, commence_time=datetime(2026, 10, 22, 19, 0, tzinfo=timezone.utc), status="final")
    g_c2 = Game(season_id=season.id, home_team_id=t1.id, away_team_id=t2.id, commence_time=datetime(2026, 10, 28, 19, 0, tzinfo=timezone.utc), status="final")
    g_e = Game(season_id=season.id, home_team_id=t1.id, away_team_id=t2.id, commence_time=datetime(2026, 10, 20, 19, 0, tzinfo=timezone.utc), status="final")
    g_f = Game(season_id=season.id, home_team_id=t1.id, away_team_id=t2.id, commence_time=datetime(2026, 10, 20, 19, 0, tzinfo=timezone.utc), status="final")
    g_g = Game(season_id=season.id, home_team_id=t1.id, away_team_id=t2.id, commence_time=datetime(2026, 10, 21, 19, 0, tzinfo=timezone.utc), status="final")
    g_h = Game(season_id=season.id, home_team_id=t1.id, away_team_id=t2.id, commence_time=NOW - timedelta(hours=1), status="final")
    g_i = Game(season_id=season.id, home_team_id=t1.id, away_team_id=t2.id, commence_time=datetime(2026, 10, 20, 19, 0, tzinfo=timezone.utc), status="scheduled")

    db_session.add_all([g_a, g_b, g_c1, g_c2, g_e, g_f, g_g, g_h, g_i])
    db_session.flush()

    for g in (g_b, g_c1, g_c2):
        db_session.add(OddsSnapshotCapture(game_id=g.id, kind=CAPTURE_CLOSING, captured_at=g.commence_time))
    db_session.flush()

    fixtures = [
        OddsPapiFixture(fixture_id="f_a", tournament_id=132, status_id=2, start_time=g_a.commence_time, home_name="DET", away_name="BOS", listed_at=NOW, game_id=g_a.id),
        OddsPapiFixture(fixture_id="f_b", tournament_id=132, status_id=2, start_time=g_b.commence_time, home_name="DET", away_name="BOS", listed_at=NOW, game_id=g_b.id),
        OddsPapiFixture(fixture_id="f_c1", tournament_id=132, status_id=2, start_time=g_c1.commence_time, home_name="DET", away_name="BOS", listed_at=NOW, game_id=g_c1.id),
        OddsPapiFixture(fixture_id="f_c2", tournament_id=132, status_id=2, start_time=g_c2.commence_time, home_name="DET", away_name="BOS", listed_at=NOW, game_id=g_c2.id),
        OddsPapiFixture(fixture_id="f_d", tournament_id=132, status_id=2, start_time=datetime(2026, 3, 15, 0, 0, tzinfo=timezone.utc), home_name="DET", away_name="BOS", listed_at=NOW, nba_game_id="0022500001"),
        OddsPapiFixture(fixture_id="f_e", tournament_id=132, status_id=2, start_time=g_e.commence_time, home_name="DET", away_name="BOS", listed_at=NOW, game_id=g_e.id, path_status="stored"),
        OddsPapiFixture(fixture_id="f_f", tournament_id=132, status_id=2, start_time=g_f.commence_time, home_name="DET", away_name="BOS", listed_at=NOW, game_id=g_f.id, path_status="not_found"),
        OddsPapiFixture(fixture_id="f_g", tournament_id=132, status_id=2, start_time=g_g.commence_time, home_name="DET", away_name="BOS", listed_at=NOW, game_id=g_g.id, path_status="error"),
        OddsPapiFixture(fixture_id="f_h", tournament_id=132, status_id=2, start_time=g_h.commence_time, home_name="DET", away_name="BOS", listed_at=NOW, game_id=g_h.id),
        OddsPapiFixture(fixture_id="f_i", tournament_id=132, status_id=2, start_time=g_i.commence_time, home_name="DET", away_name="BOS", listed_at=NOW, game_id=g_i.id),
    ]
    db_session.add_all(fixtures)
    db_session.commit()

    plans, due = plan_paths(db_session, NOW, max_paths=100, include_backfill=True)
    assert [p.fixture_id for p in plans] == ["f_g", "f_a", "f_c2", "f_b", "f_c1", "f_d"]
    assert due == {1: 2, 2: 3, 3: 1}

    plans_no_bf, due_no_bf = plan_paths(db_session, NOW, max_paths=100, include_backfill=False)
    assert "f_d" not in [p.fixture_id for p in plans_no_bf]
    assert due_no_bf.get(3, 0) == 0

    plans_cap, due_cap = plan_paths(db_session, NOW, max_paths=2, include_backfill=True)
    assert len(plans_cap) == 2 and due_cap == {1: 2, 2: 3, 3: 1}


def test_plan_run_listings_season_and_backfill(db_session):
    world = make_world(db_session)
    season, t1, t2 = world["season"], world["teams"]["DET"], world["teams"]["BOS"]

    commence = datetime(2026, 10, 20, 19, 0, tzinfo=timezone.utc)
    db_session.add(Game(season_id=season.id, home_team_id=t1.id, away_team_id=t2.id, commence_time=commence, status="final"))
    db_session.commit()

    p1 = plan_run(db_session, NOW, max_paths=10, monthly_budget=50, include_backfill=False)
    assert len(p1.listings) == 1 and p1.listings[0].label == "season"
    assert p1.listings[0].start == _aware(commence) - timedelta(days=1)

    r1 = OddsPapiRequest(requested_at=NOW - timedelta(hours=2), endpoint="/v4/fixtures", billable=True, status_code=200)
    db_session.add(r1)
    db_session.commit()
    p2 = plan_run(db_session, NOW, max_paths=10, monthly_budget=50, include_backfill=False)
    assert len(p2.listings) == 0 and any("20 h" in n for n in p2.notes)

    r1.requested_at = NOW - timedelta(hours=22)
    db_session.add(r1)
    db_session.commit()
    p3 = plan_run(db_session, NOW, max_paths=10, monthly_budget=1, include_backfill=False)
    assert len(p3.listings) == 0 and any("budget is used up" in n for n in p3.notes)

    db_session.delete(r1)
    db_session.commit()
    p4 = plan_run(db_session, NOW, max_paths=10, monthly_budget=50, include_backfill=True)
    assert any(l.label == "backfill-2026" for l in p4.listings)

    r_bf = OddsPapiRequest(requested_at=NOW - timedelta(days=2), endpoint="/v4/fixtures", label="backfill-2026", billable=True, status_code=200)
    db_session.add(r_bf)
    db_session.commit()
    p5 = plan_run(db_session, NOW, max_paths=10, monthly_budget=50, include_backfill=True)
    assert not any(l.label == "backfill-2026" for l in p5.listings)


# ==============================================================================
# END TO END TESTS (19 - 20)
# ==============================================================================

def test_run_oddspapi_e2e_success(db_session):
    world = make_world(db_session)
    game = world["games"]["DET_BOS"]

    acct_json = json.loads((FIXTURES_DIR / "account.json").read_text(encoding="utf-8"))
    fixtures_json = json.loads((FIXTURES_DIR / "fixtures_nba_sample.json").read_text(encoding="utf-8"))
    hist_json = json.loads((FIXTURES_DIR / "historical_det_bos_pinnacle.json").read_text(encoding="utf-8"))
    hist_404 = json.loads((FIXTURES_DIR / "historical_not_found.json").read_text(encoding="utf-8"))

    def handler(req: httpx.Request):
        if req.url.path == "/v4/account":
            return httpx.Response(200, json=acct_json)
        if req.url.path == "/v4/fixtures":
            return httpx.Response(200, json=fixtures_json)
        if req.url.path == "/v4/historical-odds":
            if req.url.params.get("fixtureId") == "id1100013273682354":
                return httpx.Response(200, json=hist_json, headers={"etag": '"x"'})
            return httpx.Response(404, json=hist_404)
        return httpx.Response(404)

    client = OddsPapiClient(DbRequestLedger(db_session), api_key="KEY", transport=httpx.MockTransport(handler),
                            sleep=lambda s: None, clock=lambda: 0.0, now=lambda: NOW)

    summary1 = run_oddspapi(db_session, client, NOW, max_paths=5, bookmakers=["pinnacle"])
    assert summary1.status == "ok" and summary1.paths_stored == 1
    assert summary1.closes_recovered == [game.id] and summary1.quotes_inserted == 26

    summary2 = run_oddspapi(db_session, client, NOW, max_paths=5, bookmakers=["pinnacle"])
    assert summary2.paths_stored == 0


def test_run_oddspapi_quota_exhausted_and_budget_zero(db_session):
    world = make_world(db_session)
    game = world["games"]["DET_BOS"]

    fixture = OddsPapiFixture(
        fixture_id="id1100013273682354", tournament_id=132, status_id=2, start_time=game.commence_time,
        true_start_time=datetime(2026, 10, 20, 19, 0, 54, tzinfo=timezone.utc),
        home_name="Detroit Pistons", away_name="Boston Celtics", listed_at=NOW, game_id=game.id,
    )
    db_session.add(fixture)
    db_session.commit()

    def handler_429(req: httpx.Request):
        if req.url.path == "/v4/account":
            return httpx.Response(200, json={"subscriptions": [{"is_active": True, "request_limit": 250, "request_count": 0}]})
        if req.url.path == "/v4/historical-odds":
            return httpx.Response(429, text="Rate limit exceeded")
        return httpx.Response(200, json=[])

    client = OddsPapiClient(DbRequestLedger(db_session), api_key="KEY", transport=httpx.MockTransport(handler_429),
                            sleep=lambda s: None, clock=lambda: 0.0, now=lambda: NOW)
    summary_429 = run_oddspapi(db_session, client, NOW, max_paths=5, bookmakers=["pinnacle"])
    assert summary_429.status == "quota"
    assert isinstance(summary_429.closes_recovered, list)

    db_session.delete(fixture)
    for row in db_session.execute(select(OddsPapiRequest)).scalars().all():
        db_session.delete(row)  # a listing within the last 20 h would hold the season listing back for another reason
    db_session.commit()

    transport_requests: List[str] = []
    def handler_record(req: httpx.Request):
        transport_requests.append(req.url.path)
        if req.url.path == "/v4/account":
            return httpx.Response(200, json={"subscriptions": [{"is_active": True, "request_limit": 250, "request_count": 0}]})
        return httpx.Response(200, json=[])

    client_budget0 = OddsPapiClient(DbRequestLedger(db_session), api_key="KEY", transport=httpx.MockTransport(handler_record),
                                    sleep=lambda s: None, clock=lambda: 0.0, now=lambda: NOW, monthly_budget=0)
    summary_budget0 = run_oddspapi(db_session, client_budget0, NOW, max_paths=5, bookmakers=["pinnacle"])
    assert not any("/v4/fixtures" in req for req in transport_requests)
    assert summary_budget0.status == "budget"
    assert any("budget" in note for note in summary_budget0.notes)


# ==============================================================================
# DRY RUN AND TICK TESTS (21 - 22)
# ==============================================================================

def test_oddspapi_backfill_cli_dry_run_and_report(db_session, monkeypatch):
    @contextmanager
    def session_factory():
        yield db_session

    def client_factory(session):
        raise AssertionError("client_factory should not be called in dry run or report")

    monkeypatch.setattr(httpx.Client, "__init__", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("forbidden")))

    ret_dry = scripts.oddspapi_backfill.main(["--dry-run"], session_factory=session_factory, client_factory=client_factory)
    assert ret_dry == 0
    assert db_session.execute(select(func.count(OddsPapiRequest.id))).scalar_one() == 0

    ret_rep = scripts.oddspapi_backfill.main(["--report"], session_factory=session_factory, client_factory=client_factory)
    assert ret_rep == 0
    assert db_session.execute(select(func.count(OddsPapiRequest.id))).scalar_one() == 0


def test_tick_oddspapi_step_and_default_steps(db_session, monkeypatch):
    monkeypatch.setattr(settings, "ODDSPAPI_ENABLED", False)
    ctx_dis = TickContext(session=db_session, service=None, now=NOW, dry_run=False,
                          window_minutes=30, props_events=0, min_remaining=25, local_tz=timezone.utc, oddspapi_client=None)
    assert oddspapi_step(ctx_dis).status == "skipped"

    monkeypatch.setattr(settings, "ODDSPAPI_ENABLED", True)
    monkeypatch.setattr(httpx.Client, "__init__", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("forbidden in dry run")))
    ctx_dry = TickContext(session=db_session, service=None, now=NOW, dry_run=True,
                          window_minutes=30, props_events=0, min_remaining=25, local_tz=timezone.utc, oddspapi_client=None)
    res_dry = oddspapi_step(ctx_dry)
    assert res_dry.status == "ok"
    assert db_session.execute(select(func.count(OddsPapiRequest.id))).scalar_one() == 0

    db_session.add(OddsPapiRequest(requested_at=NOW - timedelta(hours=1), endpoint="/v4/account", billable=False, status_code=200))
    db_session.commit()

    ctx_ran = TickContext(session=db_session, service=None, now=NOW, dry_run=False,
                          window_minutes=30, props_events=0, min_remaining=25, local_tz=timezone.utc, oddspapi_client=None)
    res_ran = oddspapi_step(ctx_ran)
    assert res_ran.status == "skipped" and "already ran" in res_ran.message.lower()

    steps_inc = default_steps(include_sgo=False, include_oddspapi=True)
    names_inc = [n for n, _ in steps_inc]
    assert names_inc[names_inc.index("results") + 1] == "oddspapi"

    steps_exc = default_steps(include_sgo=False, include_oddspapi=False)
    assert "oddspapi" not in [n for n, _ in steps_exc]


def test_line_movement_strategy_signs_and_small_sample_message():
    from app.services import line_movement as lm
    from app.services.oddspapi import OpenClose

    t0, t1 = NOW - timedelta(days=1), NOW
    spread = OpenClose("spreads", t0, 1.0, (1.729, 2.19), t1, 1.5, (1.99, 1.934))  # home +1 opened, closed +1.5
    path = lm.GamePath("game:1", "0022600001", NOW, {"spreads": spread}, home_score=110, away_score=105)
    res = lm.model_strategies([path], {"spreads": {"game:1": -0.7}}, {"spreads": {"game:1": 11.8}}, 1, 50)
    first = res[0]  # threshold 0.25: predicted close - open < 0 -> bet home at the open
    assert first.n == 1 and first.clv_points[0] == pytest.approx(-0.5)  # the close moved against home
    assert first.roi_open_price[0] == pytest.approx(0.729)  # home won by 5 at +1, paid at Pinnacle's 1.729
    assert any("insufficient data" in line for line in lm.format_strategies(res, "t"))
    stats = lm.movement_stats([path], 1, 50)
    assert stats[0].market == "spreads" and stats[0].mean == pytest.approx(0.5)
