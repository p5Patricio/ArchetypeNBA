import importlib.util
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from app.models import (
    CAPTURE_CLOSING,
    CAPTURE_CLOSING_PROPS,
    CAPTURE_OPENING,
    MarketType,
    OddsHistory,
    OddsSnapshotCapture,
    Player,
    Season,
    Team,
)
from app.services import odds_api_service
from app.services.odds_api_service import GameQuote, OddsQuote
from app.services.odds_ingestion import OddsIngestionService
from app.services.odds_snapshot import (
    credit_guard,
    events_with_marker,
    plan_snapshot,
    record_capture,
    run_snapshot,
    select_closing_events,
    valid_prop_markets,
)

NOW = datetime(2026, 10, 21, 22, 0, tzinfo=timezone.utc)


def _event(event_id, minutes_from_now, home="Boston Celtics", away="LA Clippers"):
    tip = NOW + timedelta(minutes=minutes_from_now)
    return {
        "id": event_id,
        "commence_time": tip.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "home_team": home,
        "away_team": away,
    }


# --- closing selection (pure) -----------------------------------------------------------

def test_closing_selects_only_events_inside_the_window_earliest_first():
    events = [
        _event("late", 120),
        _event("soon_b", 40),
        _event("soon_a", 10),
        _event("started", -5),
        _event("edge", 45),
    ]

    picked = select_closing_events(events, NOW, 45, already_captured=set())

    assert [e["id"] for e in picked] == ["soon_a", "soon_b", "edge"]


def test_closing_skips_events_that_already_have_a_closing_snapshot():
    events = [_event("done", 20), _event("todo", 30)]

    picked = select_closing_events(events, NOW, 45, already_captured={"done"})

    assert [e["id"] for e in picked] == ["todo"]


def test_closing_ignores_events_with_missing_id_or_time():
    events = [{"commence_time": "2026-10-21T22:10:00Z"}, {"id": "x"}, {"id": "y", "commence_time": "garbage"}]

    assert select_closing_events(events, NOW, 45, set()) == []


# --- capture markers (DB) -------------------------------------------------------------------------

@pytest.fixture
def world(db_session):
    db_session.add(Season(season_label="2026-27", start_date=date(2026, 10, 20), end_date=date(2027, 6, 30), is_active=True))
    for abbr, full in [("BOS", "Boston Celtics"), ("LAC", "LA Clippers")]:
        db_session.add(Team(abbreviation=abbr, full_name=full, city="", conference="", division=""))
    db_session.add(Player(id=1, full_name="Luka Doncic"))
    db_session.commit()
    return db_session


def _game_for(session, event):
    ingestion = OddsIngestionService(session)
    tip = datetime.strptime(event["commence_time"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    game = ingestion.upsert_game(event["id"], tip, event["home_team"], event["away_team"])
    session.commit()
    return game


def _markers(session, kind=None):
    query = select(OddsSnapshotCapture).order_by(OddsSnapshotCapture.id)
    if kind is not None:
        query = query.where(OddsSnapshotCapture.kind == kind)
    return list(session.exec(query).all())


def test_capture_table_is_created_without_a_migration(world):
    assert inspect(world.get_bind()).has_table("odds_snapshot_capture")


def test_events_with_marker_only_reports_games_marked_with_that_kind(world):
    closing = _event("closing_done", 30)
    props_only = _event("props_done", 30)
    unmarked = _event("unmarked", 30)
    unknown = _event("never_seen", 30)  # no game row at all
    record_capture(world, _game_for(world, closing).id, CAPTURE_CLOSING, NOW)
    record_capture(world, _game_for(world, props_only).id, CAPTURE_CLOSING_PROPS, NOW)
    _game_for(world, unmarked)
    world.commit()
    events = [closing, props_only, unmarked, unknown]

    assert events_with_marker(world, events, CAPTURE_CLOSING) == {"closing_done"}
    assert events_with_marker(world, events, CAPTURE_CLOSING_PROPS) == {"props_done"}
    assert events_with_marker(world, [], CAPTURE_CLOSING) == set()
    with pytest.raises(ValueError):
        events_with_marker(world, events, "bogus")


def test_a_second_closing_marker_for_the_same_game_is_ignored_not_fatal(world):
    game = _game_for(world, _event("a", 10))

    first = record_capture(world, game.id, CAPTURE_CLOSING, NOW, credits_spent=3)
    second = record_capture(world, game.id, CAPTURE_CLOSING, NOW, credits_spent=3)
    props = record_capture(world, game.id, CAPTURE_CLOSING_PROPS, NOW, credits_spent=1)
    world.commit()

    assert first is not None and second is None and props is not None
    assert [m.kind for m in _markers(world)] == [CAPTURE_CLOSING, CAPTURE_CLOSING_PROPS]


def test_opening_markers_may_repeat_but_the_database_rejects_duplicate_closing_rows(world):
    game = _game_for(world, _event("a", 10))

    assert record_capture(world, game.id, CAPTURE_OPENING, NOW) is not None
    assert record_capture(world, game.id, CAPTURE_OPENING, NOW + timedelta(days=1)) is not None
    world.commit()
    assert len(_markers(world, CAPTURE_OPENING)) == 2

    # bypass record_capture's exists-check: the partial unique index is the real guarantee
    world.add(OddsSnapshotCapture(game_id=game.id, kind=CAPTURE_CLOSING, captured_at=NOW))
    world.commit()
    world.add(OddsSnapshotCapture(game_id=game.id, kind=CAPTURE_CLOSING, captured_at=NOW))
    with pytest.raises(IntegrityError):
        world.commit()
    world.rollback()

    world.add(OddsSnapshotCapture(game_id=game.id, kind="bogus", captured_at=NOW))
    with pytest.raises(IntegrityError):
        world.commit()
    world.rollback()


# --- credit guard ---------------------------------------------------------------------------------

@pytest.mark.parametrize(
    "remaining,cost,floor,allowed",
    [
        (100, 3, 25, True),
        (28, 3, 25, True),  # leaves exactly the floor
        (27, 3, 25, False),  # would dip below the floor
        (10, 3, 25, False),
        (None, 3, 25, False),  # unknown quota: never spend blind
        (None, 0, 25, True),  # free calls are always fine
    ],
)
def test_credit_guard(remaining, cost, floor, allowed):
    assert credit_guard(remaining, cost, floor)[0] is allowed


# --- planning ---------------------------------------------------------------------------------------------

def test_plan_costs_match_the_odds_api_cost_model():
    opening = plan_snapshot("opening", 0, ["player_points"])
    closing = plan_snapshot("closing", 3, ["player_points"])
    closing_two_markets = plan_snapshot("closing", 2, ["player_points", "player_rebounds"])

    assert opening.total_credits == 3
    assert closing.total_credits == 3 + 3
    assert closing_two_markets.total_credits == 3 + 2 * 2
    assert plan_snapshot("opening", 0, []).steps[0].credits == 0  # /events is free
    assert closing.props_only_credits == 3  # 3 props events x 1 market; game lines are skipped once every due game is marked
    assert closing_two_markets.props_only_credits == 2 * 2
    assert opening.props_only_credits == opening.total_credits  # opening never skips its call


def test_prop_market_validation_rejects_unsupported_markets():
    assert valid_prop_markets(["player_points", "player_assists"]) == ["player_points", "player_assists"]
    with pytest.raises(ValueError):
        valid_prop_markets(["player_steals"])


# --- orchestration with a fake service ----------------------------------------------------------------------

class FakeService:
    """Stands in for OddsApiService; every paid call lowers requests_remaining like the real API."""

    def __init__(self, events, remaining=200, fail_lines=False, fail_props=False):
        self.events = events
        self.requests_remaining = remaining
        self.fail_lines = fail_lines
        self.fail_props = fail_props
        self.last_call_ok = False
        self.calls = []

    def fetch_upcoming_events(self):
        self.calls.append("events")
        return self.events

    def fetch_game_lines(self, bookmakers=None):
        self.calls.append("game_lines")
        self.last_call_ok = not self.fail_lines
        if self.fail_lines:  # non-200 responses are not charged
            return []
        self.requests_remaining -= 3
        quotes = []
        for e in self.events:
            for side, price in (("home", -150), ("away", 130)):
                quotes.append(
                    GameQuote(
                        event_id=e["id"], commence_time=e["commence_time"], home_team=e["home_team"],
                        away_team=e["away_team"], bookmaker_key="pinnacle", bookmaker_title="Pinnacle",
                        market_key="h2h", side=side, line=None, price_american=price,
                        book_last_update="2026-10-21T21:59:00Z",
                    )
                )
        return quotes

    def fetch_event_prop_quotes(self, event_id, markets=None):
        self.calls.append(f"props:{event_id}:{','.join(markets or [])}")
        self.last_call_ok = not self.fail_props
        if self.fail_props:
            return []
        self.requests_remaining -= len(markets or [])
        return [
            OddsQuote(
                event_id=event_id, bookmaker_key="draftkings", market_key="player_points", stat_type="PTS",
                player_name="Luka Dončić", side="over", line=27.5, price_american=-115,
                book_last_update="2026-10-21T21:59:00Z",
            )
        ]


def test_opening_makes_one_game_lines_call_and_stores_the_slate(world):
    service = FakeService([_event("a", 600), _event("b", 700)])

    summary = run_snapshot(world, service, "opening", props_events=0, now=NOW)

    assert service.calls == ["events", "game_lines"]
    assert summary.status == "captured"
    assert summary.game_lines.inserted == 4
    assert summary.credits_spent == 3


def test_closing_without_due_events_spends_nothing(world):
    service = FakeService([_event("later", 300)])

    summary = run_snapshot(world, service, "closing", props_events=3, now=NOW)

    assert summary.status == "nothing_due"
    assert service.calls == ["events"]


def test_closing_fetches_props_only_for_up_to_n_due_events_and_only_stores_due_events(world):
    service = FakeService([_event("a", 10), _event("b", 20), _event("c", 30), _event("far", 400)])

    summary = run_snapshot(world, service, "closing", props_events=2, props_markets=["player_points"], now=NOW)

    assert service.calls == ["events", "game_lines", "props:a:player_points", "props:b:player_points"]
    assert summary.events_targeted == 3
    assert summary.game_lines.inserted == 6  # 3 due events x 2 sides; "far" is not stored
    assert summary.props.inserted == 2
    stored_markets = {r.market for r in world.exec(select(OddsHistory)).all()}
    assert stored_markets == {MarketType.h2h, MarketType.player_points}


def test_a_second_closing_run_in_the_same_window_spends_nothing(world):
    events = [_event("a", 10)]
    first = FakeService(events)
    run_snapshot(world, first, "closing", props_events=1, now=NOW)

    second = FakeService(events)
    summary = run_snapshot(world, second, "closing", props_events=1, now=NOW + timedelta(minutes=5))

    assert summary.status == "nothing_due"
    assert second.calls == ["events"]


def test_closing_run_with_no_new_rows_still_marks_the_game_and_the_next_run_spends_nothing(world):
    events = [_event("a", 10)]
    run_snapshot(world, FakeService(events), "opening", props_events=0, now=NOW)  # stores the same quotes

    first = FakeService(events)
    summary = run_snapshot(world, first, "closing", props_events=0, now=NOW + timedelta(minutes=1))

    assert first.calls == ["events", "game_lines"]  # the opening run did not suppress the closing call
    assert summary.game_line_quotes == 2 and summary.game_lines.inserted == 0  # every quote was a duplicate
    closing = _markers(world, CAPTURE_CLOSING)
    assert len(closing) == 1
    assert (closing[0].quotes_seen, closing[0].quotes_inserted, closing[0].credits_spent) == (2, 0, 3)

    second = FakeService(events)
    again = run_snapshot(world, second, "closing", props_events=0, now=NOW + timedelta(minutes=6))

    assert again.status == "nothing_due"
    assert second.calls == ["events"]  # no /odds request at all
    assert second.requests_remaining == 200


def test_an_opening_run_inside_the_window_does_not_suppress_the_closing_capture(world):
    events = [_event("a", 10)]
    run_snapshot(world, FakeService(events), "opening", props_events=0, now=NOW)
    assert [m.kind for m in _markers(world)] == [CAPTURE_OPENING]

    service = FakeService(events)
    summary = run_snapshot(world, service, "closing", props_events=1, now=NOW + timedelta(minutes=2))

    assert summary.status == "captured"
    assert service.calls == ["events", "game_lines", "props:a:player_points"]
    assert [m.kind for m in _markers(world)] == [CAPTURE_OPENING, CAPTURE_CLOSING, CAPTURE_CLOSING_PROPS]


def test_props_markers_let_later_runs_pick_the_next_game_without_new_game_line_calls(world):
    events = [_event("a", 20), _event("b", 25), _event("c", 30)]
    picked = []
    spent = []
    for step in range(4):
        service = FakeService(events)
        run_snapshot(world, service, "closing", props_events=1, now=NOW + timedelta(minutes=step))
        picked.append([c for c in service.calls if c != "events"])
        spent.append(200 - service.requests_remaining)

    assert picked == [
        ["game_lines", "props:a:player_points"],
        ["props:b:player_points"],  # game lines already marked: props-only run
        ["props:c:player_points"],
        [],  # everything marked: not a single paid call
    ]
    assert spent == [4, 1, 1, 0]
    assert len(_markers(world, CAPTURE_CLOSING)) == 3
    assert len(_markers(world, CAPTURE_CLOSING_PROPS)) == 3


def test_game_lines_credits_are_recorded_on_the_first_marker_and_props_credits_per_event(world):
    run_snapshot(world, FakeService([_event("b", 25), _event("a", 20)]), "closing", props_events=1, now=NOW)

    closing = _markers(world, CAPTURE_CLOSING)
    props = _markers(world, CAPTURE_CLOSING_PROPS)

    assert [m.credits_spent for m in closing] == [3, 0]  # earliest tip-off carries the 3 credits
    assert [m.credits_spent for m in props] == [1]
    assert (props[0].quotes_seen, props[0].quotes_inserted) == (1, 1)


def test_a_failed_game_lines_call_writes_no_marker_and_the_next_run_retries(world):
    events = [_event("a", 10)]
    failing = FakeService(events, fail_lines=True)

    summary = run_snapshot(world, failing, "closing", props_events=1, now=NOW)

    assert summary.status == "call_failed"
    assert failing.calls == ["events", "game_lines"]  # no props after a failed lines call
    assert _markers(world) == []
    assert world.exec(select(OddsHistory)).first() is None

    retry = FakeService(events)
    assert run_snapshot(world, retry, "closing", props_events=1, now=NOW + timedelta(minutes=5)).status == "captured"
    assert retry.calls == ["events", "game_lines", "props:a:player_points"]


def test_a_failed_props_call_writes_no_props_marker_but_keeps_the_closing_marker(world):
    events = [_event("a", 10)]
    failing = FakeService(events, fail_props=True)

    summary = run_snapshot(world, failing, "closing", props_events=1, now=NOW)

    assert "Props call failed" in summary.message
    assert [m.kind for m in _markers(world)] == [CAPTURE_CLOSING]

    retry = FakeService(events)
    run_snapshot(world, retry, "closing", props_events=1, now=NOW + timedelta(minutes=5))

    assert retry.calls == ["events", "props:a:player_points"]  # props-only retry, no /odds
    assert [m.kind for m in _markers(world)] == [CAPTURE_CLOSING, CAPTURE_CLOSING_PROPS]


def test_a_props_only_run_checks_the_credit_guard_for_the_props_cost(world):
    events = [_event("a", 10)]
    run_snapshot(world, FakeService(events), "closing", props_events=0, now=NOW)  # lines marked, props pending

    blocked = FakeService(events, remaining=25)
    summary = run_snapshot(world, blocked, "closing", props_events=1, min_remaining=25, now=NOW)

    assert summary.status == "aborted_low_credits"
    assert blocked.calls == ["events"]
    assert _markers(world, CAPTURE_CLOSING_PROPS) == []


def test_low_credits_abort_before_any_paid_call(world):
    service = FakeService([_event("a", 10)], remaining=26)

    summary = run_snapshot(world, service, "closing", props_events=3, min_remaining=25, now=NOW)

    assert summary.status == "aborted_low_credits"
    assert service.calls == ["events"]
    assert world.exec(select(OddsHistory)).first() is None


def test_props_stop_when_the_guard_trips_mid_run(world):
    # 30 left: game lines (3) -> 27, first prop call (1) -> 26, second would leave 25 -> allowed, third -> 24 blocked
    service = FakeService([_event("a", 5), _event("b", 10), _event("c", 15)], remaining=30)

    summary = run_snapshot(world, service, "closing", props_events=3, min_remaining=25, now=NOW)

    assert [c for c in service.calls if c.startswith("props")] == ["props:a:player_points", "props:b:player_points"]
    assert "Props stopped early" in summary.message


def test_no_upcoming_events_means_no_paid_calls(world):
    service = FakeService([])

    assert run_snapshot(world, service, "opening", props_events=0, now=NOW).status == "no_events"
    assert service.calls == ["events"]


# --- CLI ------------------------------------------------------------------------------------------------------------------

def _load_cli():
    path = Path(__file__).resolve().parents[1] / "scripts" / "capture_odds_snapshot.py"
    spec = importlib.util.spec_from_file_location("capture_odds_snapshot", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("network access attempted")

    monkeypatch.setattr(odds_api_service.httpx, "Client", forbidden)
    monkeypatch.setattr(httpx, "Client", forbidden)


@pytest.mark.parametrize("phase,expected_cost", [("opening", 3), ("closing", 4)])
def test_cli_dry_run_prints_the_plan_and_never_touches_the_network(no_network, capsys, phase, expected_cost):
    cli = _load_cli()

    exit_code = cli.main(["--phase", phase, "--dry-run"])

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "DRY RUN" in out
    assert f"worst-case cost: {expected_cost} credits" in out
    assert ("props-only run" in out) is (phase == "closing")


def test_cli_rejects_unknown_prop_markets(no_network, capsys):
    cli = _load_cli()

    assert cli.main(["--phase", "closing", "--props-markets", "player_steals", "--dry-run"]) == 1
    assert "unsupported prop market" in capsys.readouterr().out


def test_cli_without_api_key_exits_before_any_call(no_network, monkeypatch, capsys):
    cli = _load_cli()
    monkeypatch.setattr(odds_api_service.settings, "THE_ODDS_API_KEY", "")

    assert cli.main(["--phase", "opening"]) == 1
    assert "THE_ODDS_API_KEY" in capsys.readouterr().out
