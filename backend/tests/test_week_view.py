"""
Tests for Week View service and API (GET /api/v1/week).

Covers:
- Empty database -> 200 with empty list
- Success with odds, predictions, line shopping and injuries
- No odds case
- No injuries case
- Stale injuries case (> 36 h)
- Policy flag matches evaluate_candidate / recorder on a hand-computed case
- Pure read-only guarantee: nothing is written to DB
- Days window filtering (e.g. days=7 vs days=14)
- Challenger predictions inclusion
"""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, func, select

from app.analytics import betting_policy as policy
from app.analytics import elo
from app.analytics.props_engine import devig_two_way
from app.models import (
    BetSide,
    Game,
    InjuryEntry,
    InjuryReportSnapshot,
    MarketType,
    ModelPrediction,
    ModelVersion,
    OddsHistory,
    Season,
    SimulatedBet,
    Sportsbook,
    Team,
    TeamEloRating,
    MODEL_ROLE_CHAMPION,
    MODEL_ROLE_CHALLENGER,
)
from app.services.elo_service import MODEL_NAME, MODEL_VERSION
from app.services.week_view import MEXICO_CITY_TZ, build_week_view

NOW = datetime(2026, 10, 20, 18, 0, tzinfo=timezone.utc)
SIGMA = 14.0
RATINGS = {"AAA": 1600.0, "BBB": 1500.0, "CCC": 1550.0, "DDD": 1450.0}


class SyntheticWorld:
    """Helper world for week view tests with SQLite session."""

    def __init__(self, session: Session):
        self.session = session
        self.old_season = Season(season_label="2025-26", is_active=True)
        self.new_season = Season(season_label="2026-27")
        session.add_all([self.old_season, self.new_season])

        self.teams: dict[str, Team] = {}
        for abbr in RATINGS:
            t = Team(
                abbreviation=abbr,
                full_name=f"{abbr} Basketball Team",
                city=abbr,
                conference="East",
                division="Atlantic",
            )
            session.add(t)
            self.teams[abbr] = t

        self.books: dict[str, Sportsbook] = {
            "pinnacle": Sportsbook(key="pinnacle", name="Pinnacle", region="eu", is_sharp=True),
            "draftkings": Sportsbook(key="draftkings", name="DraftKings", region="us", is_sharp=False),
            "fanduel": Sportsbook(key="fanduel", name="FanDuel", region="us", is_sharp=False),
        }
        session.add_all(self.books.values())

        # Champion model
        self.champion = ModelVersion(
            name=MODEL_NAME,
            version=MODEL_VERSION,
            params={"sigma": SIGMA},
            role=MODEL_ROLE_CHAMPION,
            promoted_at=NOW - timedelta(days=30),
        )
        session.add(self.champion)
        session.commit()

        # Seed ratings
        for i, (abbr, rating) in enumerate(RATINGS.items()):
            session.add(
                TeamEloRating(
                    model_version_id=self.champion.id,
                    team_id=self.teams[abbr].id,
                    season_id=self.old_season.id,
                    game_id=f"00225{i:05d}",
                    game_date=date(2026, 4, 10),
                    rating_after=rating,
                )
            )
        session.commit()

    def make_game(
        self,
        home: str = "AAA",
        away: str = "BBB",
        days_ahead: float = 1.0,
        status: str = "scheduled",
    ) -> Game:
        game = Game(
            provider_event_id=f"evt-{home}-{away}-{days_ahead}",
            season_id=self.new_season.id,
            home_team_id=self.teams[home].id,
            away_team_id=self.teams[away].id,
            commence_time=NOW + timedelta(days=days_ahead),
            status=status,
        )
        self.session.add(game)
        self.session.commit()
        return game

    def add_quote(
        self,
        game: Game,
        book: str,
        side: str,
        price_american: int,
        hours_old: float = 1.0,
    ) -> OddsHistory:
        captured = NOW - timedelta(hours=hours_old)
        row = OddsHistory(
            game_id=game.id,
            sportsbook_id=self.books[book].id,
            market=MarketType.h2h,
            side=side,
            price_american=price_american,
            captured_at=captured,
            book_last_update=captured - timedelta(minutes=5),
        )
        self.session.add(row)
        self.session.commit()
        return row

    def add_snapshot(
        self, hours_old: float = 2.0, entries: list[dict] = None
    ) -> InjuryReportSnapshot:
        snap_time = NOW - timedelta(hours=hours_old)
        snap = InjuryReportSnapshot(
            source="nba_official_pdf",
            report_url="https://ak-static.cms.nba.com/referee/injury/Injury-Report.pdf",
            report_timestamp=snap_time,
            fetched_at=snap_time,
            sha256=f"sha-{hours_old}",
            entries_count=len(entries or []),
        )
        self.session.add(snap)
        self.session.flush()

        for ent in entries or []:
            e = InjuryEntry(
                snapshot_id=snap.id,
                game_date=snap_time.strftime("%m/%d/%Y"),
                team_name=ent.get("team_name"),
                player_name_raw=ent.get("player_name_raw", "Sample Player"),
                status=ent.get("status", "Out"),
                reason=ent.get("reason", "Ankle sprain"),
                availability_prob=Decimal(str(ent.get("prob", 0.0))),
            )
            self.session.add(e)
        self.session.commit()
        return snap


# -----------------------------------------------------------------------------
# Tests
# -----------------------------------------------------------------------------

def test_empty_database_returns_200_with_empty_list(client: TestClient):
    """An empty database returns 200 OK with an empty list."""
    res = client.get("/api/v1/week")
    assert res.status_code == 200
    assert res.json() == []


def test_week_view_success_with_odds_and_injuries(client: TestClient, db_session: Session):
    """Complete week view item with predictions, lines,line shopping, and injuries."""
    world = SyntheticWorld(db_session)
    game = world.make_game(home="AAA", away="BBB", days_ahead=2.0)

    # Pinnacle sharp quotes
    world.add_quote(game, "pinnacle", BetSide.home.value, -110, hours_old=3.0)
    world.add_quote(game, "pinnacle", BetSide.away.value, -110, hours_old=3.0)

    # Soft quotes: DraftKings has better home odds (+110)
    world.add_quote(game, "draftkings", BetSide.home.value, 110, hours_old=2.0)
    world.add_quote(game, "fanduel", BetSide.away.value, -105, hours_old=1.5)

    # Injury report
    world.add_snapshot(
        hours_old=4.0,
        entries=[
            {
                "team_name": "AAA Basketball Team",
                "player_name_raw": "Star Player",
                "status": "Out",
                "reason": "Ankle",
                "prob": 0.0,
            },
            {
                "team_name": "BBB Basketball Team",
                "player_name_raw": "Role Player",
                "status": "Questionable",
                "reason": "Illness",
                "prob": 0.5,
            },
        ],
    )

    items = build_week_view(db_session, days=7, now=NOW)
    assert len(items) == 1
    item = items[0]

    assert item.game_id == game.id
    assert item.home_team.abbreviation == "AAA"
    assert item.away_team.abbreviation == "BBB"

    # Champion predictions
    assert item.champion_prediction is not None
    assert item.champion_prediction.p_home > 0.5  # AAA rating (1600) > BBB (1500)
    assert item.champion_prediction.projected_margin > 0.0

    # Market & Quotes
    assert item.home_market.fair_prob is not None
    assert item.home_market.best_book == "draftkings"
    assert item.home_market.best_price == 2.10  # +110 -> 2.10
    assert item.home_market.quote_age_minutes == pytest.approx(120.0, abs=1.0)
    assert item.home_market.edge is not None

    # Injuries
    assert len(item.home_team.injuries.entries) == 1
    assert item.home_team.injuries.entries[0].player_name == "Star Player"
    assert item.home_team.injuries.entries[0].status == "Out"
    assert item.home_team.injuries.stale is False
    assert len(item.away_team.injuries.entries) == 1
    assert item.away_team.injuries.entries[0].player_name == "Role Player"


def test_week_view_no_odds(client: TestClient, db_session: Session):
    """When no odds exist, predictions still compute, but candidate reason is no_quotes."""
    world = SyntheticWorld(db_session)
    game = world.make_game(home="AAA", away="BBB", days_ahead=1.5)

    items = build_week_view(db_session, days=7, now=NOW)
    assert len(items) == 1
    item = items[0]

    assert item.champion_prediction is not None
    assert item.home_market.fair_prob is None
    assert item.home_market.best_price is None
    assert item.home_market.would_qualify is False
    assert item.home_market.reason == "no_sharp_reference"


def test_week_view_no_injuries(client: TestClient, db_session: Session):
    """When no injury snapshot exists, injuries entries is empty and stale is True."""
    world = SyntheticWorld(db_session)
    world.make_game(home="AAA", away="BBB", days_ahead=1.0)

    items = build_week_view(db_session, days=7, now=NOW)
    assert len(items) == 1
    item = items[0]

    assert item.home_team.injuries.entries == []
    assert item.home_team.injuries.stale is True
    assert item.away_team.injuries.entries == []
    assert item.away_team.injuries.stale is True
    assert item.injury_snapshot_stale is True


def test_week_view_stale_injuries(client: TestClient, db_session: Session):
    """When injury snapshot is older than 36 h, stale is set to True."""
    world = SyntheticWorld(db_session)
    world.make_game(home="AAA", away="BBB", days_ahead=2.0)
    world.add_snapshot(
        hours_old=40.0,
        entries=[
            {
                "team_name": "AAA Basketball Team",
                "player_name_raw": "Old Injury",
                "status": "Out",
                "reason": "Rest",
            }
        ],
    )

    items = build_week_view(db_session, days=7, now=NOW)
    assert len(items) == 1
    item = items[0]

    assert len(item.home_team.injuries.entries) == 1
    assert item.home_team.injuries.stale is True
    assert item.injury_snapshot_stale is True


def test_policy_flag_matches_recorder_hand_case(db_session: Session):
    """Candidate 'would qualify' flag and reason match policy.evaluate_candidate exactly."""
    world = SyntheticWorld(db_session)
    game = world.make_game(home="AAA", away="BBB", days_ahead=1.0)

    # Pinnacle fair line at even money (-105 / -105)
    world.add_quote(game, "pinnacle", BetSide.home.value, -105, hours_old=1.0)
    world.add_quote(game, "pinnacle", BetSide.away.value, -105, hours_old=1.0)

    # Soft book offers +130 on home (decimal 2.30)
    world.add_quote(game, "draftkings", BetSide.home.value, 130, hours_old=0.5)

    items = build_week_view(db_session, days=7, now=NOW)
    assert len(items) == 1
    item = items[0]

    # Hand calculation:
    p_home = item.champion_prediction.p_home
    fair_home, _ = devig_two_way(1.952, 1.952)  # -105 -> 1.952
    expected_decision = policy.evaluate_candidate(
        p_win=p_home,
        p_push=0.0,
        p_loss=1.0 - p_home,
        p_fair=fair_home,
        decimal_price=2.30,
    )

    assert item.home_market.would_qualify == expected_decision.eligible
    assert item.home_market.reason == expected_decision.reason
    assert item.home_market.ev == pytest.approx(expected_decision.ev, abs=0.001)
    assert item.home_market.p_blend == pytest.approx(expected_decision.p_blend, abs=0.001)


def test_pure_read_only_nothing_is_written(db_session: Session):
    """Verifies that running build_week_view leaves the database 100% untouched."""
    world = SyntheticWorld(db_session)
    game = world.make_game(home="AAA", away="BBB", days_ahead=2.0)
    world.add_quote(game, "pinnacle", BetSide.home.value, -110)
    world.add_quote(game, "pinnacle", BetSide.away.value, -110)
    world.add_quote(game, "draftkings", BetSide.home.value, 120)

    counts_before = {
        "predictions": db_session.execute(select(func.count(ModelPrediction.id))).scalar_one(),
        "simulated_bets": db_session.execute(select(func.count(SimulatedBet.id))).scalar_one(),
        "games": db_session.execute(select(func.count(Game.id))).scalar_one(),
        "odds": db_session.execute(select(func.count(OddsHistory.id))).scalar_one(),
    }

    _ = build_week_view(db_session, days=7, now=NOW)

    counts_after = {
        "predictions": db_session.execute(select(func.count(ModelPrediction.id))).scalar_one(),
        "simulated_bets": db_session.execute(select(func.count(SimulatedBet.id))).scalar_one(),
        "games": db_session.execute(select(func.count(Game.id))).scalar_one(),
        "odds": db_session.execute(select(func.count(OddsHistory.id))).scalar_one(),
    }

    assert counts_before == counts_after
    assert counts_after["predictions"] == 0
    assert counts_after["simulated_bets"] == 0


def test_days_window_filtering(db_session: Session):
    """Scheduled games beyond the days window are excluded."""
    world = SyntheticWorld(db_session)
    g1 = world.make_game(home="AAA", away="BBB", days_ahead=2.0)
    g2 = world.make_game(home="BBB", away="CCC", days_ahead=5.0)
    g3 = world.make_game(home="CCC", away="DDD", days_ahead=10.0)

    items_7 = build_week_view(db_session, days=7, now=NOW)
    game_ids_7 = [it.game_id for it in items_7]
    assert g1.id in game_ids_7
    assert g2.id in game_ids_7
    assert g3.id not in game_ids_7

    items_14 = build_week_view(db_session, days=14, now=NOW)
    game_ids_14 = [it.game_id for it in items_14]
    assert g1.id in game_ids_14
    assert g2.id in game_ids_14
    assert g3.id in game_ids_14


def test_challenger_predictions_included(db_session: Session):
    """When active challenger model exists, its predictions are included in challenger_predictions."""
    world = SyntheticWorld(db_session)

    # Register an active Elo challenger with different sigma
    challenger = ModelVersion(
        name=MODEL_NAME,
        version="2.0-test",
        params={"sigma": 12.0},
        role=MODEL_ROLE_CHALLENGER,
    )
    db_session.add(challenger)
    db_session.commit()

    # Seed ratings for challenger
    for i, (abbr, rating) in enumerate(RATINGS.items()):
        db_session.add(
            TeamEloRating(
                model_version_id=challenger.id,
                team_id=world.teams[abbr].id,
                season_id=world.old_season.id,
                game_id=f"00225{i:05d}",
                game_date=date(2026, 4, 10),
                rating_after=rating,
            )
        )
    db_session.commit()

    world.make_game(home="AAA", away="BBB", days_ahead=1.0)

    items = build_week_view(db_session, days=7, now=NOW)
    assert len(items) == 1
    item = items[0]
    assert len(item.challenger_predictions) == 1
    assert item.challenger_predictions[0].model_id == challenger.id
    assert item.challenger_predictions[0].model_name == MODEL_NAME
    assert item.challenger_predictions[0].p_home > 0.0


def test_week_api_endpoint_populated(client: TestClient, db_session: Session):
    """Test GET /api/v1/week endpoint end-to-end with TestClient."""
    world = SyntheticWorld(db_session)
    real_now = datetime.now(timezone.utc)
    game = Game(
        provider_event_id="evt-real-now",
        season_id=world.new_season.id,
        home_team_id=world.teams["AAA"].id,
        away_team_id=world.teams["BBB"].id,
        commence_time=real_now + timedelta(days=2),
        status="scheduled",
    )
    db_session.add(game)
    db_session.commit()

    # Add quotes relative to real_now
    captured = real_now - timedelta(hours=1)
    q_home = OddsHistory(
        game_id=game.id,
        sportsbook_id=world.books["pinnacle"].id,
        market=MarketType.h2h,
        side=BetSide.home.value,
        price_american=-110,
        captured_at=captured,
        book_last_update=captured - timedelta(minutes=5),
    )
    q_away = OddsHistory(
        game_id=game.id,
        sportsbook_id=world.books["pinnacle"].id,
        market=MarketType.h2h,
        side=BetSide.away.value,
        price_american=-110,
        captured_at=captured,
        book_last_update=captured - timedelta(minutes=5),
    )
    db_session.add_all([q_home, q_away])
    db_session.commit()

    res = client.get("/api/v1/week?days=7")
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["game_id"] == game.id
    assert data[0]["home_team"]["abbreviation"] == "AAA"
    assert data[0]["away_team"]["abbreviation"] == "BBB"
    assert data[0]["champion_prediction"]["p_home"] > 0.5



def test_week_view_uses_latest_snapshot_when_several_exist(db_session: Session):
    """Several stored snapshots must not break the view: only the newest one is shown."""
    world = SyntheticWorld(db_session)
    world.make_game(home="AAA", away="BBB", days_ahead=1.0)
    world.add_snapshot(
        hours_old=10.0,
        entries=[{"team_name": "AAA Basketball Team", "player_name_raw": "Old Entry", "status": "Out"}],
    )
    world.add_snapshot(
        hours_old=2.0,
        entries=[{"team_name": "AAA Basketball Team", "player_name_raw": "New Entry", "status": "Out"}],
    )

    items = build_week_view(db_session, days=7, now=NOW)
    names = [e.player_name for e in items[0].home_team.injuries.entries]
    assert names == ["New Entry"]
    assert items[0].injury_snapshot_stale is False


def test_injury_entries_carry_impact_when_a_lookup_is_available(db_session: Session):
    from app.services.week_view import _match_team_injuries

    world = SyntheticWorld(db_session)
    world.add_snapshot(
        hours_old=1.0,
        entries=[
            {"team_name": "AAA Basketball Team", "player_name_raw": "Star", "status": "Out"},
            {"team_name": "AAA Basketball Team", "player_name_raw": "Unknown Id", "status": "Out"},
        ],
    )
    from app.services.week_view import _load_injuries_by_team

    _, by_team = _load_injuries_by_team(db_session)
    for entry_list in by_team.values():
        for e in entry_list:
            e.player_id = 7 if e.player_name_raw == "Star" else None

    def lookup(player_id: int) -> float:
        return 4.2567

    out = _match_team_injuries(world.teams["AAA"], by_team, lookup)
    impacts = {e.player_name: e.impact for e in out}
    assert impacts == {"Star": 4.26, "Unknown Id": None}

    def broken(player_id: int) -> float:
        raise RuntimeError("boom")

    assert all(e.impact is None for e in _match_team_injuries(world.teams["AAA"], by_team, broken))
