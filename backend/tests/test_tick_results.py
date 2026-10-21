"""The ``results`` step of the tick: ordering, gating, isolation, dry run and an end-to-end settlement."""
import importlib.util
import logging
from contextlib import nullcontext
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from sqlmodel import select

from app.models import BetSide, BetStatus, Game, MarketType, PlayerGameLog, SimulatedBet, TeamEloRating
from app.services import tick
from app.services.prediction_recorder import RecorderSummary
from app.services.results_sync import ResultsProviderError
from app.services.tick import default_steps, run_tick
from tests.test_results_sync import FakeProvider, log_rows
from tests.test_settlement import (  # noqa: F401  (world is a fixture)
    CLOSING_AT,
    NOW,
    TIPOFF,
    add_game,
    add_marker,
    add_quote,
    final_game,
    place_bet,
    reload,
    world,
)

NO_CAPTURE = ["opening", "closing"]


class ForbiddenProvider:
    def __getattr__(self, name):
        raise AssertionError(f"the results provider was used: {name}")


def _tick(session, tmp_path, provider, **kwargs):
    kwargs.setdefault("steps", default_steps(skip=NO_CAPTURE))
    return run_tick(session, None, NOW, lock_path=tmp_path / "tick.lock", results_provider=provider, **kwargs)


def _statuses(summary):
    return {step.name: step.status for step in summary.steps}


def _finished_game_with_bet(world):
    """A game that tipped off 4 h ago with a pending home-spread bet and a closing capture."""
    game = add_game(world)
    bet = place_bet(world, game, MarketType.spreads, BetSide.home, line=-3.5, american=100, price="2.0000")
    add_quote(world, game, "pinnacle", MarketType.spreads, BetSide.home, -125, -3.5, captured_at=CLOSING_AT)
    add_marker(world, game)
    return game, bet


def test_results_run_between_capture_and_record_in_a_fixed_order(world, tmp_path, monkeypatch):
    order = []

    class FakeRecorder:
        def __init__(self, session, now=None, **kwargs):
            self.now = now

        def run(self, dry_run=False):
            order.append("record")
            return RecorderSummary(now=self.now)

    real = {name: getattr(tick, name) for name in ("sync_results", "settle_bets", "fill_clv")}
    for name, function in real.items():
        monkeypatch.setattr(tick, name, lambda *a, _n=name, _f=function, **k: order.append(_n) or _f(*a, **k))
    monkeypatch.setattr(tick, "PredictionRecorder", FakeRecorder)

    summary = _tick(world, tmp_path, FakeProvider())

    assert [name for name, _ in default_steps()] == ["opening", "closing", "results", "learn", "record"]
    assert order == ["sync_results", "settle_bets", "fill_clv", "record"]
    assert _statuses(summary) == {"results": "skipped", "learn": "skipped", "record": "ok"}


def test_nothing_unresolved_means_no_provider_call_and_a_skipped_step(world, tmp_path):
    add_game(world, start=NOW + timedelta(hours=5))  # upcoming
    final_game(world, 100, 90, home="NYK", away="LAL")  # already final
    provider = FakeProvider()

    summary = _tick(world, tmp_path, provider)

    assert provider.calls == []
    assert _statuses(summary) == {"results": "skipped", "learn": "skipped", "record": "ok"}
    assert "nothing to do" in summary.steps[0].message


def test_a_finished_game_is_finalized_settled_and_given_its_clv_in_one_tick(world, tmp_path):
    game, bet = _finished_game_with_bet(world)
    provider = FakeProvider(log_rows("0022600001", date(2026, 10, 21), "BOS", "LAC", 112, 104))

    summary = _tick(world, tmp_path, provider)

    assert _statuses(summary) == {"results": "ok", "learn": "skipped", "record": "ok"}
    assert summary.steps[0].message == "1 game(s) finalized, 1 bet(s) settled, CLV filled for 1 bet(s)"
    assert "Elo rating rows added: 2" in summary.steps[0].detail
    game, bet = reload(world, game), reload(world, bet)
    assert (game.status, game.home_score, game.away_score) == ("final", 112, 104)
    assert (bet.status, bet.profit_units) == (BetStatus.won, Decimal("1.000"))  # 8-point win covers -3.5 at 2.0
    assert bet.closing_price == Decimal("1.8000") and float(bet.clv_pct) > 0
    assert len(world.exec(select(TeamEloRating)).all()) == 2
    assert summary.exit_code == 0


def test_a_provider_failure_does_not_stop_settlement_of_final_games_or_the_recorder(world, tmp_path, caplog):
    stuck = add_game(world, "NYK", "LAL")  # tipped off, no result yet -> the provider is called
    done = final_game(world, 110, 100, home="LAC", away="NYK")
    bet = place_bet(world, done, MarketType.h2h, BetSide.home)
    provider = FakeProvider(error=ResultsProviderError("nba_api is down"))

    with caplog.at_level(logging.ERROR, logger="app.services.tick"):
        summary = _tick(world, tmp_path, provider)

    assert _statuses(summary) == {"results": "error", "learn": "skipped", "record": "ok"}
    assert "sync: ResultsProviderError: nba_api is down" in summary.steps[0].detail
    assert "1 bet(s) settled" in summary.steps[0].message
    assert reload(world, bet).status == BetStatus.won
    assert reload(world, stuck).status == "scheduled"
    assert world.exec(select(PlayerGameLog)).all() == []
    assert summary.exit_code == 1


def test_unresolved_games_without_a_published_result_are_not_an_error(world, tmp_path):
    game = add_game(world)
    provider = FakeProvider()  # nba_api answers, but has no rows for the game yet

    summary = _tick(world, tmp_path, provider)

    assert len(provider.calls) == 1
    assert _statuses(summary) == {"results": "ok", "learn": "skipped", "record": "ok"}
    assert "no result yet for 1 game(s): LAC @ BOS 2026-10-21" in summary.steps[0].detail
    assert reload(world, game).status == "scheduled" and summary.exit_code == 0


def test_a_second_tick_does_nothing_more(world, tmp_path):
    _finished_game_with_bet(world)
    provider = FakeProvider(log_rows("0022600001", date(2026, 10, 21), "BOS", "LAC", 112, 104))
    _tick(world, tmp_path, provider)

    second = _tick(world, tmp_path, provider)

    assert len(provider.calls) == 1
    assert _statuses(second) == {"results": "skipped", "learn": "skipped", "record": "ok"}


def test_dry_run_reports_the_plan_without_network_or_writes(world, tmp_path):
    game, bet = _finished_game_with_bet(world)
    final = final_game(world, 110, 100, home="NYK", away="LAL")
    place_bet(world, final, MarketType.h2h, BetSide.home)
    before = (len(world.exec(select(Game)).all()), len(world.exec(select(PlayerGameLog)).all()))

    summary = _tick(world, tmp_path, ForbiddenProvider(), dry_run=True)

    step = summary.steps[0]
    assert step.status == "ok"
    assert step.message == (
        "would look up results of 1 game(s) (1 nba_api call), rate 0 final game(s) waiting for Elo, "
        "settle 1 bet(s), fill CLV for 1 bet(s)"
    )
    assert not world.new and not world.dirty
    assert (len(world.exec(select(Game)).all()), len(world.exec(select(PlayerGameLog)).all())) == before
    assert reload(world, bet).status == BetStatus.pending and reload(world, bet).closing_price is None
    assert reload(world, game).status == "scheduled"
    assert not (tmp_path / "tick.lock").exists()


def test_dry_run_with_nothing_pending_is_skipped(world, tmp_path):
    add_game(world, start=NOW + timedelta(hours=5))

    summary = _tick(world, tmp_path, ForbiddenProvider(), dry_run=True)

    assert _statuses(summary) == {"results": "skipped", "learn": "ok", "record": "ok"}  # learn: a proposal is due


# --- CLI ----------------------------------------------------------------------------------------------------------

def _load_cli():
    path = Path(__file__).resolve().parents[1] / "scripts" / "run_tick.py"
    spec = importlib.util.spec_from_file_location("run_tick_cli_results", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def cli(tmp_path, monkeypatch):
    module = _load_cli()
    monkeypatch.setattr(module, "LOG_FILE", tmp_path / "logs" / "tick.log")
    monkeypatch.setattr(tick, "DEFAULT_LOCK_PATH", tmp_path / "logs" / "tick.lock")
    yield module
    root = logging.getLogger()
    for handler in list(module._installed_handlers):
        root.removeHandler(handler)
        handler.close()
    module._installed_handlers.clear()


def test_cli_skip_results_leaves_the_games_alone(cli, world, monkeypatch, capsys):
    monkeypatch.setattr(cli, "NbaApiResultsProvider", ForbiddenProvider)
    monkeypatch.setattr(cli, "OddsApiService", lambda: type("S", (), {"is_configured": False})())
    game, _ = _finished_game_with_bet(world)

    cli.main(["--skip", "opening", "closing", "results"], session_factory=lambda: nullcontext(world))

    out = capsys.readouterr().out
    assert "[ok] record" in out and "results" not in out
    assert reload(world, game).status == "scheduled"


def test_cli_dry_run_never_builds_the_provider(cli, world, monkeypatch, capsys):
    def exploding():
        raise AssertionError("the nba_api provider was built on a dry run")

    monkeypatch.setattr(cli, "NbaApiResultsProvider", exploding)
    add_game(world, start=datetime.now(timezone.utc) - timedelta(hours=5))  # the CLI runs on the real clock

    exit_code = cli.main(["--dry-run", "--skip", "opening", "closing"], session_factory=lambda: nullcontext(world))

    out = capsys.readouterr().out
    assert exit_code == 0 and "would look up results of 1 game(s)" in out
