import importlib.util
import logging
import logging.handlers
import os
import time
from contextlib import nullcontext
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from sqlmodel import select

from app.models import (
    CAPTURE_CLOSING,
    CAPTURE_OPENING,
    Game,
    ModelPrediction,
    ModelVersion,
    OddsHistory,
    OddsSnapshotCapture,
    Season,
    SimulatedBet,
    Team,
    TeamEloRating,
)
from app.services import odds_api_service, tick
from app.services.elo_service import MODEL_NAME, MODEL_VERSION
from app.services.odds_snapshot import SnapshotSummary
from app.services.prediction_recorder import RecorderSummary
from app.services.results_sync import FetchedLogs, ResultsProviderError
from app.services.tick import (
    StepResult,
    TickLock,
    count_missed_closing,
    default_steps,
    local_day_bounds_utc,
    opening_captured_today,
    run_tick,
)
from tests.test_odds_snapshot import FakeService, _event

NOW = datetime(2026, 10, 21, 22, 0, tzinfo=timezone.utc)
LOCAL = timezone(timedelta(hours=-5))  # fixed "machine zone": NOW is 17:00 on Oct 21 there


# --- fixtures -----------------------------------------------------------------------------------------

@pytest.fixture
def world(db_session):
    old = Season(season_label="2025-26", start_date=date(2025, 10, 21), end_date=date(2026, 6, 30), is_active=False)
    new = Season(season_label="2026-27", start_date=date(2026, 10, 20), end_date=date(2027, 6, 30), is_active=True)
    db_session.add_all([old, new])
    teams = {}
    for abbr, full in [("BOS", "Boston Celtics"), ("LAC", "LA Clippers")]:
        teams[abbr] = Team(abbreviation=abbr, full_name=full, city="", conference="", division="")
        db_session.add(teams[abbr])
    model = ModelVersion(name=MODEL_NAME, version=MODEL_VERSION, params={"sigma": 14.0})
    db_session.add(model)
    db_session.commit()
    for index, (abbr, rating) in enumerate([("BOS", 1600.0), ("LAC", 1500.0)]):
        db_session.add(
            TeamEloRating(
                model_version_id=model.id, team_id=teams[abbr].id, season_id=old.id, game_id=f"00225{index:05d}",
                game_date=date(2026, 4, 10), rating_after=rating,
            )
        )
    db_session.commit()
    db_session.teams = teams  # convenience for the game helper below
    db_session.new_season = new
    return db_session


def _add_game(session, event_id, start, status="scheduled"):
    game = Game(
        provider_event_id=event_id,
        season_id=session.new_season.id,
        home_team_id=session.teams["BOS"].id,
        away_team_id=session.teams["LAC"].id,
        commence_time=start,
        status=status,
    )
    session.add(game)
    session.commit()
    return game


def _marker(session, game, kind, at=NOW):
    session.add(OddsSnapshotCapture(game_id=game.id, kind=kind, captured_at=at))
    session.commit()


@pytest.fixture
def order():
    """Shared call log so tests can assert the order in which the steps did their work."""
    return []


@pytest.fixture
def fake_recorder(monkeypatch, order):
    class FakeRecorder:
        def __init__(self, session, now=None, **kwargs):
            self.now = now

        def run(self, dry_run=False):
            order.append("record")
            return RecorderSummary(now=self.now, dry_run=dry_run)

    monkeypatch.setattr(tick, "PredictionRecorder", FakeRecorder)


def _spy_snapshot(monkeypatch, order, calls=None, raise_for=None):
    def fake(session, service, phase, props_events, **kwargs):
        order.append(f"capture:{phase}")
        if calls is not None:
            calls.append((phase, props_events, kwargs))
        if phase == raise_for:
            raise RuntimeError("odds api exploded")
        return SnapshotSummary(phase=phase, status="no_events", message="spy")

    monkeypatch.setattr(tick, "run_snapshot", fake)


def _configured(service):
    service.is_configured = True  # the real service exposes it; the CLI checks it before running
    return service


class EmptyResultsProvider:
    """nba_api stand-in: no results published yet. The tick tests must never reach the network."""

    def __init__(self):
        self.calls = []

    def fetch_player_game_logs(self, season_label, date_from, date_to):
        self.calls.append((season_label, date_from, date_to))
        return FetchedLogs(rows=[], api_calls=1)


def _tick(session, service, now=NOW, tmp_path=None, **kwargs):
    kwargs.setdefault("lock_path", tmp_path / "tick.lock")
    kwargs.setdefault("local_tz", LOCAL)
    kwargs.setdefault("results_provider", EmptyResultsProvider())
    return run_tick(session, service, now, **kwargs)


def _statuses(summary):
    return {step.name: step.status for step in summary.steps}


# --- opening: once per local day -----------------------------------------------------------------------

def test_opening_runs_once_per_local_day_and_again_on_the_next_one(world, fake_recorder, tmp_path):
    events = [_event("a", 600)]

    first = FakeService(events)
    summary = _tick(world, first, tmp_path=tmp_path)
    assert first.calls == ["events", "game_lines", "events"]  # opening (events + paid), closing (events only)
    assert _statuses(summary) == {"opening": "ok", "closing": "skipped", "results": "skipped", "record": "ok"}
    assert 200 - first.requests_remaining == 3

    # 20:00 local, still Oct 21 there although the UTC date has already changed
    same_day = FakeService(events)
    summary = _tick(world, same_day, now=NOW + timedelta(hours=3), tmp_path=tmp_path)
    assert same_day.calls == ["events"]  # only the closing step's free call
    assert _statuses(summary)["opening"] == "skipped"
    assert "already captured" in summary.steps[0].message

    # 01:00 local on Oct 22
    next_day = FakeService(events)
    summary = _tick(world, next_day, now=NOW + timedelta(hours=8), tmp_path=tmp_path)
    assert "game_lines" in next_day.calls
    assert _statuses(summary)["opening"] == "ok"
    assert len([m for m in world.exec(select(OddsSnapshotCapture)).all() if m.kind == CAPTURE_OPENING]) == 2


def test_local_day_bounds_follow_the_given_zone():
    day, start, end = local_day_bounds_utc(NOW, LOCAL)

    assert day == date(2026, 10, 21)
    assert (start, end) == (datetime(2026, 10, 21, 5, tzinfo=timezone.utc), datetime(2026, 10, 22, 5, tzinfo=timezone.utc))
    assert local_day_bounds_utc(NOW + timedelta(hours=8), LOCAL)[0] == date(2026, 10, 22)


def test_opening_captured_today_ignores_other_days_and_other_kinds(world):
    game = _add_game(world, "x", NOW + timedelta(hours=9))
    _marker(world, game, CAPTURE_CLOSING, at=NOW)
    _marker(world, game, CAPTURE_OPENING, at=NOW - timedelta(hours=18))  # 23:00 local on Oct 20

    assert opening_captured_today(world, NOW, LOCAL) is False

    _marker(world, game, CAPTURE_OPENING, at=NOW - timedelta(hours=1))
    assert opening_captured_today(world, NOW, LOCAL) is True
    assert opening_captured_today(world, NOW + timedelta(hours=8), LOCAL) is False


def test_no_upcoming_events_means_no_paid_call(world, fake_recorder, tmp_path):
    service = FakeService([])

    summary = _tick(world, service, tmp_path=tmp_path)

    assert "game_lines" not in service.calls and set(service.calls) == {"events"}
    assert service.requests_remaining == 200
    assert _statuses(summary) == {"opening": "skipped", "closing": "skipped", "results": "skipped", "record": "ok"}
    assert summary.exit_code == 0


# --- closing delegation ----------------------------------------------------------------------------------------

def test_closing_delegates_with_the_30_minute_window_and_one_props_event(world, fake_recorder, monkeypatch, order, tmp_path):
    calls = []
    _spy_snapshot(monkeypatch, order, calls)

    _tick(world, FakeService([]), tmp_path=tmp_path)
    _tick(world, FakeService([]), tmp_path=tmp_path, window_minutes=20, props_events=0)

    closing = [(props, kw) for phase, props, kw in calls if phase == "closing"]
    assert closing[0][0] == 1 and closing[0][1]["window_minutes"] == 30
    assert closing[0][1]["now"] == NOW and closing[0][1]["min_remaining"] == 25
    assert closing[1][0] == 0 and closing[1][1]["window_minutes"] == 20
    assert [props for phase, props, _ in calls if phase == "opening"] == [0, 0]


def test_closing_captures_only_events_inside_the_tick_window(world, fake_recorder, tmp_path):
    service = FakeService([_event("soon", 20), _event("later", 40)])

    _tick(world, service, tmp_path=tmp_path)

    marked = world.exec(
        select(Game.provider_event_id)
        .join(OddsSnapshotCapture, OddsSnapshotCapture.game_id == Game.id)
        .where(OddsSnapshotCapture.kind == CAPTURE_CLOSING)
    ).all()
    assert marked == ["soon"]


# --- ordering and isolation ------------------------------------------------------------------------------------------

def test_record_runs_after_capture(world, fake_recorder, monkeypatch, order, tmp_path):
    _spy_snapshot(monkeypatch, order)

    summary = _tick(world, FakeService([]), tmp_path=tmp_path)

    assert order == ["capture:opening", "capture:closing", "record"]
    assert _statuses(summary) == {"opening": "skipped", "closing": "skipped", "results": "skipped", "record": "ok"}


def test_record_still_runs_when_capture_raises(world, fake_recorder, monkeypatch, order, tmp_path):
    _spy_snapshot(monkeypatch, order, raise_for="opening")

    summary = _tick(world, FakeService([]), tmp_path=tmp_path)

    assert order == ["capture:opening", "capture:closing", "record"]  # closing and record were not blocked
    assert _statuses(summary) == {"opening": "error", "closing": "skipped", "results": "skipped", "record": "ok"}
    assert "odds api exploded" in summary.steps[0].message
    assert summary.exit_code == 1


def test_a_raising_step_does_not_stop_the_others(world, tmp_path):
    ran = []

    def boom(ctx):
        raise ValueError("bad step")

    def fine(label):
        def step(ctx):
            ran.append(label)
            return StepResult("", "ok", label)

        return step

    summary = _tick(world, None, tmp_path=tmp_path, steps=[("first", fine("first")), ("boom", boom), ("last", fine("last"))])

    assert ran == ["first", "last"]
    assert _statuses(summary) == {"first": "ok", "boom": "error", "last": "ok"}
    assert summary.exit_code == 1
    assert "ValueError: bad step" in str(summary)


def test_a_failed_step_leaves_a_usable_session_for_the_next_one(world, tmp_path):
    def poison(ctx):
        ctx.session.add(Season(season_label="2026-27"))  # violates the unique label: fails on flush
        ctx.session.flush()

    def probe(ctx):
        return StepResult("", "ok", f"{len(ctx.session.exec(select(Season)).all())} seasons")

    summary = _tick(world, None, tmp_path=tmp_path, steps=[("poison", poison), ("probe", probe)])

    assert _statuses(summary) == {"poison": "error", "probe": "ok"}
    assert summary.steps[1].message == "2 seasons"


def test_steps_are_an_ordered_registry_that_accepts_new_entries(world, tmp_path):
    seen = []
    extra = ("extra", lambda ctx: seen.append("extra") or StepResult("", "ok", "added"))

    summary = _tick(world, FakeService([]), tmp_path=tmp_path, steps=[*default_steps(skip=["record", "opening"]), extra])

    assert [step.name for step in summary.steps] == ["closing", "results", "extra"]
    assert seen == ["extra"]
    assert [name for name, _ in default_steps()] == ["opening", "closing", "results", "record"]
    with pytest.raises(ValueError):
        default_steps(skip=["nope"])


def test_failed_paid_call_is_an_error_and_recording_still_runs(world, fake_recorder, order, tmp_path):
    service = FakeService([_event("a", 10)], fail_lines=True)

    summary = _tick(world, service, tmp_path=tmp_path)

    assert _statuses(summary) == {"opening": "error", "closing": "error", "results": "skipped", "record": "ok"}
    assert summary.exit_code == 1
    assert order == ["record"]


def test_missing_api_key_fails_the_capture_steps_but_not_the_recording(world, fake_recorder, order, tmp_path):
    service = FakeService([_event("a", 10)])
    service.is_configured = False

    summary = _tick(world, service, tmp_path=tmp_path)

    assert service.calls == []
    assert _statuses(summary) == {"opening": "error", "closing": "error", "results": "skipped", "record": "ok"}
    assert order == ["record"]


def test_credit_guard_holds_the_capture_back_without_failing_the_tick(world, fake_recorder, tmp_path):
    service = FakeService([_event("a", 10)], remaining=26)

    summary = _tick(world, service, tmp_path=tmp_path)

    assert "game_lines" not in service.calls
    assert _statuses(summary) == {"opening": "skipped", "closing": "skipped", "results": "skipped", "record": "ok"}
    assert "aborted_low_credits" in summary.steps[1].message
    assert summary.exit_code == 0


def test_the_real_recorder_writes_predictions_through_the_tick(world, tmp_path):
    game = _add_game(world, "g1", NOW + timedelta(hours=5))

    summary = _tick(world, FakeService([]), tmp_path=tmp_path, steps=default_steps(skip=["opening", "closing"]))

    assert _statuses(summary) == {"results": "skipped", "record": "ok"}
    rows = world.exec(select(ModelPrediction)).all()
    assert len(rows) == 2 and {r.game_id for r in rows} == {game.id}


# --- lock --------------------------------------------------------------------------------------------------------------------

def test_a_fresh_lock_skips_the_tick_without_doing_any_work(world, order, tmp_path):
    lock = tmp_path / "tick.lock"
    lock.write_text("pid=1 started=now\n", encoding="utf-8")
    service = FakeService([_event("a", 10)])

    summary = _tick(world, service, tmp_path=tmp_path, steps=[("work", lambda ctx: order.append("work"))])

    assert summary.status == "locked" and summary.steps == [] and summary.exit_code == 0
    assert service.calls == [] and order == []
    assert lock.read_text(encoding="utf-8") == "pid=1 started=now\n"  # the other tick's lock is untouched
    assert "locked" in str(summary)


def test_a_stale_lock_is_replaced_and_released(world, tmp_path):
    lock = tmp_path / "tick.lock"
    lock.write_text("pid=1 started=long ago\n", encoding="utf-8")
    stale = time.time() - 21 * 60
    os.utime(lock, (stale, stale))
    inside = []

    summary = _tick(
        world, None, tmp_path=tmp_path,
        steps=[("work", lambda ctx: inside.append(lock.read_text(encoding="utf-8")) or StepResult("", "ok", "done"))],
    )

    assert summary.status == "completed" and _statuses(summary) == {"work": "ok"}
    assert inside and f"pid={os.getpid()}" in inside[0] and "started=" in inside[0]
    assert not lock.exists()


def test_the_lock_is_released_after_an_exception_escapes(world, tmp_path):
    lock = tmp_path / "tick.lock"

    def interrupted(ctx):
        raise KeyboardInterrupt  # not an Exception: it is not isolated by the step runner

    with pytest.raises(KeyboardInterrupt):
        _tick(world, None, tmp_path=tmp_path, steps=[("interrupted", interrupted)])

    assert not lock.exists()
    assert TickLock(lock).acquire()  # a following tick can run


def test_a_lock_is_created_with_its_directory_and_not_deleted_when_taken_over(tmp_path):
    path = tmp_path / "logs" / "tick.lock"
    first = TickLock(path)
    assert first.acquire() and path.exists()
    assert not TickLock(path).acquire()

    path.write_text("someone else\n", encoding="utf-8")  # the lock was replaced behind our back
    first.release()

    assert path.read_text(encoding="utf-8") == "someone else\n"


# --- dry run ---------------------------------------------------------------------------------------------------------------------

class ForbiddenService:
    """Any use of the service on a dry run is a bug."""

    def __getattr__(self, name):
        raise AssertionError(f"dry run touched the odds service: {name}")


def _row_counts(session):
    return [
        len(session.exec(select(model)).all())
        for model in (Game, OddsHistory, OddsSnapshotCapture, ModelPrediction, SimulatedBet)
    ]


def test_dry_run_makes_no_http_call_no_db_write_and_takes_no_lock(world, monkeypatch, tmp_path):
    def forbidden(*args, **kwargs):
        raise AssertionError("network access attempted")

    monkeypatch.setattr(httpx, "Client", forbidden)
    monkeypatch.setattr(odds_api_service.httpx, "Client", forbidden)
    _add_game(world, "g1", NOW + timedelta(hours=5))
    before = _row_counts(world)

    summary = _tick(world, ForbiddenService(), tmp_path=tmp_path, dry_run=True)

    assert _row_counts(world) == before
    assert not world.new and not world.dirty
    assert not (tmp_path / "tick.lock").exists()
    assert _statuses(summary) == {"opening": "ok", "closing": "ok", "results": "skipped", "record": "ok"}
    assert summary.exit_code == 0
    assert sum(step.credits or 0 for step in summary.steps) == 3 + 4  # opening slate + closing lines + 1 props event
    assert "would write 2 prediction(s)" in summary.steps[3].message
    text = str(summary)
    assert "dry run" in text and "worst-case credits: 7" in text


def test_dry_run_still_skips_an_opening_that_is_already_captured(world, tmp_path):
    game = _add_game(world, "g1", NOW + timedelta(hours=5))
    _marker(world, game, CAPTURE_OPENING, at=NOW - timedelta(hours=1))

    summary = _tick(world, ForbiddenService(), tmp_path=tmp_path, dry_run=True)

    assert _statuses(summary)["opening"] == "skipped"
    assert sum(step.credits or 0 for step in summary.steps) == 4


# --- missed closing -----------------------------------------------------------------------------------------------------------

def test_missed_closing_counts_unfinished_started_games_without_a_closing_marker(world, fake_recorder, tmp_path):
    lost = _add_game(world, "lost", NOW - timedelta(hours=3))
    _add_game(world, "lost_live", NOW - timedelta(minutes=30), status="live")
    covered = _add_game(world, "covered", NOW - timedelta(hours=3))
    _marker(world, covered, CAPTURE_CLOSING, at=NOW - timedelta(hours=4))
    _add_game(world, "too_old", NOW - timedelta(hours=13))
    _add_game(world, "finished", NOW - timedelta(hours=2), status="final")
    _add_game(world, "postponed", NOW - timedelta(hours=2), status="postponed")
    _add_game(world, "upcoming", NOW + timedelta(hours=2))
    _marker(world, lost, CAPTURE_OPENING)  # an opening marker is not a closing line

    assert count_missed_closing(world, NOW) == 3  # lost, lost_live and finished (final, but its closing line is gone)

    summary = _tick(world, FakeService([]), tmp_path=tmp_path)
    assert summary.missed_closing == 3
    assert "missed closing lines (last 12 h, PC off or tick missed): 3" in str(summary)


def test_missed_closing_is_logged_as_a_warning(world, fake_recorder, caplog, tmp_path):
    _add_game(world, "lost", NOW - timedelta(hours=3))

    with caplog.at_level(logging.WARNING, logger="app.services.tick"):
        _tick(world, FakeService([]), tmp_path=tmp_path)

    assert any("without a closing capture" in record.getMessage() for record in caplog.records)


# --- CLI ----------------------------------------------------------------------------------------------------------------------------

def _load_cli():
    path = Path(__file__).resolve().parents[1] / "scripts" / "run_tick.py"
    spec = importlib.util.spec_from_file_location("run_tick_cli", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def cli(tmp_path, monkeypatch):
    module = _load_cli()
    monkeypatch.setattr(module, "NbaApiResultsProvider", EmptyResultsProvider)
    monkeypatch.setattr(module, "LOG_FILE", tmp_path / "logs" / "tick.log")
    monkeypatch.setattr(tick, "DEFAULT_LOCK_PATH", tmp_path / "logs" / "tick.lock")
    yield module
    root = logging.getLogger()
    for handler in list(module._installed_handlers):  # do not leave handlers bound to a captured stream
        root.removeHandler(handler)
        handler.close()
    module._installed_handlers.clear()


def test_cli_dry_run_prints_the_plan_without_network_lock_or_log_file(cli, world, monkeypatch, capsys, tmp_path):
    def forbidden(*args, **kwargs):
        raise AssertionError("network access attempted")

    monkeypatch.setattr(httpx, "Client", forbidden)
    monkeypatch.setattr(odds_api_service.httpx, "Client", forbidden)

    exit_code = cli.main(["--dry-run", "--skip", "record"], session_factory=lambda: nullcontext(world))

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "dry run" in out and "worst-case credits: 7" in out and "[ok] record" not in out
    assert not (tmp_path / "logs").exists()


def test_cli_logs_to_a_rotating_file_and_exits_with_the_summary_code(cli, world, monkeypatch, capsys, tmp_path, order, fake_recorder):
    monkeypatch.setattr(cli, "OddsApiService", lambda: _configured(FakeService([_event("a", 600)])))

    exit_code = cli.main([], session_factory=lambda: nullcontext(world))

    assert exit_code == 0
    log_text = (tmp_path / "logs" / "tick.log").read_text(encoding="utf-8")
    assert "Tick " in log_text and "[ok] opening" in log_text and "exit code: 0" in log_text
    rotating = [h for h in cli._installed_handlers if isinstance(h, logging.handlers.RotatingFileHandler)]
    assert len(rotating) == 1 and (rotating[0].maxBytes, rotating[0].backupCount) == (2 * 1024 * 1024, 3)
    assert logging.getLogger("httpx").level == logging.WARNING
    assert not (tmp_path / "logs" / "tick.lock").exists()
    assert "Tick " in capsys.readouterr().out


def test_cli_exit_code_is_1_when_a_step_fails(cli, world, monkeypatch, tmp_path, order, fake_recorder):
    monkeypatch.setattr(cli, "OddsApiService", lambda: _configured(FakeService([_event("a", 10)], fail_lines=True)))

    assert cli.main([], session_factory=lambda: nullcontext(world)) == 1
    assert order == ["record"]


def test_cli_rejects_an_unknown_step_to_skip(cli):
    with pytest.raises(SystemExit):
        cli.main(["--skip", "bogus"])
