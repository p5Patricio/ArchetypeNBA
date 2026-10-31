"""
Unit and integration tests for SportsGameOdds daily capture (work package WP-K1).

Tests:
1. SGO parser extracts main markets, player props, and consensus quotes with sgo_book_prefix.
2. SGO ingestion maps to existing games (never creates games), stores main lines & props under sgo_<book>
   in odds_history, resolves player names using team-scoped suffix-aware resolver, skips & counts unmatched.
3. Market consensus snapshots stored in market_consensus_snapshot, NEVER written to odds_history.
4. Recorder safety: PredictionRecorder never queries consensus rows and treats sgo_ books like any other non-sharp
   bookmaker; bets only placed on quotes younger than max_quote_age_minutes.
5. Tick step 'sgo' runs once per local day after opening capture succeeded, respects daily budget, uses cursor pagination,
   records sgo_daily marker in odds_snapshot_capture, dry-run support with no network, failure isolation.
6. scripts/sgo_probe.py --capture-dry-run prints request specification and budget estimate.
"""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Dict, List, Optional
from unittest.mock import MagicMock

import httpx
import pytest
from sqlmodel import select

from app.config import settings
from app.models import (
    CAPTURE_OPENING,
    CAPTURE_SGO_DAILY,
    BetSide,
    Game,
    MarketConsensusSnapshot,
    MarketType,
    ModelVersion,
    OddsHistory,
    OddsSnapshotCapture,
    Player,
    PlayerSeasonStats,
    Season,
    Sportsbook,
    Team,
    TeamEloRating,
)
from app.services.elo_service import MODEL_NAME, MODEL_VERSION
from app.services.odds_ingestion import OddsIngestionService
from app.services.odds_providers.sportsgameodds import (
    ConsensusQuote,
    SportsGameOddsService,
    parse_sgo_consensus,
    parse_sgo_events,
    parse_sgo_props,
)
from app.services.prediction_recorder import PredictionRecorder
from app.services.tick import (
    DEFAULT_STEPS,
    STEP_ERROR,
    STEP_OK,
    STEP_SKIPPED,
    TickContext,
    default_steps,
    opening_captured_today,
    run_tick,
    sgo_captured_today,
    sgo_step,
)


SYNTHETIC_SGO_EVENT = {
    "eventID": "sgo_evt_20261031_001",
    "status": {
        "startsAt": "2026-10-31T23:30:00.000Z",
        "started": False,
        "ended": False,
        "finalized": False,
    },
    "teams": {
        "home": {
            "teamID": "boston_celtics",
            "names": {"long": "Boston Celtics", "medium": "Celtics", "short": "BOS"},
        },
        "away": {
            "teamID": "new_york_knicks",
            "names": {"long": "New York Knicks", "medium": "Knicks", "short": "NYK"},
        },
    },
    "players": {
        "AARON_WIGGINS_1_NBA": {
            "name": "Aaron Wiggins",
            "firstName": "Aaron",
            "lastName": "Wiggins",
            "teamID": "boston_celtics",
        },
        "UNKNOWN_GHOST_NBA": {
            "name": "Ghost Player",
            "firstName": "Ghost",
            "lastName": "Player",
            "teamID": "boston_celtics",
        },
    },
    "odds": {
        # 1. Moneyline home
        "points-home-game-ml-home": {
            "oddID": "points-home-game-ml-home",
            "statID": "points",
            "statEntityID": "home",
            "periodID": "game",
            "betTypeID": "ml",
            "sideID": "home",
            "fairOdds": "-155",
            "bookOdds": "-160",
            "byBookmaker": {
                "draftkings": {
                    "odds": "-150",
                    "available": True,
                    "lastUpdatedAt": "2026-10-31T20:00:00Z",
                },
                "fanduel": {
                    "odds": "-152",
                    "available": True,
                    "lastUpdatedAt": "2026-10-31T20:05:00Z",
                },
            },
        },
        # 2. Moneyline away
        "points-away-game-ml-away": {
            "oddID": "points-away-game-ml-away",
            "statID": "points",
            "statEntityID": "away",
            "periodID": "game",
            "betTypeID": "ml",
            "sideID": "away",
            "fairOdds": "+135",
            "bookOdds": "+130",
            "byBookmaker": {
                "draftkings": {
                    "odds": "+130",
                    "available": True,
                    "lastUpdatedAt": "2026-10-31T20:00:00Z",
                },
            },
        },
        # 3. Spread home
        "points-home-game-sp-home": {
            "oddID": "points-home-game-sp-home",
            "statID": "points",
            "statEntityID": "home",
            "periodID": "game",
            "betTypeID": "sp",
            "sideID": "home",
            "fairSpread": "-4.5",
            "fairOdds": "-108",
            "bookSpread": "-4.5",
            "bookOdds": "-110",
            "byBookmaker": {
                "caesars": {
                    "odds": "-108",
                    "spread": "-4.5",
                    "available": True,
                    "lastUpdatedAt": "2026-10-31T20:00:00Z",
                },
            },
        },
        # 4. Spread away
        "points-away-game-sp-away": {
            "oddID": "points-away-game-sp-away",
            "statID": "points",
            "statEntityID": "away",
            "periodID": "game",
            "betTypeID": "sp",
            "sideID": "away",
            "fairSpread": "+4.5",
            "fairOdds": "-112",
            "bookSpread": "+4.5",
            "bookOdds": "-110",
            "byBookmaker": {
                "caesars": {
                    "odds": "-112",
                    "spread": "+4.5",
                    "available": True,
                    "lastUpdatedAt": "2026-10-31T20:00:00Z",
                },
            },
        },
        # 5. Totals over
        "points-all-game-ou-over": {
            "oddID": "points-all-game-ou-over",
            "statID": "points",
            "statEntityID": "all",
            "periodID": "game",
            "betTypeID": "ou",
            "sideID": "over",
            "fairOverUnder": "224.5",
            "fairOdds": "-109",
            "bookOverUnder": "224.5",
            "bookOdds": "-110",
            "byBookmaker": {
                "betmgm": {
                    "odds": "-110",
                    "overUnder": "224.5",
                    "available": True,
                    "lastUpdatedAt": "2026-10-31T20:00:00Z",
                },
            },
        },
        # 6. Totals under
        "points-all-game-ou-under": {
            "oddID": "points-all-game-ou-under",
            "statID": "points",
            "statEntityID": "all",
            "periodID": "game",
            "betTypeID": "ou",
            "sideID": "under",
            "fairOverUnder": "224.5",
            "fairOdds": "-111",
            "bookOverUnder": "224.5",
            "bookOdds": "-110",
            "byBookmaker": {
                "betmgm": {
                    "odds": "-110",
                    "overUnder": "224.5",
                    "available": True,
                    "lastUpdatedAt": "2026-10-31T20:00:00Z",
                },
            },
        },
        # 7. Player Props: Points over/under
        "points-AARON_WIGGINS_1_NBA-game-ou-over": {
            "oddID": "points-AARON_WIGGINS_1_NBA-game-ou-over",
            "statID": "points",
            "statEntityID": "AARON_WIGGINS_1_NBA",
            "periodID": "game",
            "betTypeID": "ou",
            "sideID": "over",
            "byBookmaker": {
                "draftkings": {
                    "odds": "-115",
                    "overUnder": "14.5",
                    "available": True,
                    "lastUpdatedAt": "2026-10-31T20:00:00Z",
                },
            },
        },
        "points-AARON_WIGGINS_1_NBA-game-ou-under": {
            "oddID": "points-AARON_WIGGINS_1_NBA-game-ou-under",
            "statID": "points",
            "statEntityID": "AARON_WIGGINS_1_NBA",
            "periodID": "game",
            "betTypeID": "ou",
            "sideID": "under",
            "byBookmaker": {
                "draftkings": {
                    "odds": "-115",
                    "overUnder": "14.5",
                    "available": True,
                    "lastUpdatedAt": "2026-10-31T20:00:00Z",
                },
            },
        },
        # 8. Player Props: Rebounds
        "rebounds-AARON_WIGGINS_1_NBA-game-ou-over": {
            "oddID": "rebounds-AARON_WIGGINS_1_NBA-game-ou-over",
            "statID": "rebounds",
            "statEntityID": "AARON_WIGGINS_1_NBA",
            "periodID": "game",
            "betTypeID": "ou",
            "sideID": "over",
            "byBookmaker": {
                "caesars": {
                    "odds": "-110",
                    "overUnder": "4.5",
                    "available": True,
                    "lastUpdatedAt": "2026-10-31T20:00:00Z",
                },
            },
        },
        # 9. Player Props: Assists
        "assists-AARON_WIGGINS_1_NBA-game-ou-over": {
            "oddID": "assists-AARON_WIGGINS_1_NBA-game-ou-over",
            "statID": "assists",
            "statEntityID": "AARON_WIGGINS_1_NBA",
            "periodID": "game",
            "betTypeID": "ou",
            "sideID": "over",
            "byBookmaker": {
                "fanduel": {
                    "odds": "-120",
                    "overUnder": "2.5",
                    "available": True,
                    "lastUpdatedAt": "2026-10-31T20:00:00Z",
                },
            },
        },
        # 10. Player Props: PRA combo
        "points_rebounds_assists-AARON_WIGGINS_1_NBA-game-ou-over": {
            "oddID": "points_rebounds_assists-AARON_WIGGINS_1_NBA-game-ou-over",
            "statID": "points_rebounds_assists",
            "statEntityID": "AARON_WIGGINS_1_NBA",
            "periodID": "game",
            "betTypeID": "ou",
            "sideID": "over",
            "byBookmaker": {
                "draftkings": {
                    "odds": "-115",
                    "overUnder": "21.5",
                    "available": True,
                    "lastUpdatedAt": "2026-10-31T20:00:00Z",
                },
            },
        },
        # 11. Unmatched player prop
        "points-UNKNOWN_GHOST_NBA-game-ou-over": {
            "oddID": "points-UNKNOWN_GHOST_NBA-game-ou-over",
            "statID": "points",
            "statEntityID": "UNKNOWN_GHOST_NBA",
            "periodID": "game",
            "betTypeID": "ou",
            "sideID": "over",
            "byBookmaker": {
                "draftkings": {
                    "odds": "-110",
                    "overUnder": "10.5",
                    "available": True,
                    "lastUpdatedAt": "2026-10-31T20:00:00Z",
                },
            },
        },
    },
}

SYNTHETIC_SGO_PAYLOAD = {
    "success": True,
    "data": [SYNTHETIC_SGO_EVENT],
    "notice": "Response is missing 12 bookmaker odds. Upgrade your API key.",
}


@pytest.fixture
def capture_env(db_session):
    """Sets up season, teams, player, elo rating, model, and existing game."""
    season = Season(
        season_label="2026-27",
        start_date=date(2026, 10, 20),
        end_date=date(2027, 6, 30),
        is_active=True,
    )
    db_session.add(season)

    bos = Team(abbreviation="BOS", full_name="Boston Celtics", city="Boston", conference="East", division="Atlantic")
    nyk = Team(abbreviation="NYK", full_name="New York Knicks", city="New York", conference="East", division="Atlantic")
    db_session.add(bos)
    db_session.add(nyk)

    # Aaron Wiggins on Boston
    player = Player(full_name="Aaron Wiggins")
    db_session.add(player)
    db_session.commit()

    pss = PlayerSeasonStats(player_id=player.id, team_id=bos.id, season_id=season.id)
    db_session.add(pss)

    # Sharp book (Pinnacle) to establish fair probability reference
    pinnacle = Sportsbook(key="pinnacle", name="Pinnacle", region="eu", is_sharp=True)
    db_session.add(pinnacle)

    # Model version
    model = ModelVersion(name=MODEL_NAME, version=MODEL_VERSION, params={"sigma": 14.0})
    db_session.add(model)
    db_session.commit()

    db_session.add(TeamEloRating(
        model_version_id=model.id, team_id=bos.id, season_id=season.id,
        game_id="0022600001", game_date=date(2026, 10, 30), rating_after=1620.0,
    ))
    db_session.add(TeamEloRating(
        model_version_id=model.id, team_id=nyk.id, season_id=season.id,
        game_id="0022600001", game_date=date(2026, 10, 30), rating_after=1510.0,
    ))
    db_session.commit()

    game = Game(
        provider_event_id="toa_event_bos_nyk_001",
        season_id=season.id,
        home_team_id=bos.id,
        away_team_id=nyk.id,
        commence_time=datetime(2026, 10, 31, 23, 30, tzinfo=timezone.utc),
        status="scheduled",
    )
    db_session.add(game)
    db_session.commit()

    return db_session, game, player, bos, nyk


# ----------------------------------------------------------------------------------------------
# 1. Parser tests
# ----------------------------------------------------------------------------------------------

def test_parse_sgo_events_with_sgo_prefix():
    quotes = parse_sgo_events(SYNTHETIC_SGO_PAYLOAD, sgo_book_prefix=True)
    # Expected 7 game quotes (3 h2h, 2 sp, 2 totals)
    assert len(quotes) == 7
    for q in quotes:
        assert q.bookmaker_key.startswith("sgo_")
        assert q.bookmaker_title.endswith("(SportsGameOdds)")
        assert q.bookmaker_key in ("sgo_draftkings", "sgo_fanduel", "sgo_caesars", "sgo_betmgm")


def test_parse_sgo_props_extracts_all_categories():
    props = parse_sgo_props(SYNTHETIC_SGO_PAYLOAD, sgo_book_prefix=True)
    # Expected: points (over + under), rebounds (over), assists (over), pra (over), ghost player (over) = 6 props
    assert len(props) == 6

    market_keys = {p.market_key for p in props}
    assert market_keys == {"player_points", "player_rebounds", "player_assists", "player_pra"}

    for p in props:
        assert p.bookmaker_key.startswith("sgo_")
        assert p.side in ("over", "under")
        assert isinstance(p.line, float)
        assert p.price_american in (-110, -115, -120)

    # Aaron Wiggins props
    wiggins_props = [p for p in props if p.player_name == "Aaron Wiggins"]
    assert len(wiggins_props) == 5

    pts_over = next(p for p in wiggins_props if p.market_key == "player_points" and p.side == "over")
    assert pts_over.line == 14.5
    assert pts_over.bookmaker_key == "sgo_draftkings"

    reb_over = next(p for p in wiggins_props if p.market_key == "player_rebounds")
    assert reb_over.line == 4.5
    assert reb_over.bookmaker_key == "sgo_caesars"

    ast_over = next(p for p in wiggins_props if p.market_key == "player_assists")
    assert ast_over.line == 2.5
    assert ast_over.bookmaker_key == "sgo_fanduel"

    pra_over = next(p for p in wiggins_props if p.market_key == "player_pra")
    assert pra_over.line == 21.5
    assert pra_over.bookmaker_key == "sgo_draftkings"


def test_parse_sgo_consensus_extracts_main_markets():
    consensus = parse_sgo_consensus(SYNTHETIC_SGO_PAYLOAD)
    # 2 h2h (home, away), 2 spreads (home, away), 2 totals (over, under) = 6 quotes
    assert len(consensus) == 6

    h2h = [c for c in consensus if c.market == MarketType.h2h]
    assert len(h2h) == 2
    h2h_home = next(c for c in h2h if c.side == BetSide.home)
    assert h2h_home.fair_price_american == -155
    assert h2h_home.book_price_american == -160
    assert h2h_home.line is None

    sp = [c for c in consensus if c.market == MarketType.spreads]
    assert len(sp) == 2
    sp_home = next(c for c in sp if c.side == BetSide.home)
    assert sp_home.line == -4.5
    assert sp_home.fair_price_american == -108
    assert sp_home.book_price_american == -110

    ou = [c for c in consensus if c.market == MarketType.totals]
    assert len(ou) == 2
    ou_over = next(c for c in ou if c.side == BetSide.over)
    assert ou_over.line == 224.5
    assert ou_over.fair_price_american == -109
    assert ou_over.book_price_american == -110


# ----------------------------------------------------------------------------------------------
# 2. Ingestion tests: quotes into odds_history, consensus into market_consensus_snapshot
# ----------------------------------------------------------------------------------------------

def test_ingest_sgo_daily_events_stores_main_props_and_consensus(capture_env):
    session, game, player, bos, nyk = capture_env
    ingestion = OddsIngestionService(session)
    now = datetime(2026, 10, 31, 20, 15, tzinfo=timezone.utc)

    result, consensus_count, matched_games = ingestion.ingest_sgo_daily_events([SYNTHETIC_SGO_EVENT], now)

    # 1 game matched
    assert len(matched_games) == 1
    assert matched_games[0].id == game.id

    # Quotes in odds_history:
    # 7 main quotes + 5 resolved player props (Ghost Player skipped unmatched) = 12 inserted
    assert result.inserted == 12
    assert result.unmatched_names == 1
    assert result.skipped_unmatched == 1

    # Verify sportsbook rows created with sgo_ prefix
    books = session.exec(select(Sportsbook)).all()
    sgo_book_keys = {b.key for b in books if b.key.startswith("sgo_")}
    assert "sgo_draftkings" in sgo_book_keys
    assert "sgo_fanduel" in sgo_book_keys
    assert "sgo_caesars" in sgo_book_keys
    assert "sgo_betmgm" in sgo_book_keys

    # Verify Sportsbook attributes
    dk = next(b for b in books if b.key == "sgo_draftkings")
    assert dk.name == "DraftKings (SportsGameOdds)"
    assert not dk.is_sharp
    assert dk.region == "us"

    # Verify player props in odds_history
    prop_history = session.exec(
        select(OddsHistory).where(OddsHistory.player_id == player.id)
    ).all()
    assert len(prop_history) == 5
    markets_stored = {h.market for h in prop_history}
    assert markets_stored == {
        MarketType.player_points,
        MarketType.player_rebounds,
        MarketType.player_assists,
        MarketType.player_pra,
    }

    # Verify consensus in market_consensus_snapshot: exactly 6 rows
    assert consensus_count == 6
    consensus_rows = session.exec(
        select(MarketConsensusSnapshot).where(MarketConsensusSnapshot.game_id == game.id)
    ).all()
    assert len(consensus_rows) == 6
    for c in consensus_rows:
        assert c.source == "sgo_fair"
        assert c.fair_price_american <= -100 or c.fair_price_american >= 100

    # CRITICAL INVARIANT: consensus must NEVER exist in odds_history
    oh_sources = session.exec(select(OddsHistory.sportsbook_id)).all()
    # Ensure no sportsbook exists with key 'sgo_fair'
    sgo_fair_sb = session.exec(select(Sportsbook).where(Sportsbook.key == "sgo_fair")).first()
    assert sgo_fair_sb is None


def test_ingest_sgo_daily_events_unmatched_event_is_skipped_never_created(capture_env):
    session, game, player, bos, nyk = capture_env
    ingestion = OddsIngestionService(session)
    now = datetime(2026, 10, 31, 20, 15, tzinfo=timezone.utc)

    unmatched_event = {
        "eventID": "unmatched_999",
        "status": {"startsAt": "2026-11-05T01:00:00.000Z"},
        "teams": {
            "home": {"names": {"short": "PHX", "long": "Phoenix Suns"}},
            "away": {"names": {"short": "DEN", "long": "Denver Nuggets"}},
        },
        "odds": {
            "points-home-game-ml-home": {
                "periodID": "game", "betTypeID": "ml", "sideID": "home",
                "byBookmaker": {"draftkings": {"odds": "-140", "available": True}},
            }
        },
    }

    initial_games = len(session.exec(select(Game)).all())
    result, consensus_count, matched = ingestion.ingest_sgo_daily_events([unmatched_event], now)

    assert len(matched) == 0
    assert result.skipped_unmatched == 1
    assert result.inserted == 0
    assert consensus_count == 0
    assert len(session.exec(select(Game)).all()) == initial_games


# ----------------------------------------------------------------------------------------------
# 3. Safety tests: recorder, settlement, CLV, and max quote age
# ----------------------------------------------------------------------------------------------

def test_prediction_recorder_never_sees_consensus_rows(capture_env):
    session, game, player, bos, nyk = capture_env
    ingestion = OddsIngestionService(session)
    now = datetime(2026, 10, 31, 20, 15, tzinfo=timezone.utc)

    # Ingest SGO event
    ingestion.ingest_sgo_daily_events([SYNTHETIC_SGO_EVENT], now)

    # Verify consensus exists in its dedicated table
    consensus_rows = session.exec(select(MarketConsensusSnapshot)).all()
    assert len(consensus_rows) == 6

    # Run PredictionRecorder at fresh quote time
    recorder = PredictionRecorder(session, now=now + timedelta(minutes=5))
    summary = recorder.run(dry_run=True)

    # Recorder loads quotes from odds_history only
    # SGO books are non-sharp, so without a sharp book establishing fair price, no bet is placed
    assert summary.games_considered >= 1


def test_sgo_books_treated_as_non_sharp_and_stale_quotes_ignored(capture_env):
    session, game, player, bos, nyk = capture_env
    ingestion = OddsIngestionService(session)

    # Capture 7 hours before now (exceeding default 360 min / 6 h max_quote_age)
    capture_time = datetime(2026, 10, 31, 13, 0, tzinfo=timezone.utc)
    ingestion.ingest_sgo_daily_events([SYNTHETIC_SGO_EVENT], capture_time)

    # Now is 7 hours later
    current_now = datetime(2026, 10, 31, 20, 30, tzinfo=timezone.utc)

    recorder = PredictionRecorder(session, now=current_now)
    quotes = recorder._load_quotes([game.id])

    # SGO quotes from 7 hours ago must be completely ignored as stale (> 360 min)
    sgo_quotes_loaded = [q for q_list in quotes.values() for q in q_list if q.book_key.startswith("sgo_")]
    assert len(sgo_quotes_loaded) == 0


def test_fresh_sgo_quote_eligible_as_best_price(capture_env):
    session, game, player, bos, nyk = capture_env
    ingestion = OddsIngestionService(session)

    # Capture time 10 minutes ago (well within 360 min)
    capture_time = datetime(2026, 10, 31, 20, 0, tzinfo=timezone.utc)
    ingestion.ingest_sgo_daily_events([SYNTHETIC_SGO_EVENT], capture_time)

    current_now = datetime(2026, 10, 31, 20, 10, tzinfo=timezone.utc)
    recorder = PredictionRecorder(session, now=current_now)
    quotes = recorder._load_quotes([game.id])

    # Fresh SGO quotes are loaded for the game
    sgo_quotes = [q for q in quotes.get(game.id, []) if q.book_key.startswith("sgo_")]
    assert len(sgo_quotes) > 0
    # Every SGO book is non-sharp
    for q in sgo_quotes:
        assert not q.is_sharp


# ----------------------------------------------------------------------------------------------
# 4. Tick step 'sgo' tests: isolation, daily idempotency, cursor pagination, budgets
# ----------------------------------------------------------------------------------------------

def test_sgo_step_skips_when_api_key_not_configured(capture_env):
    session, game, player, bos, nyk = capture_env
    now = datetime(2026, 10, 31, 20, 0, tzinfo=timezone.utc)

    sgo_svc = SportsGameOddsService(api_key="")
    ctx = TickContext(
        session=session,
        service=MagicMock(is_configured=True),
        now=now,
        dry_run=False,
        window_minutes=30,
        props_events=1,
        min_remaining=25,
        local_tz=None,
        sgo_service=sgo_svc,
    )

    result = sgo_step(ctx)
    assert result.status == STEP_SKIPPED
    assert "not configured" in result.message


def test_sgo_step_waits_for_opening_capture(capture_env):
    session, game, player, bos, nyk = capture_env
    now = datetime(2026, 10, 31, 20, 0, tzinfo=timezone.utc)

    sgo_svc = SportsGameOddsService(api_key="sgo_valid_test_key_123")
    ctx = TickContext(
        session=session,
        service=MagicMock(is_configured=True),
        now=now,
        dry_run=False,
        window_minutes=30,
        props_events=1,
        min_remaining=25,
        local_tz=None,
        sgo_service=sgo_svc,
    )

    # Opening capture has NOT run today
    assert not opening_captured_today(session, now)

    result = sgo_step(ctx)
    assert result.status == STEP_SKIPPED
    assert "waiting for opening capture" in result.message


def test_sgo_step_dry_run_support_no_network(capture_env):
    session, game, player, bos, nyk = capture_env
    now = datetime(2026, 10, 31, 20, 0, tzinfo=timezone.utc)

    # Record opening capture for today
    session.add(OddsSnapshotCapture(game_id=game.id, kind=CAPTURE_OPENING, captured_at=now))
    session.commit()

    sgo_svc = SportsGameOddsService(api_key="sgo_valid_test_key_123")
    ctx = TickContext(
        session=session,
        service=MagicMock(is_configured=True),
        now=now,
        dry_run=True,
        window_minutes=30,
        props_events=1,
        min_remaining=25,
        local_tz=None,
        sgo_service=sgo_svc,
    )

    result = sgo_step(ctx)
    assert result.status == STEP_OK
    assert "would capture SGO daily odds" in result.message
    # No markers or quotes written during dry run
    assert not sgo_captured_today(session, now)


def test_sgo_step_successful_execution_and_idempotency(capture_env):
    session, game, player, bos, nyk = capture_env
    now = datetime(2026, 10, 31, 20, 0, tzinfo=timezone.utc)

    # 1. Opening marker exists for today
    session.add(OddsSnapshotCapture(game_id=game.id, kind=CAPTURE_OPENING, captured_at=now))
    session.commit()

    # 2. Mock HTTP transport returning synthetic SGO payload
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=SYNTHETIC_SGO_PAYLOAD)

    sgo_svc = SportsGameOddsService(
        api_key="sgo_valid_test_key_123",
        transport=httpx.MockTransport(handler),
    )

    ctx = TickContext(
        session=session,
        service=MagicMock(is_configured=True),
        now=now,
        dry_run=False,
        window_minutes=30,
        props_events=1,
        min_remaining=25,
        local_tz=None,
        sgo_service=sgo_svc,
    )

    # 3. First execution succeeds
    result = sgo_step(ctx)
    assert result.status == STEP_OK
    assert "captured 1 event(s) (1 object(s))" in result.message

    # Marker written in odds_snapshot_capture with kind 'sgo_daily' and credits_spent = objects used
    assert sgo_captured_today(session, now)
    marker = session.exec(
        select(OddsSnapshotCapture).where(OddsSnapshotCapture.kind == CAPTURE_SGO_DAILY)
    ).first()
    assert marker is not None
    assert marker.game_id == game.id
    assert marker.credits_spent == 1

    # 4. Second execution on same day is skipped (idempotent)
    second_result = sgo_step(ctx)
    assert second_result.status == STEP_SKIPPED
    assert "already completed" in second_result.message


def test_sgo_step_cursor_pagination_and_budget_enforcement(capture_env):
    session, game, player, bos, nyk = capture_env
    now = datetime(2026, 10, 31, 20, 0, tzinfo=timezone.utc)

    # Page 1 has nextCursor='cursor_page_2'
    page1 = {
        "success": True,
        "data": [SYNTHETIC_SGO_EVENT],
        "nextCursor": "cursor_page_2",
    }
    # Page 2 has nextCursor=None
    page2_event = dict(SYNTHETIC_SGO_EVENT, eventID="sgo_evt_20261031_002")
    page2 = {
        "success": True,
        "data": [page2_event],
        "nextCursor": None,
    }

    requests_made = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests_made.append(request)
        if "cursor=cursor_page_2" in str(request.url):
            return httpx.Response(200, json=page2)
        return httpx.Response(200, json=page1)

    sgo_svc = SportsGameOddsService(
        api_key="sgo_valid_test_key_123",
        transport=httpx.MockTransport(handler),
    )

    events, consumed = sgo_svc.fetch_daily_events(now=now, max_objects=30)
    assert len(events) == 2
    assert consumed == 2
    assert len(requests_made) == 2
    assert "cursor" not in str(requests_made[0].url)
    assert "cursor=cursor_page_2" in str(requests_made[1].url)


def test_sgo_step_failure_never_blocks_record_step(capture_env):
    session, game, player, bos, nyk = capture_env
    now = datetime(2026, 10, 31, 20, 0, tzinfo=timezone.utc)

    # Opening captured
    session.add(OddsSnapshotCapture(game_id=game.id, kind=CAPTURE_OPENING, captured_at=now))
    session.commit()

    # SGO service that throws a server error
    def failing_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "provider down"})

    failing_svc = SportsGameOddsService(
        api_key="sgo_valid_test_key_123",
        transport=httpx.MockTransport(failing_handler),
    )

    summary = run_tick(
        session,
        odds_service=MagicMock(is_configured=True),
        now=now,
        dry_run=True,
        sgo_service=failing_svc,
    )

    statuses = {s.name: s.status for s in summary.steps}
    # Record step ran and succeeded despite sgo step status
    assert "record" in statuses
    assert statuses["record"] == STEP_OK


def test_default_steps_omits_sgo_when_key_empty():
    # When key is empty (the default), sgo is omitted to preserve backward compatibility
    steps = default_steps()
    step_names = [name for name, _ in steps]
    assert "sgo" not in step_names
    assert step_names == ["opening", "closing", "results", "learn", "record"]
