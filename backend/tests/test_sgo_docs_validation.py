"""
Validation tests for SportsGameOdds parser, ingestion, and account usage
against verbatim example responses from the provider's official documentation.

Documentation sources:
- https://sportsgameodds.com/docs/endpoints/getEvents
- https://sportsgameodds.com/docs/data-types/odds
- https://sportsgameodds.com/openapi.json
- https://sportsgameodds.com/docs/endpoints/getUsageData
"""
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict

import httpx
import pytest
from sqlmodel import select

from app.models import BetSide, Game, MarketType, OddsHistory, Season, Sportsbook, Team
from app.services.odds_ingestion import OddsIngestionService
from app.services.odds_providers.sportsgameodds import (
    BOOKMAKER_TITLES,
    SportsGameOddsService,
    american_to_decimal,
    parse_american_odds,
    parse_float_line,
    parse_sgo_events,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "sgo_docs_examples"


@pytest.fixture
def doc_future_events() -> Dict[str, Any]:
    with open(FIXTURES_DIR / "get_events_future.json", "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def doc_live_events() -> Dict[str, Any]:
    with open(FIXTURES_DIR / "events_live.json", "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def doc_past_events() -> Dict[str, Any]:
    with open(FIXTURES_DIR / "events_past_match.json", "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def doc_odds_snippet() -> Dict[str, Any]:
    with open(FIXTURES_DIR / "odds_data_type.json", "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def doc_account_usage() -> Dict[str, Any]:
    with open(FIXTURES_DIR / "account_usage.json", "r", encoding="utf-8") as f:
        return json.load(f)


# -----------------------------------------------------------------------------
# 1. Validation against getEvents future documentation example
# -----------------------------------------------------------------------------

def test_parse_sgo_docs_future_example(doc_future_events):
    """
    Validates parse_sgo_events against the official GET /events future example.
    3 events total (Bundesliga, Ligue 1, Serie A).
    Asserts:
    - Exactly 66 valid game lines extracted (42 h2h, 2 spreads, 22 totals).
    - Non-point props (weightedCards, cornerKicks, firstToScore) are skipped.
    - Partial period odds (1h) are skipped.
    - 3-way moneylines (ml3way) are skipped.
    - Decimal prices are valid and > 1.0.
    - Spread and over/under lines are parsed to floats.
    - Timestamps preserved from lastUpdatedAt.
    """
    quotes = parse_sgo_events(doc_future_events)
    assert len(quotes) == 66

    mls = [q for q in quotes if q.market_key == "h2h"]
    sps = [q for q in quotes if q.market_key == "spreads"]
    ous = [q for q in quotes if q.market_key == "totals"]

    assert len(mls) == 42
    assert len(sps) == 2
    assert len(ous) == 22

    # Verify event distribution: Event 0 has 24, Event 1 has 20, Event 2 has 22
    by_event = {}
    for q in quotes:
        by_event[q.event_id] = by_event.get(q.event_id, 0) + 1
    assert by_event["IWYZfq3CzbMNV4bbIpR2"] == 24
    assert by_event["trulBe8G1Fwl0n9qV2zF"] == 20
    assert by_event["xhnJqYBn15iogRYEHUlI"] == 22

    # Spreads: only Bovada on Event 0 has available spread quotes (+0.5 and -0.5)
    for sp in sps:
        assert sp.bookmaker_key == "bovada"
        assert sp.line in (-0.5, 0.5)
        assert sp.price_american in (-122, 102)

    # Totals: lines are float 1.5, 2.0, or 2.5
    for ou in ous:
        assert ou.line in (1.5, 2.0, 2.5)
        assert ou.side in ("over", "under")
        assert ou.price_american is not None

    # Verify price conversions and timestamps
    for q in quotes:
        dec = american_to_decimal(q.price_american)
        assert dec > 1.0
        assert q.book_last_update is not None
        assert "T" in q.book_last_update

    # Verify that no non-point props leaked into quotes
    assert not any("weightedCards" in q.event_id for q in quotes)
    assert not any("cornerKicks" in q.event_id for q in quotes)
    assert not any("firstToScore" in q.event_id for q in quotes)


# -----------------------------------------------------------------------------
# 2. Validation against live event documentation example
# -----------------------------------------------------------------------------

def test_parse_sgo_docs_live_example(doc_live_events):
    """
    Validates parse_sgo_events against the official live event example (Tennis WTA).
    Asserts:
    - Exactly 6 points quotes extracted (2 h2h, 2 spreads, 2 totals).
    - Pinnacle quotes are available and parsed.
    - Tennis non-point stats ('games', 'breakPoints') are filtered out.
    - Partial period ('1s' - 1st set) is filtered out.
    """
    quotes = parse_sgo_events(doc_live_events)
    assert len(quotes) == 6

    assert all(q.bookmaker_key == "pinnacle" for q in quotes)
    assert all(q.bookmaker_title == "Pinnacle" for q in quotes)

    mls = [q for q in quotes if q.market_key == "h2h"]
    assert len(mls) == 2
    away_ml = next(q for q in mls if q.side == "away")
    home_ml = next(q for q in mls if q.side == "home")
    assert away_ml.price_american == -117
    assert home_ml.price_american == 100

    sps = [q for q in quotes if q.market_key == "spreads"]
    assert len(sps) == 2
    away_sp = next(q for q in sps if q.side == "away")
    home_sp = next(q for q in sps if q.side == "home")
    assert away_sp.line == 1.5
    assert away_sp.price_american == -357
    assert home_sp.line == -1.5
    assert home_sp.price_american == 306

    ous = [q for q in quotes if q.market_key == "totals"]
    assert len(ous) == 2
    over_ou = next(q for q in ous if q.side == "over")
    under_ou = next(q for q in ous if q.side == "under")
    assert over_ou.line == 2.5
    assert over_ou.price_american == -357
    assert under_ou.line == 2.5
    assert under_ou.price_american == 306


# -----------------------------------------------------------------------------
# 3. Validation against past match documentation example
# -----------------------------------------------------------------------------

def test_parse_sgo_docs_past_match_example(doc_past_events):
    """
    Validates parse_sgo_events against the official completed match example (MLB).
    All quotes in past matches have available: false.
    Asserts:
    - 0 quotes parsed (all unavailable quotes skipped).
    - Completed / closed matches do not generate active quotes.
    """
    quotes = parse_sgo_events(doc_past_events)
    assert len(quotes) == 0


# -----------------------------------------------------------------------------
# 4. Validation against odds data type documentation snippet
# -----------------------------------------------------------------------------

def test_parse_sgo_docs_odds_data_type_example(doc_odds_snippet):
    """
    Validates handling of the odds data-type snippet from sportsgameodds.com/docs/data-types/odds.
    - Bare snippet without status.startsAt and teams is gracefully skipped (returns 0).
    - When wrapped in a valid Event container, extracts moneyline and totals quotes.
    """
    bare_payload = {"data": [doc_odds_snippet]}
    assert parse_sgo_events(bare_payload) == []

    # Wrap with event metadata
    wrapped_event = {
        "eventID": "doc_evt_odds_type",
        "status": {"startsAt": "2026-11-01T00:00:00Z"},
        "teams": {
            "home": {"names": {"long": "Boston Celtics", "short": "BOS"}},
            "away": {"names": {"long": "New York Knicks", "short": "NYK"}},
        },
        "odds": doc_odds_snippet.get("odds", {}),
    }
    quotes = parse_sgo_events({"data": [wrapped_event]})
    # 2 ML quotes (draftkings -112, fanduel -118) + 1 Total quote (draftkings -110, 224.5)
    assert len(quotes) == 3

    mls = [q for q in quotes if q.market_key == "h2h"]
    assert len(mls) == 2
    dk_ml = next(q for q in mls if q.bookmaker_key == "draftkings")
    assert dk_ml.price_american == -112
    fd_ml = next(q for q in mls if q.bookmaker_key == "fanduel")
    assert fd_ml.price_american == -118

    ous = [q for q in quotes if q.market_key == "totals"]
    assert len(ous) == 1
    dk_ou = ous[0]
    assert dk_ou.side == "over"
    assert dk_ou.line == 224.5
    assert dk_ou.price_american == -110


# -----------------------------------------------------------------------------
# 5. Validation against GET /account/usage documentation example
# -----------------------------------------------------------------------------

def test_fetch_account_usage_docs_example(doc_account_usage, tmp_path):
    """
    Validates fetch_account_usage against the official OpenAPI AccountUsageExample.
    Extracts remaining monthly objects from rateLimits.per-month (max-entities - current-entities).
    """
    cache_file = tmp_path / "usage.json"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=doc_account_usage)

    svc = SportsGameOddsService(
        api_key="sgo_valid_test_key",
        transport=httpx.MockTransport(handler),
        usage_cache_path=cache_file,
    )
    usage = svc.fetch_account_usage()
    assert usage is not None
    # 1,000,000 max - 914 current = 999,086 remaining
    assert svc.objects_remaining == 999086
    assert cache_file.exists()
    with open(cache_file, "r") as f:
        cached = json.load(f)
    assert cached["objects_remaining"] == 999086


# -----------------------------------------------------------------------------
# 6. Game matching helper validation with documentation example
# -----------------------------------------------------------------------------

def test_ingest_secondary_game_quotes_with_doc_fixture(db_session, doc_future_events):
    """
    Validates OddsIngestionService.ingest_secondary_game_quotes using the doc example.
    Sets up an existing Game matching Event 0 ('1. FC Union Berlin' vs 'RB Leipzig').
    Asserts:
    - 24 quotes from Event 0 match and are inserted into OddsHistory.
    - 42 quotes from Events 1 and 2 are unmatched, counted in skipped_unmatched, and skipped.
    - Crucial rule: total Game row count in database NEVER increases.
    """
    season = Season(
        season_label="2025-26",
        start_date=date(2025, 8, 1),
        end_date=date(2026, 6, 30),
        is_active=True,
    )
    db_session.add(season)
    fcu = Team(abbreviation="FCU", full_name="1. FC Union Berlin", city="Berlin", conference="East", division="Atlantic")
    rbl = Team(abbreviation="RBL", full_name="RB Leipzig", city="Leipzig", conference="East", division="Atlantic")
    db_session.add(fcu)
    db_session.add(rbl)
    db_session.commit()

    game = Game(
        provider_event_id="toa_test_doc_event_001",
        season_id=season.id,
        home_team_id=fcu.id,
        away_team_id=rbl.id,
        commence_time=datetime(2025, 12, 12, 19, 30, tzinfo=timezone.utc),
        status="scheduled",
    )
    db_session.add(game)
    db_session.commit()

    initial_games = len(db_session.exec(select(Game)).all())
    assert initial_games == 1

    quotes = parse_sgo_events(doc_future_events)
    assert len(quotes) == 66

    service = OddsIngestionService(db_session)
    captured_at = datetime(2025, 12, 12, 15, 0, tzinfo=timezone.utc)
    result = service.ingest_secondary_game_quotes(quotes, captured_at)

    assert result.inserted == 24
    assert result.skipped_unmatched == 42

    # Verify Game count remains unchanged
    final_games = len(db_session.exec(select(Game)).all())
    assert final_games == initial_games

    # Verify OddsHistory rows
    stored_quotes = db_session.exec(select(OddsHistory).where(OddsHistory.game_id == game.id)).all()
    assert len(stored_quotes) == 24

    # Verify Bovada spread was stored with correct line and price
    bovada_spread = next((q for q in stored_quotes if q.market == MarketType.spreads and q.side == BetSide.home), None)
    assert bovada_spread is not None
    assert float(bovada_spread.line) == 0.5
    assert bovada_spread.price_american == -122


# -----------------------------------------------------------------------------
# 7. Regression tests for specific fixes and edge cases
# -----------------------------------------------------------------------------

def test_regression_stat_id_filtering_skips_non_points_props():
    """Props with betTypeID in ('ou', 'ml') but statID != 'points' must be skipped."""
    payload = {
        "data": [
            {
                "eventID": "evt_stat_id_test",
                "status": {"startsAt": "2026-11-01T00:00:00Z"},
                "teams": {
                    "home": {"names": {"long": "Boston Celtics"}},
                    "away": {"names": {"long": "New York Knicks"}},
                },
                "odds": {
                    # Non-point prop with ou: corner kicks
                    "cornerKicks-all-game-ou-over": {
                        "oddID": "cornerKicks-all-game-ou-over",
                        "statID": "cornerKicks",
                        "periodID": "game",
                        "betTypeID": "ou",
                        "sideID": "over",
                        "byBookmaker": {"draftkings": {"odds": "-110", "overUnder": "9.5", "available": True}},
                    },
                    # Non-point prop with ml: last to score
                    "lastToScore-home-game-ml-home": {
                        "oddID": "lastToScore-home-game-ml-home",
                        "statID": "lastToScore",
                        "periodID": "game",
                        "betTypeID": "ml",
                        "sideID": "home",
                        "byBookmaker": {"draftkings": {"odds": "+120", "available": True}},
                    },
                    # Valid points total
                    "points-all-game-ou-over": {
                        "oddID": "points-all-game-ou-over",
                        "statID": "points",
                        "periodID": "game",
                        "betTypeID": "ou",
                        "sideID": "over",
                        "byBookmaker": {"draftkings": {"odds": "-110", "overUnder": "220.5", "available": True}},
                    },
                },
            }
        ]
    }
    quotes = parse_sgo_events(payload)
    assert len(quotes) == 1
    assert quotes[0].market_key == "totals"
    assert quotes[0].line == 220.5


def test_regression_period_id_filtering():
    """Accepts 'game' and 'reg'; rejects partial periods ('1h', '2h', '1q', '1s')."""
    payload = {
        "data": [
            {
                "eventID": "evt_period_test",
                "status": {"startsAt": "2026-11-01T00:00:00Z"},
                "teams": {
                    "home": {"names": {"long": "Boston Celtics"}},
                    "away": {"names": {"long": "New York Knicks"}},
                },
                "odds": {
                    "points-home-game-ml-home": {
                        "statID": "points",
                        "periodID": "game",
                        "betTypeID": "ml",
                        "sideID": "home",
                        "byBookmaker": {"draftkings": {"odds": "-150", "available": True}},
                    },
                    "points-home-reg-ml-home": {
                        "statID": "points",
                        "periodID": "reg",
                        "betTypeID": "ml",
                        "sideID": "home",
                        "byBookmaker": {"draftkings": {"odds": "-140", "available": True}},
                    },
                    "points-home-1h-ml-home": {
                        "statID": "points",
                        "periodID": "1h",
                        "betTypeID": "ml",
                        "sideID": "home",
                        "byBookmaker": {"draftkings": {"odds": "-130", "available": True}},
                    },
                    "points-home-1q-ml-home": {
                        "statID": "points",
                        "periodID": "1q",
                        "betTypeID": "ml",
                        "sideID": "home",
                        "byBookmaker": {"draftkings": {"odds": "-120", "available": True}},
                    },
                },
            }
        ]
    }
    quotes = parse_sgo_events(payload)
    assert len(quotes) == 2
    prices = {q.price_american for q in quotes}
    assert prices == {-150, -140}


def test_regression_odd_id_string_fallback():
    """Parses statID, periodID, and betTypeID from oddID when fields are omitted from odd_obj."""
    payload = {
        "data": [
            {
                "eventID": "evt_fallback_test",
                "status": {"startsAt": "2026-11-01T00:00:00Z"},
                "teams": {
                    "home": {"names": {"long": "Boston Celtics"}},
                    "away": {"names": {"long": "New York Knicks"}},
                },
                "odds": {
                    # No statID, periodID, betTypeID, sideID in dictionary
                    "points-home-game-ml-home": {
                        "byBookmaker": {"draftkings": {"odds": "-155", "available": True}},
                    },
                },
            }
        ]
    }
    quotes = parse_sgo_events(payload)
    assert len(quotes) == 1
    assert quotes[0].market_key == "h2h"
    assert quotes[0].side == "home"
    assert quotes[0].price_american == -155


def test_regression_american_odds_extended_formats():
    """Tests parse_american_odds with various formats including '+', floats, and bounds."""
    assert parse_american_odds("+105") == 105
    assert parse_american_odds("105") == 105
    assert parse_american_odds(105) == 105
    assert parse_american_odds("-110") == -110
    assert parse_american_odds("+100") == 100
    assert parse_american_odds("-100") == -100
    assert parse_american_odds("105.0") == 105
    assert parse_american_odds("+100000") == 100000
    assert parse_american_odds("-100000") == -100000

    # Values between -100 and +100 are invalid American odds
    assert parse_american_odds(0) is None
    assert parse_american_odds("0") is None
    assert parse_american_odds(99) is None
    assert parse_american_odds(-99) is None
    assert parse_american_odds("") is None
    assert parse_american_odds("abc") is None
    assert parse_american_odds(None) is None


def test_regression_float_line_extended_formats():
    """Tests parse_float_line with spread signs, zeros, and bounds."""
    assert parse_float_line("+4.5") == 4.5
    assert parse_float_line("-4.5") == -4.5
    assert parse_float_line("+0") == 0.0
    assert parse_float_line("-0") == 0.0
    assert parse_float_line("224.5") == 224.5
    assert parse_float_line(224.5) == 224.5
    assert parse_float_line("") is None
    assert parse_float_line("invalid") is None
    assert parse_float_line(None) is None


def test_regression_available_variants():
    """Tests that available accepts True and 'true', while skipping False, 'false', and None."""
    payload = {
        "data": [
            {
                "eventID": "evt_avail_test",
                "status": {"startsAt": "2026-11-01T00:00:00Z"},
                "teams": {
                    "home": {"names": {"long": "Boston Celtics"}},
                    "away": {"names": {"long": "New York Knicks"}},
                },
                "odds": {
                    "points-home-game-ml-home": {
                        "statID": "points",
                        "periodID": "game",
                        "betTypeID": "ml",
                        "sideID": "home",
                        "byBookmaker": {
                            "dk": {"odds": "-110", "available": True},
                            "fd": {"odds": "-115", "available": "true"},
                            "mgm": {"odds": "-120", "available": False},
                            "czr": {"odds": "-125", "available": "false"},
                            "wh": {"odds": "-130"},  # missing available
                        },
                    },
                },
            }
        ]
    }
    quotes = parse_sgo_events(payload)
    assert len(quotes) == 2
    bms = {q.bookmaker_key for q in quotes}
    assert bms == {"dk", "fd"}
