"""
Offline tests for SportsGameOdds provider, parser, ingestion, and quota guard.

All fixtures strictly follow the shapes documented at https://sportsgameodds.com/docs
(this test suite does not use any captured live network responses).
"""
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Dict

import httpx
import pytest
from sqlmodel import select

from app.models import BetSide, Game, MarketType, OddsHistory, Season, Sportsbook, Team
from app.services.odds_api_service import OddsApiService
from app.services.odds_ingestion import OddsIngestionService
from app.services.odds_providers.base import OddsProvider
from app.services.odds_providers.sportsgameodds import (
    FREE_TIER_MONTHLY_OBJECT_LIMIT,
    InsufficientQuotaError,
    SportsGameOddsService,
    american_to_decimal,
    mask_key,
    parse_american_odds,
    parse_float_line,
    parse_sgo_events,
    sanitize_message,
)

# Note: The following fixture strictly reflects the documentation on sportsgameodds.com/docs,
# and is NOT a captured live response.
DOC_FIXTURE_EVENTS = {
    "success": True,
    "data": [
        {
            "eventID": "doc_evt_001",
            "status": {
                "startsAt": "2026-10-29T23:30:00.000Z",
                "started": False,
                "ended": False,
                "finalized": False,
            },
            "teams": {
                "home": {
                    "teamID": "boston_celtics",
                    "names": {
                        "long": "Boston Celtics",
                        "medium": "Celtics",
                        "short": "BOS",
                    },
                },
                "away": {
                    "teamID": "new_york_knicks",
                    "names": {
                        "long": "New York Knicks",
                        "medium": "Knicks",
                        "short": "NYK",
                    },
                },
            },
            "odds": {
                # 1. Moneyline home (available)
                "points-home-game-ml-home": {
                    "oddID": "points-home-game-ml-home",
                    "statID": "points",
                    "statEntityID": "home",
                    "periodID": "game",
                    "betTypeID": "ml",
                    "sideID": "home",
                    "byBookmaker": {
                        "draftkings": {
                            "odds": "-155",
                            "available": True,
                            "lastUpdatedAt": "2026-10-29T20:00:00Z",
                        },
                        "fanduel": {
                            "odds": "-150",
                            "available": True,
                            "lastUpdatedAt": "2026-10-29T20:05:00Z",
                        },
                        # Unavailable quote: must be skipped
                        "betmgm": {
                            "odds": "-160",
                            "available": False,
                            "lastUpdatedAt": "2026-10-29T19:50:00Z",
                        },
                    },
                },
                # 2. Moneyline away (available)
                "points-away-game-ml-away": {
                    "oddID": "points-away-game-ml-away",
                    "statID": "points",
                    "statEntityID": "away",
                    "periodID": "game",
                    "betTypeID": "ml",
                    "sideID": "away",
                    "byBookmaker": {
                        "draftkings": {
                            "odds": "+135",
                            "available": True,
                            "lastUpdatedAt": "2026-10-29T20:00:00Z",
                        },
                    },
                },
                # 3. Spread home (available)
                "points-home-game-sp-home": {
                    "oddID": "points-home-game-sp-home",
                    "statID": "points",
                    "statEntityID": "home",
                    "periodID": "game",
                    "betTypeID": "sp",
                    "sideID": "home",
                    "bookSpread": "-4.5",
                    "byBookmaker": {
                        "draftkings": {
                            "odds": "-110",
                            "spread": "-4.5",
                            "available": True,
                            "lastUpdatedAt": "2026-10-29T20:00:00Z",
                        },
                        # Overrides spread via odd-level fallback if bookmaker spread is missing
                        "caesars": {
                            "odds": "-108",
                            "available": True,
                            "lastUpdatedAt": "2026-10-29T20:01:00Z",
                        },
                    },
                },
                # 4. Spread away (available)
                "points-away-game-sp-away": {
                    "oddID": "points-away-game-sp-away",
                    "statID": "points",
                    "statEntityID": "away",
                    "periodID": "game",
                    "betTypeID": "sp",
                    "sideID": "away",
                    "byBookmaker": {
                        "draftkings": {
                            "odds": "-110",
                            "spread": "+4.5",
                            "available": True,
                            "lastUpdatedAt": "2026-10-29T20:00:00Z",
                        },
                    },
                },
                # 5. Totals over (available)
                "points-all-game-ou-over": {
                    "oddID": "points-all-game-ou-over",
                    "statID": "points",
                    "statEntityID": "all",
                    "periodID": "game",
                    "betTypeID": "ou",
                    "sideID": "over",
                    "bookOverUnder": "224.5",
                    "byBookmaker": {
                        "draftkings": {
                            "odds": "-112",
                            "overUnder": "224.5",
                            "available": True,
                            "lastUpdatedAt": "2026-10-29T20:00:00Z",
                        },
                    },
                },
                # 6. Totals under (available)
                "points-all-game-ou-under": {
                    "oddID": "points-all-game-ou-under",
                    "statID": "points",
                    "statEntityID": "all",
                    "periodID": "game",
                    "betTypeID": "ou",
                    "sideID": "under",
                    "byBookmaker": {
                        "draftkings": {
                            "odds": "-108",
                            "overUnder": "224.5",
                            "available": True,
                            "lastUpdatedAt": "2026-10-29T20:00:00Z",
                        },
                    },
                },
                # 7. Non-game period (1st half): must be ignored
                "points-home-1h-ml-home": {
                    "oddID": "points-home-1h-ml-home",
                    "statID": "points",
                    "statEntityID": "home",
                    "periodID": "1h",
                    "betTypeID": "ml",
                    "sideID": "home",
                    "byBookmaker": {
                        "draftkings": {"odds": "-120", "available": True},
                    },
                },
                # 8. Malformed odds value (-50 is not valid American odds): must be ignored
                "points-home-game-sp-malformed": {
                    "oddID": "points-home-game-sp-malformed",
                    "statID": "points",
                    "statEntityID": "home",
                    "periodID": "game",
                    "betTypeID": "sp",
                    "sideID": "home",
                    "byBookmaker": {
                        "draftkings": {"odds": "-50", "spread": "-4.5", "available": True},
                    },
                },
                # 9. Missing spread value: must be ignored without raising
                "points-home-game-sp-no-line": {
                    "oddID": "points-home-game-sp-no-line",
                    "statID": "points",
                    "statEntityID": "home",
                    "periodID": "game",
                    "betTypeID": "sp",
                    "sideID": "home",
                    "byBookmaker": {
                        "draftkings": {"odds": "-110", "available": True},
                    },
                },
            },
        }
    ],
    "nextCursor": "cursor_token_123",
}


@pytest.fixture
def mock_sgo_http():
    """Returns a client factory backed by a mock transport."""
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        path = request.url.path
        if path.endswith("/account/usage"):
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "data": {
                        "plan": "Amateur",
                        "requestsPerMinuteLimit": 10,
                        "objectsPerMonthLimit": 2500,
                        "objectsUsedThisMonth": 200,
                        "objectsRemainingThisMonth": 2300,
                        "resetDate": "2026-11-01T00:00:00Z",
                    },
                },
            )
        if path.endswith("/events"):
            return httpx.Response(200, json=DOC_FIXTURE_EVENTS)
        return httpx.Response(404, json={"success": False, "message": "Not found"})

    transport = httpx.MockTransport(handler)
    return transport, calls


# -----------------------------------------------------------------------------
# 1. Parsing tests (ml, sp, ou, unavailable skipped, malformed ignored)
# -----------------------------------------------------------------------------

def test_parse_sgo_events_extracts_game_lines():
    quotes = parse_sgo_events(DOC_FIXTURE_EVENTS)
    # Expected valid quotes:
    # ml home: draftkings (-155), fanduel (-150) [betmgm skipped because available=False] -> 2
    # ml away: draftkings (+135) -> 1
    # sp home: draftkings (-110, -4.5), caesars (-108, -4.5 from fallback) -> 2
    # sp away: draftkings (-110, +4.5) -> 1
    # ou over: draftkings (-112, 224.5) -> 1
    # ou under: draftkings (-108, 224.5) -> 1
    # Total = 8 quotes
    assert len(quotes) == 8

    # Verify moneyline
    mls = [q for q in quotes if q.market_key == "h2h"]
    assert len(mls) == 3
    assert all(q.line is None for q in mls)
    dk_ml_home = next(q for q in mls if q.bookmaker_key == "draftkings" and q.side == "home")
    assert dk_ml_home.price_american == -155
    assert dk_ml_home.home_team == "Boston Celtics"
    assert dk_ml_home.away_team == "New York Knicks"
    assert dk_ml_home.bookmaker_title == "DraftKings"
    assert dk_ml_home.book_last_update == "2026-10-29T20:00:00Z"

    # Verify spread
    sps = [q for q in quotes if q.market_key == "spreads"]
    assert len(sps) == 3
    caesars_sp = next(q for q in sps if q.bookmaker_key == "caesars")
    assert caesars_sp.line == -4.5
    assert caesars_sp.price_american == -108
    assert caesars_sp.bookmaker_title == "Caesars"

    dk_sp_away = next(q for q in sps if q.bookmaker_key == "draftkings" and q.side == "away")
    assert dk_sp_away.line == 4.5
    assert dk_sp_away.price_american == -110

    # Verify totals
    ous = [q for q in quotes if q.market_key == "totals"]
    assert len(ous) == 2
    over = next(q for q in ous if q.side == "over")
    under = next(q for q in ous if q.side == "under")
    assert over.line == 224.5
    assert over.price_american == -112
    assert under.line == 224.5
    assert under.price_american == -108


def test_unavailable_quotes_are_skipped():
    quotes = parse_sgo_events(DOC_FIXTURE_EVENTS)
    betmgm_quotes = [q for q in quotes if q.bookmaker_key == "betmgm"]
    assert len(betmgm_quotes) == 0  # betmgm had available: False


def test_unknown_or_malformed_odds_are_ignored():
    quotes = parse_sgo_events(DOC_FIXTURE_EVENTS)
    # Check that 1st half odds ('1h') were not parsed
    assert not any("1h" in q.event_id for q in quotes)
    # Check that -50 odds and missing line were skipped
    assert not any(q.price_american == -50 for q in quotes)


def test_empty_or_invalid_payload_returns_empty_list():
    assert parse_sgo_events(None) == []
    assert parse_sgo_events({}) == []
    assert parse_sgo_events({"data": "not a list"}) == []
    assert parse_sgo_events({"data": [{}]}) == []


# -----------------------------------------------------------------------------
# 2. American to Decimal conversion tests
# -----------------------------------------------------------------------------

def test_american_to_decimal_conversion():
    assert american_to_decimal(-110) == 1.909
    assert american_to_decimal(-150) == 1.667
    assert american_to_decimal(+100) == 2.0
    assert american_to_decimal(+130) == 2.300
    assert american_to_decimal(+250) == 3.500
    assert american_to_decimal(0) == 1.0


def test_parse_american_odds_validation():
    assert parse_american_odds("-110") == -110
    assert parse_american_odds("+105") == 105
    assert parse_american_odds(150) == 150
    assert parse_american_odds(-150) == -150
    # Values between -100 and +100 are invalid American odds
    assert parse_american_odds(0) is None
    assert parse_american_odds(50) is None
    assert parse_american_odds(-50) is None
    assert parse_american_odds("invalid") is None
    assert parse_american_odds(None) is None


def test_parse_float_line_validation():
    assert parse_float_line("-4.5") == -4.5
    assert parse_float_line("+4.5") == 4.5
    assert parse_float_line(224.5) == 224.5
    assert parse_float_line("invalid") is None
    assert parse_float_line(None) is None


# -----------------------------------------------------------------------------
# 3. Key masking and sanitization
# -----------------------------------------------------------------------------

def test_key_masking():
    assert mask_key(None) == ""
    assert mask_key("") == ""
    assert mask_key("short") == "***"
    assert mask_key("12345678") == "***"
    assert mask_key("sgo_api_key_secret_123") == "sgo...123"


def test_sanitize_message():
    key = "secret_key_abc_999"
    msg = f"Request to https://api.sportsgameodds.com?apiKey={key} failed"
    sanitized = sanitize_message(msg, key)
    assert key not in sanitized
    assert "sec...999" in sanitized


# -----------------------------------------------------------------------------
# 4. Service configuration and disabled without key
# -----------------------------------------------------------------------------

def test_disabled_without_key():
    svc_empty = SportsGameOddsService(api_key="")
    assert not svc_empty.is_configured
    assert svc_empty.fetch_game_lines() == []

    svc_placeholder = SportsGameOddsService(api_key="your_sportsgameodds_api_key_here")
    assert not svc_placeholder.is_configured
    assert svc_placeholder.fetch_game_lines() == []


def test_odds_provider_protocol_compliance():
    sgo_svc = SportsGameOddsService(api_key="sgo_valid_key_123")
    assert isinstance(sgo_svc, OddsProvider)
    assert sgo_svc.name == "sportsgameodds"
    assert sgo_svc.is_configured

    toa_svc = OddsApiService(api_key="toa_valid_key_123")
    assert isinstance(toa_svc, OddsProvider)
    assert toa_svc.name == "the_odds_api"


# -----------------------------------------------------------------------------
# 5. Quota guard and usage tracking
# -----------------------------------------------------------------------------

def test_quota_guard_stops_at_floor(tmp_path):
    cache_file = tmp_path / "usage.json"
    svc = SportsGameOddsService(
        api_key="sgo_valid_key_123",
        min_remaining_objects=100,
        usage_cache_path=cache_file,
    )
    # Set remaining objects below the floor
    svc.objects_remaining = 50

    allowed, reason = svc.check_quota(expected_objects=1)
    assert not allowed
    assert "fall below floor" in reason

    with pytest.raises(InsufficientQuotaError):
        svc.fetch_game_lines()


def test_fetch_account_usage_updates_remaining(mock_sgo_http, tmp_path):
    transport, _ = mock_sgo_http
    cache_file = tmp_path / "usage.json"
    svc = SportsGameOddsService(
        api_key="sgo_valid_key_123",
        transport=transport,
        usage_cache_path=cache_file,
    )
    usage = svc.fetch_account_usage()
    assert usage is not None
    assert usage.get("objectsRemainingThisMonth") == 2300
    assert svc.objects_remaining == 2300

    # Local usage cache should have recorded the value
    assert cache_file.exists()
    with open(cache_file, "r") as f:
        data = json.load(f)
    assert data["objects_remaining"] == 2300


def test_record_objects_consumed_updates_local_cache(tmp_path):
    cache_file = tmp_path / "usage.json"
    svc = SportsGameOddsService(
        api_key="sgo_valid_key_123",
        usage_cache_path=cache_file,
    )
    svc.objects_remaining = 2500
    svc.record_objects_consumed(2)

    assert svc.objects_remaining == 2498
    with open(cache_file, "r") as f:
        data = json.load(f)
    assert data["objects_used"] == 2
    assert data["objects_remaining"] == 2498


# -----------------------------------------------------------------------------
# 6. Game matching and ingestion (never create game, unmatched counted/logged)
# -----------------------------------------------------------------------------

@pytest.fixture
def ingestion_world(db_session):
    season = Season(
        season_label="2026-27",
        start_date=date(2026, 10, 20),
        end_date=date(2027, 6, 30),
        is_active=True,
    )
    db_session.add(season)
    bos = Team(abbreviation="BOS", full_name="Boston Celtics", city="Boston", conference="East", division="Atlantic")
    nyk = Team(abbreviation="NYK", full_name="New York Knicks", city="New York", conference="East", division="Atlantic")
    lal = Team(abbreviation="LAL", full_name="Los Angeles Lakers", city="Los Angeles", conference="West", division="Pacific")
    db_session.add(bos)
    db_session.add(nyk)
    db_session.add(lal)
    db_session.commit()

    # Create an existing game between BOS and NYK
    game = Game(
        provider_event_id="toa_event_bos_nyk_001",
        season_id=season.id,
        home_team_id=bos.id,
        away_team_id=nyk.id,
        commence_time=datetime(2026, 10, 29, 23, 30, tzinfo=timezone.utc),
        status="scheduled",
    )
    db_session.add(game)
    db_session.commit()

    return OddsIngestionService(db_session), game, bos, nyk, lal


def test_ingest_secondary_game_quotes_matches_existing_game(ingestion_world):
    service, game, bos, nyk, lal = ingestion_world
    captured_at = datetime(2026, 10, 29, 20, 10, tzinfo=timezone.utc)

    quotes = parse_sgo_events(DOC_FIXTURE_EVENTS)
    initial_game_count = len(service.session.exec(select(Game)).all())

    result = service.ingest_secondary_game_quotes(quotes, captured_at)

    # All 8 quotes belong to the BOS vs NYK game which exists
    assert result.inserted == 8
    assert result.skipped_unmatched == 0

    # Crucial rule: NEVER create a game from secondary feed!
    final_game_count = len(service.session.exec(select(Game)).all())
    assert final_game_count == initial_game_count

    # Check that odds_history rows were inserted with the existing game's ID
    stored_quotes = service.session.exec(select(OddsHistory).where(OddsHistory.game_id == game.id)).all()
    assert len(stored_quotes) == 8

    # Check book_last_update is preserved from lastUpdatedAt
    dk_ml = next(q for q in stored_quotes if q.market == MarketType.h2h and q.side == BetSide.home and q.price_american == -155)
    assert dk_ml.book_last_update.replace(tzinfo=timezone.utc) == datetime(2026, 10, 29, 20, 0, tzinfo=timezone.utc)

    # Check sportsbooks created/upserted
    books = service.session.exec(select(Sportsbook)).all()
    book_keys = {b.key for b in books}
    assert "draftkings" in book_keys
    assert "fanduel" in book_keys
    assert "caesars" in book_keys
    # SGO books are not sharp
    caesars_sb = next(b for b in books if b.key == "caesars")
    assert not caesars_sb.is_sharp
    assert caesars_sb.region == "us"


def test_ingest_secondary_game_quotes_unmatched_event_is_skipped_and_never_created(ingestion_world):
    service, game, bos, nyk, lal = ingestion_world
    captured_at = datetime(2026, 10, 29, 20, 10, tzinfo=timezone.utc)

    # Event for LAL @ BOS which does NOT exist in the database
    unmatched_payload = {
        "success": True,
        "data": [
            {
                "eventID": "unmatched_lal_bos_999",
                "status": {"startsAt": "2026-10-31T01:00:00.000Z"},
                "teams": {
                    "home": {"names": {"short": "BOS", "long": "Boston Celtics"}},
                    "away": {"names": {"short": "LAL", "long": "Los Angeles Lakers"}},
                },
                "odds": {
                    "points-home-game-ml-home": {
                        "periodID": "game",
                        "betTypeID": "ml",
                        "sideID": "home",
                        "byBookmaker": {
                            "draftkings": {"odds": "-140", "available": True},
                        },
                    }
                },
            }
        ],
    }

    quotes = parse_sgo_events(unmatched_payload)
    assert len(quotes) == 1

    initial_game_count = len(service.session.exec(select(Game)).all())
    result = service.ingest_secondary_game_quotes(quotes, captured_at)

    # Unmatched quote must be skipped and counted, NEVER creating a game
    assert result.inserted == 0
    assert result.skipped_unmatched == 1

    final_game_count = len(service.session.exec(select(Game)).all())
    assert final_game_count == initial_game_count


def test_retry_on_server_error(mock_sgo_http):
    transport, calls = mock_sgo_http
    call_count = 0

    def flaking_handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return httpx.Response(500, json={"error": "temporary server error"})
        return httpx.Response(200, json=DOC_FIXTURE_EVENTS)

    svc = SportsGameOddsService(
        api_key="sgo_valid_key_123",
        transport=httpx.MockTransport(flaking_handler),
    )
    quotes = svc.fetch_game_lines()
    assert call_count == 2
    assert len(quotes) == 8
    assert svc.last_call_ok


def test_retry_sanitizes_key_in_transient_logs(caplog):
    import logging
    raw_key = "sgo_super_secret_key_777"

    call_count = 0
    def failing_handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise httpx.ConnectError(f"Connection failed to url with key={raw_key}")
        return httpx.Response(200, json=DOC_FIXTURE_EVENTS)

    svc = SportsGameOddsService(
        api_key=raw_key,
        transport=httpx.MockTransport(failing_handler),
    )

    with caplog.at_level(logging.WARNING):
        quotes = svc.fetch_game_lines()

    assert call_count == 2
    assert len(quotes) == 8
    # Raw key must NOT be present in log output
    assert raw_key not in caplog.text
    # Masked key should appear in log
    assert "sgo...777" in caplog.text


def test_record_objects_consumed_preserves_persisted_remaining(tmp_path):
    cache_file = tmp_path / "usage.json"
    current_month = datetime.now(timezone.utc).strftime("%Y-%m")
    # Simulate a prior run that fetched remaining=2300 from /account/usage
    with open(cache_file, "w") as f:
        json.dump({
            "month": current_month,
            "objects_used": 200,
            "objects_remaining": 2300,
            "last_updated": "2026-10-28T10:00:00Z",
        }, f)

    # New service instance with objects_remaining=None (fresh process)
    svc = SportsGameOddsService(
        api_key="sgo_valid_key_123",
        usage_cache_path=cache_file,
    )
    assert svc.objects_remaining is None

    svc.record_objects_consumed(5)
    assert svc.objects_remaining == 2295

    with open(cache_file, "r") as f:
        data = json.load(f)
    assert data["objects_remaining"] == 2295
    assert data["objects_used"] == 205


def test_record_objects_consumed_resets_on_month_rollover(tmp_path):
    cache_file = tmp_path / "usage.json"
    # Old month
    with open(cache_file, "w") as f:
        json.dump({
            "month": "2026-09",
            "objects_used": 2400,
            "objects_remaining": 100,
            "last_updated": "2026-09-30T23:59:00Z",
        }, f)

    svc = SportsGameOddsService(
        api_key="sgo_valid_key_123",
        usage_cache_path=cache_file,
    )
    svc.record_objects_consumed(10)

    current_month = datetime.now(timezone.utc).strftime("%Y-%m")
    with open(cache_file, "r") as f:
        data = json.load(f)
    assert data["month"] == current_month
    assert data["objects_used"] == 10
    assert data["objects_remaining"] == FREE_TIER_MONTHLY_OBJECT_LIMIT - 10


# -----------------------------------------------------------------------------
# 7. Regression tests for live observation shape (WP-S4, 2026-10-31)
# -----------------------------------------------------------------------------

# Note: The following synthetic payload is shaped after a live observation (2026-10-31),
# but uses entirely synthetic/fake event IDs, fake player IDs, and made-up odds prices.
# It is NOT captured data and does not contain any real odds.
SYNTHETIC_LIVE_SHAPED_PAYLOAD = {
    "success": True,
    "notice": "Response is missing 12 bookmaker odds. Upgrade your API key to access all data from this query.",
    "data": [
        {
            "eventID": "synth_evt_live_001",
            "status": {
                "startsAt": "2026-11-01T01:00:00.000Z",
                "started": False,
                "ended": False,
                "finalized": False,
            },
            "teams": {
                "home": {
                    "teamID": "synth_okc",
                    "names": {"long": "Oklahoma City Thunder", "short": "OKC"},
                },
                "away": {
                    "teamID": "synth_den",
                    "names": {"long": "Denver Nuggets", "short": "DEN"},
                },
            },
            "odds": {
                # --- MAIN MARKETS (Full-game) ---
                # 1. Main ML Home (draftkings, fanduel)
                "points-home-game-ml-home": {
                    "oddID": "points-home-game-ml-home",
                    "statID": "points",
                    "statEntityID": "home",
                    "periodID": "game",
                    "betTypeID": "ml",
                    "sideID": "home",
                    "byBookmaker": {
                        "draftkings": {"odds": "-140", "available": True, "lastUpdatedAt": "2026-10-31T18:00:00Z"},
                        "fanduel": {"odds": "-135", "available": True, "lastUpdatedAt": "2026-10-31T18:05:00Z"},
                    },
                },
                # 2. Main ML Away (draftkings, fanduel)
                "points-away-game-ml-away": {
                    "oddID": "points-away-game-ml-away",
                    "statID": "points",
                    "statEntityID": "away",
                    "periodID": "game",
                    "betTypeID": "ml",
                    "sideID": "away",
                    "byBookmaker": {
                        "draftkings": {"odds": "+120", "available": True, "lastUpdatedAt": "2026-10-31T18:00:00Z"},
                        "fanduel": {"odds": "+115", "available": True, "lastUpdatedAt": "2026-10-31T18:05:00Z"},
                    },
                },
                # 3. Main Spread Home (draftkings, fanduel)
                "points-home-game-sp-home": {
                    "oddID": "points-home-game-sp-home",
                    "statID": "points",
                    "statEntityID": "home",
                    "periodID": "game",
                    "betTypeID": "sp",
                    "sideID": "home",
                    "bookSpread": "-3.5",
                    "byBookmaker": {
                        "draftkings": {"odds": "-110", "spread": "-3.5", "available": True, "lastUpdatedAt": "2026-10-31T18:00:00Z"},
                        "fanduel": {"odds": "-108", "spread": "-3.5", "available": True, "lastUpdatedAt": "2026-10-31T18:05:00Z"},
                    },
                },
                # 4. Main Spread Away (draftkings, fanduel)
                "points-away-game-sp-away": {
                    "oddID": "points-away-game-sp-away",
                    "statID": "points",
                    "statEntityID": "away",
                    "periodID": "game",
                    "betTypeID": "sp",
                    "sideID": "away",
                    "bookSpread": "+3.5",
                    "byBookmaker": {
                        "draftkings": {"odds": "-110", "spread": "+3.5", "available": True, "lastUpdatedAt": "2026-10-31T18:00:00Z"},
                        "fanduel": {"odds": "-112", "spread": "+3.5", "available": True, "lastUpdatedAt": "2026-10-31T18:05:00Z"},
                    },
                },
                # 5. Main Game Total Over (draftkings, fanduel)
                "points-all-game-ou-over": {
                    "oddID": "points-all-game-ou-over",
                    "statID": "points",
                    "statEntityID": "all",
                    "periodID": "game",
                    "betTypeID": "ou",
                    "sideID": "over",
                    "bookOverUnder": "221.5",
                    "byBookmaker": {
                        "draftkings": {"odds": "-110", "overUnder": "221.5", "available": True, "lastUpdatedAt": "2026-10-31T18:00:00Z"},
                        "fanduel": {"odds": "-112", "overUnder": "221.5", "available": True, "lastUpdatedAt": "2026-10-31T18:05:00Z"},
                    },
                },
                # 6. Main Game Total Under (draftkings, fanduel)
                "points-all-game-ou-under": {
                    "oddID": "points-all-game-ou-under",
                    "statID": "points",
                    "statEntityID": "all",
                    "periodID": "game",
                    "betTypeID": "ou",
                    "sideID": "under",
                    "bookOverUnder": "221.5",
                    "byBookmaker": {
                        "draftkings": {"odds": "-110", "overUnder": "221.5", "available": True, "lastUpdatedAt": "2026-10-31T18:00:00Z"},
                        "fanduel": {"odds": "-108", "overUnder": "221.5", "available": True, "lastUpdatedAt": "2026-10-31T18:05:00Z"},
                    },
                },

                # --- NON-MAIN MARKETS (Must be filtered out) ---
                # A. Team Totals (statEntityID home/away, betTypeID ou, periodID game)
                "points-home-game-ou-over": {
                    "oddID": "points-home-game-ou-over",
                    "statID": "points",
                    "statEntityID": "home",
                    "periodID": "game",
                    "betTypeID": "ou",
                    "sideID": "over",
                    "bookOverUnder": "112.5",
                    "byBookmaker": {
                        "draftkings": {"odds": "-115", "overUnder": "112.5", "available": True},
                        "fanduel": {"odds": "-110", "overUnder": "112.5", "available": True},
                    },
                },
                "points-home-game-ou-under": {
                    "oddID": "points-home-game-ou-under",
                    "statID": "points",
                    "statEntityID": "home",
                    "periodID": "game",
                    "betTypeID": "ou",
                    "sideID": "under",
                    "bookOverUnder": "112.5",
                    "byBookmaker": {
                        "draftkings": {"odds": "-115", "overUnder": "112.5", "available": True},
                        "fanduel": {"odds": "-110", "overUnder": "112.5", "available": True},
                    },
                },
                "points-away-game-ou-over": {
                    "oddID": "points-away-game-ou-over",
                    "statID": "points",
                    "statEntityID": "away",
                    "periodID": "game",
                    "betTypeID": "ou",
                    "sideID": "over",
                    "bookOverUnder": "109.5",
                    "byBookmaker": {
                        "draftkings": {"odds": "-110", "overUnder": "109.5", "available": True},
                        "fanduel": {"odds": "-115", "overUnder": "109.5", "available": True},
                    },
                },
                "points-away-game-ou-under": {
                    "oddID": "points-away-game-ou-under",
                    "statID": "points",
                    "statEntityID": "away",
                    "periodID": "game",
                    "betTypeID": "ou",
                    "sideID": "under",
                    "bookOverUnder": "109.5",
                    "byBookmaker": {
                        "draftkings": {"odds": "-110", "overUnder": "109.5", "available": True},
                        "fanduel": {"odds": "-115", "overUnder": "109.5", "available": True},
                    },
                },

                # B. Player Points Props (statEntityID player id, betTypeID ou, periodID game)
                "points-FAKE_PLAYER_1_NBA-game-ou-over": {
                    "oddID": "points-FAKE_PLAYER_1_NBA-game-ou-over",
                    "statID": "points",
                    "statEntityID": "FAKE_PLAYER_1_NBA",
                    "periodID": "game",
                    "betTypeID": "ou",
                    "sideID": "over",
                    "bookOverUnder": "19.5",
                    "byBookmaker": {
                        "draftkings": {"odds": "-115", "overUnder": "19.5", "available": True},
                        "fanduel": {"odds": "-120", "overUnder": "19.5", "available": True},
                    },
                },
                "points-FAKE_PLAYER_1_NBA-game-ou-under": {
                    "oddID": "points-FAKE_PLAYER_1_NBA-game-ou-under",
                    "statID": "points",
                    "statEntityID": "FAKE_PLAYER_1_NBA",
                    "periodID": "game",
                    "betTypeID": "ou",
                    "sideID": "under",
                    "bookOverUnder": "19.5",
                    "byBookmaker": {
                        "draftkings": {"odds": "-115", "overUnder": "19.5", "available": True},
                        "fanduel": {"odds": "-110", "overUnder": "19.5", "available": True},
                    },
                },

                # C. 1st Half Total (periodID 1h)
                "points-all-1h-ou-over": {
                    "oddID": "points-all-1h-ou-over",
                    "statID": "points",
                    "statEntityID": "all",
                    "periodID": "1h",
                    "betTypeID": "ou",
                    "sideID": "over",
                    "bookOverUnder": "110.5",
                    "byBookmaker": {
                        "draftkings": {"odds": "-110", "overUnder": "110.5", "available": True},
                        "fanduel": {"odds": "-110", "overUnder": "110.5", "available": True},
                    },
                },
                "points-all-1h-ou-under": {
                    "oddID": "points-all-1h-ou-under",
                    "statID": "points",
                    "statEntityID": "all",
                    "periodID": "1h",
                    "betTypeID": "ou",
                    "sideID": "under",
                    "bookOverUnder": "110.5",
                    "byBookmaker": {
                        "draftkings": {"odds": "-110", "overUnder": "110.5", "available": True},
                        "fanduel": {"odds": "-110", "overUnder": "110.5", "available": True},
                    },
                },

                # D. Even / Odd (betTypeID eo)
                "points-all-game-eo-odd": {
                    "oddID": "points-all-game-eo-odd",
                    "statID": "points",
                    "statEntityID": "all",
                    "periodID": "game",
                    "betTypeID": "eo",
                    "sideID": "odd",
                    "byBookmaker": {
                        "draftkings": {"odds": "-105", "available": True},
                        "fanduel": {"odds": "-105", "available": True},
                    },
                },
                "points-all-game-eo-even": {
                    "oddID": "points-all-game-eo-even",
                    "statID": "points",
                    "statEntityID": "all",
                    "periodID": "game",
                    "betTypeID": "eo",
                    "sideID": "even",
                    "byBookmaker": {
                        "draftkings": {"odds": "-115", "available": True},
                        "fanduel": {"odds": "-115", "available": True},
                    },
                },

                # E. Regulation 3-way Moneyline (periodID reg, betTypeID ml3way)
                "points-home-reg-ml3way-home": {
                    "oddID": "points-home-reg-ml3way-home",
                    "statID": "points",
                    "statEntityID": "home",
                    "periodID": "reg",
                    "betTypeID": "ml3way",
                    "sideID": "home",
                    "byBookmaker": {
                        "draftkings": {"odds": "-125", "available": True},
                        "fanduel": {"odds": "-120", "available": True},
                    },
                },
                "points-away-reg-ml3way-away": {
                    "oddID": "points-away-reg-ml3way-away",
                    "statID": "points",
                    "statEntityID": "away",
                    "periodID": "reg",
                    "betTypeID": "ml3way",
                    "sideID": "away",
                    "byBookmaker": {
                        "draftkings": {"odds": "+135", "available": True},
                        "fanduel": {"odds": "+130", "available": True},
                    },
                },
                "points-draw-reg-ml3way-draw": {
                    "oddID": "points-draw-reg-ml3way-draw",
                    "statID": "points",
                    "statEntityID": "draw",
                    "periodID": "reg",
                    "betTypeID": "ml3way",
                    "sideID": "draw",
                    "byBookmaker": {
                        "draftkings": {"odds": "+950", "available": True},
                        "fanduel": {"odds": "+900", "available": True},
                    },
                },
            },
        }
    ],
}


def test_parse_sgo_events_synthetic_live_shaped_filters_non_main_markets():
    quotes = parse_sgo_events(SYNTHETIC_LIVE_SHAPED_PAYLOAD)

    # Exactly 12 main market quotes:
    # 2 books x 2 sides x 3 markets = 12 quotes
    assert len(quotes) == 12

    # Check breakdown by market
    market_counts = {}
    book_counts = {}
    for q in quotes:
        market_counts[q.market_key] = market_counts.get(q.market_key, 0) + 1
        book_counts[q.bookmaker_key] = book_counts.get(q.bookmaker_key, 0) + 1

    assert market_counts == {"h2h": 4, "spreads": 4, "totals": 4}
    assert book_counts == {"draftkings": 6, "fanduel": 6}

    # Verify totals: only full game total (221.5), absolutely no team totals (112.5, 109.5),
    # player props (19.5), or 1h totals (110.5)
    totals = [q for q in quotes if q.market_key == "totals"]
    assert len(totals) == 4
    for t in totals:
        assert t.line == 221.5
        assert t.side in ("over", "under")

    # Verify spreads: only -3.5 / +3.5
    spreads = [q for q in quotes if q.market_key == "spreads"]
    assert len(spreads) == 4
    for s in spreads:
        assert abs(s.line) == 3.5
        assert s.side in ("home", "away")

    # Verify h2h
    h2hs = [q for q in quotes if q.market_key == "h2h"]
    assert len(h2hs) == 4
    for h in h2hs:
        assert h.line is None
        assert h.side in ("home", "away")

    # Assert no non-main markets leaked into the parsed quotes
    for q in quotes:
        assert "FAKE_PLAYER" not in q.event_id
        assert "1h" not in q.event_id
        assert q.line not in (112.5, 109.5, 19.5, 110.5)


def test_parse_sgo_events_synthetic_live_shaped_odd_id_fallback():
    import copy
    payload_copy = copy.deepcopy(SYNTHETIC_LIVE_SHAPED_PAYLOAD)
    event_odds = payload_copy["data"][0]["odds"]
    for odd_obj in event_odds.values():
        for field in ("statID", "statEntityID", "periodID", "betTypeID", "sideID"):
            odd_obj.pop(field, None)

    quotes = parse_sgo_events(payload_copy)
    assert len(quotes) == 12
    market_counts = {}
    book_counts = {}
    for q in quotes:
        market_counts[q.market_key] = market_counts.get(q.market_key, 0) + 1
        book_counts[q.bookmaker_key] = book_counts.get(q.bookmaker_key, 0) + 1

    assert market_counts == {"h2h": 4, "spreads": 4, "totals": 4}
    assert book_counts == {"draftkings": 6, "fanduel": 6}


def test_fetch_game_lines_logs_notice_at_info(caplog):
    import logging

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=SYNTHETIC_LIVE_SHAPED_PAYLOAD)

    svc = SportsGameOddsService(
        api_key="sgo_notice_test_key_123",
        transport=httpx.MockTransport(handler),
    )
    with caplog.at_level(logging.INFO):
        quotes = svc.fetch_game_lines()

    assert len(quotes) == 12
    notice_records = [
        r for r in caplog.records
        if "SportsGameOddsService notice:" in r.message
    ]
    assert len(notice_records) == 1
    rec = notice_records[0]
    assert rec.levelno == logging.INFO
    assert "Response is missing 12 bookmaker odds" in rec.message
    # Ensure key is masked if present
    assert "sgo_notice_test_key_123" not in rec.message
    # Ensure payload data is not dumped into log
    assert "synth_evt_live_001" not in rec.message
