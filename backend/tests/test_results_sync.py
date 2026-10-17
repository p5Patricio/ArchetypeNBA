import zlib
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import pytest
from sqlmodel import select

from app.models import Game, Player, PlayerGameLog, Season, Team, TeamEloRating
from app.services.elo_service import EloRatingService
from app.services.results_sync import (
    FetchedLogs,
    GameResult,
    NbaApiResultsProvider,
    ResultsProviderError,
    find_pending_games,
    match_results,
    sync_results,
    us_game_date,
)

NOW = datetime(2026, 10, 23, 12, 0, tzinfo=timezone.utc)
TIPOFF_1 = datetime(2026, 10, 21, 23, 30, tzinfo=timezone.utc)  # 7:30 pm ET on Oct 21
TIPOFF_2 = datetime(2026, 10, 22, 2, 0, tzinfo=timezone.utc)  # 10 pm ET Oct 21 / 7 pm PT, already Oct 22 in UTC


# --- fakes ----------------------------------------------------------------------------------------------------

def log_rows(game_id, game_date, home, away, home_pts, away_pts, wl=True):
    """Player rows of one game as nba_api returns them: two players per team, points summing to the score."""
    rows = []
    for team, matchup, total in ((home, f"{home} vs. {away}", home_pts), (away, f"{away} @ {home}", away_pts)):
        won = (total > (away_pts if team == home else home_pts))
        for index, share in enumerate((total - 10, 10)):
            rows.append(
                {
                    "PLAYER_ID": 1 + zlib.crc32(f"{team}-{index}".encode()) % 1_000_000,
                    "PLAYER_NAME": f"{team} player {index}",
                    "TEAM_ID": 0,
                    "TEAM_ABBREVIATION": team,
                    "GAME_ID": game_id,
                    "GAME_DATE": f"{game_date.isoformat()}T00:00:00",
                    "MATCHUP": matchup,
                    "WL": ("W" if won else "L") if wl else None,
                    "MIN": 30.5,
                    "PTS": share,
                }
            )
    return rows


class FakeProvider:
    def __init__(self, rows=None, error=None):
        self.rows = list(rows or [])
        self.error = error
        self.calls = []

    def fetch_player_game_logs(self, season_label, date_from, date_to):
        self.calls.append((season_label, date_from, date_to))
        if self.error:
            raise self.error
        return FetchedLogs(rows=self.rows, api_calls=1)


@pytest.fixture
def world(db_session):
    old = Season(season_label="2025-26", start_date=date(2025, 10, 21), end_date=date(2026, 6, 30), is_active=False)
    new = Season(season_label="2026-27", start_date=date(2026, 10, 1), end_date=date(2027, 6, 30), is_active=True)
    db_session.add_all([old, new])
    teams = {}
    for abbr in ("BOS", "LAC", "NYK", "LAL"):
        teams[abbr] = Team(abbreviation=abbr, full_name=abbr, city="", conference="", division="")
        db_session.add(teams[abbr])
    db_session.commit()
    db_session.teams = teams
    db_session.new_season = new
    return db_session


def add_game(session, home, away, start, status="scheduled", event="e"):
    game = Game(
        provider_event_id=f"{event}-{home}-{away}-{start.isoformat()}",
        season_id=session.new_season.id,
        home_team_id=session.teams[home].id,
        away_team_id=session.teams[away].id,
        commence_time=start,
        status=status,
    )
    session.add(game)
    session.commit()
    return game


def refreshed(session, game):
    session.refresh(game)
    return game


# --- gating -----------------------------------------------------------------------------------------------------

def test_nothing_unresolved_means_no_provider_call(world):
    add_game(world, "BOS", "LAC", NOW + timedelta(hours=5))  # upcoming
    add_game(world, "NYK", "LAL", NOW - timedelta(hours=2, minutes=59))  # tipped off, inside the 3 h grace
    add_game(world, "LAC", "NYK", NOW - timedelta(days=1), status="final")
    provider = FakeProvider()

    summary = sync_results(world, provider, NOW)

    assert provider.calls == [] and summary.api_calls == 0
    assert summary.games_pending == 0 and not summary.did_work


def test_games_older_than_the_lookback_are_not_chased(world):
    add_game(world, "BOS", "LAC", NOW - timedelta(days=20))
    provider = FakeProvider()

    summary = sync_results(world, provider, NOW)

    assert provider.calls == [] and summary.games_stale == 1 and summary.games_pending == 0


def test_dry_run_only_counts_pending_games(world):
    add_game(world, "BOS", "LAC", TIPOFF_1)
    provider = FakeProvider(log_rows("0022600001", date(2026, 10, 21), "BOS", "LAC", 110, 100))

    summary = sync_results(world, provider, NOW, dry_run=True)

    assert provider.calls == [] and summary.games_pending == 1
    assert world.exec(select(PlayerGameLog)).all() == []


# --- matching and scores --------------------------------------------------------------------------------------

def test_a_finished_game_gets_scores_status_and_nba_game_id(world):
    game = add_game(world, "BOS", "LAC", TIPOFF_1)
    provider = FakeProvider(log_rows("0022600001", date(2026, 10, 21), "BOS", "LAC", 112, 104))

    summary = sync_results(world, provider, NOW)

    game = refreshed(world, game)
    assert (game.status, game.nba_game_id, game.home_score, game.away_score) == ("final", "0022600001", 112, 104)
    assert summary.games_finalized == 1 and summary.api_calls == 1 and summary.unmatched == []
    # the window is the US date of the tip-off +-1 day, of the season of the game
    assert provider.calls == [("2026-27", date(2026, 10, 20), date(2026, 10, 22))]
    seasons = {log.season_id for log in world.exec(select(PlayerGameLog)).all()}
    assert seasons == {world.new_season.id}
    assert world.get(Player, world.exec(select(PlayerGameLog.player_id)).first()) is not None


def test_scores_follow_the_game_rows_home_and_away_whatever_the_matchup_says(world):
    game = add_game(world, "LAC", "BOS", TIPOFF_1)  # the odds feed lists LAC as home
    provider = FakeProvider(log_rows("0022600001", date(2026, 10, 21), "BOS", "LAC", 99, 120))  # NBA says BOS is home

    sync_results(world, provider, NOW)

    game = refreshed(world, game)
    assert (game.home_score, game.away_score) == (120, 99)


@pytest.mark.parametrize("offset_days", [-1, 0, 1])
def test_dates_within_one_day_match(world, offset_days):
    game = add_game(world, "BOS", "LAC", TIPOFF_1)
    provider = FakeProvider(log_rows("0022600001", date(2026, 10, 21) + timedelta(days=offset_days), "BOS", "LAC", 100, 90))

    sync_results(world, provider, NOW)

    assert refreshed(world, game).status == "final"


def test_a_result_two_days_away_does_not_match(world):
    game = add_game(world, "BOS", "LAC", TIPOFF_1)
    provider = FakeProvider(log_rows("0022600001", date(2026, 10, 19), "BOS", "LAC", 100, 90))

    summary = sync_results(world, provider, NOW)

    game = refreshed(world, game)
    assert game.status == "scheduled" and game.home_score is None and game.nba_game_id is None
    assert summary.unmatched == ["LAC @ BOS 2026-10-21"]


def test_other_teams_do_not_match(world):
    game = add_game(world, "BOS", "LAC", TIPOFF_1)
    provider = FakeProvider(log_rows("0022600001", date(2026, 10, 21), "NYK", "LAL", 100, 90))

    summary = sync_results(world, provider, NOW)

    assert refreshed(world, game).status == "scheduled" and summary.games_finalized == 0
    assert summary.logs_inserted > 0  # the other game is stored anyway: player_game_log is the source of truth


def test_a_series_with_two_games_a_few_days_apart_never_swaps_results(world):
    first = add_game(world, "BOS", "LAC", datetime(2026, 10, 21, 23, 30, tzinfo=timezone.utc))
    second = add_game(world, "BOS", "LAC", datetime(2026, 10, 22, 23, 30, tzinfo=timezone.utc))
    rows = log_rows("0022600001", date(2026, 10, 21), "BOS", "LAC", 100, 90) + log_rows(
        "0022600002", date(2026, 10, 22), "BOS", "LAC", 95, 105
    )

    sync_results(world, FakeProvider(rows), NOW)

    first, second = refreshed(world, first), refreshed(world, second)
    assert (first.nba_game_id, first.home_score) == ("0022600001", 100)
    assert (second.nba_game_id, second.home_score) == ("0022600002", 95)


def test_the_closest_date_wins_when_two_results_could_match(world):
    game = add_game(world, "BOS", "LAC", TIPOFF_1)
    rows = log_rows("0022600009", date(2026, 10, 22), "BOS", "LAC", 80, 70) + log_rows(
        "0022600001", date(2026, 10, 21), "BOS", "LAC", 100, 90
    )

    sync_results(world, FakeProvider(rows), NOW)

    assert refreshed(world, game).nba_game_id == "0022600001"


def test_a_late_west_coast_tipoff_uses_the_us_date(world):
    assert us_game_date(TIPOFF_2) == date(2026, 10, 21)
    game = add_game(world, "LAL", "NYK", TIPOFF_2)

    sync_results(world, FakeProvider(log_rows("0022600003", date(2026, 10, 21), "LAL", "NYK", 101, 99)), NOW)

    assert refreshed(world, game).status == "final"


def test_rows_without_a_result_or_with_unknown_teams_are_ignored(world):
    game = add_game(world, "BOS", "LAC", TIPOFF_1)
    in_progress = log_rows("0022600001", date(2026, 10, 21), "BOS", "LAC", 60, 55, wl=False)  # still being played
    junk = log_rows("0012600005", date(2026, 10, 21), "EST", "WST", 70, 60)  # not NBA teams

    summary = sync_results(world, FakeProvider(in_progress + junk), NOW)

    assert refreshed(world, game).status == "scheduled"
    assert world.exec(select(PlayerGameLog)).all() == []
    assert summary.rows_skipped == len(in_progress) + len(junk)
    assert world.exec(select(Team).where(Team.abbreviation == "EST")).all() == []


def test_a_postponed_game_stays_scheduled_and_the_others_are_finalized(world):
    done = add_game(world, "BOS", "LAC", TIPOFF_1)
    postponed = add_game(world, "NYK", "LAL", TIPOFF_1, event="pp")
    provider = FakeProvider(log_rows("0022600001", date(2026, 10, 21), "BOS", "LAC", 110, 100))

    summary = sync_results(world, provider, NOW)

    assert refreshed(world, done).status == "final"
    postponed = refreshed(world, postponed)
    assert postponed.status == "scheduled" and postponed.home_score is None
    assert summary.unmatched == ["LAL @ NYK 2026-10-21"] and summary.games_finalized == 1


def test_existing_nba_game_ids_are_never_assigned_twice(world):
    add_game(world, "BOS", "LAC", datetime(2026, 10, 10, 23, 30, tzinfo=timezone.utc), status="final")
    taken = world.exec(select(Game)).first()
    taken.nba_game_id = "0022600001"
    world.add(taken)
    world.commit()
    pending = add_game(world, "BOS", "LAC", TIPOFF_1)

    sync_results(world, FakeProvider(log_rows("0022600001", date(2026, 10, 21), "BOS", "LAC", 100, 90)), NOW)

    assert refreshed(world, pending).status == "scheduled"


def test_match_results_is_a_pure_function_over_games_and_results(world):
    game = add_game(world, "BOS", "LAC", TIPOFF_1)
    ids = (world.teams["BOS"].id, world.teams["LAC"].id)
    result = GameResult("0022600001", date(2026, 10, 21), {ids[0]: 100, ids[1]: 90})

    assert match_results([game], {result.nba_game_id: result}, taken=set()) == {game.id: result}
    assert match_results([game], {result.nba_game_id: result}, taken={"0022600001"}) == {}


# --- idempotency and Elo -------------------------------------------------------------------------------------

def test_a_second_sync_changes_nothing_and_skips_the_provider(world):
    add_game(world, "BOS", "LAC", TIPOFF_1)
    provider = FakeProvider(log_rows("0022600001", date(2026, 10, 21), "BOS", "LAC", 112, 104))
    sync_results(world, provider, NOW)
    logs_before = len(world.exec(select(PlayerGameLog)).all())
    ratings_before = len(world.exec(select(TeamEloRating)).all())

    again = sync_results(world, provider, NOW + timedelta(minutes=15))

    assert len(provider.calls) == 1
    assert not again.did_work and again.api_calls == 0
    assert len(world.exec(select(PlayerGameLog)).all()) == logs_before
    assert len(world.exec(select(TeamEloRating)).all()) == ratings_before


def test_elo_is_updated_after_the_sync_and_equals_a_full_rebuild(world):
    add_game(world, "BOS", "LAC", TIPOFF_1)
    add_game(world, "NYK", "LAL", TIPOFF_2)
    rows = log_rows("0022600001", date(2026, 10, 21), "BOS", "LAC", 112, 104) + log_rows(
        "0022600002", date(2026, 10, 21), "NYK", "LAL", 99, 108
    )

    summary = sync_results(world, FakeProvider(rows), NOW)

    assert summary.rating_rows_added == 4 and not summary.elo_rebuilt
    incremental = {
        (r.team_id, r.game_id): (r.rating_before, r.rating_after) for r in world.exec(select(TeamEloRating)).all()
    }
    assert len(incremental) == 4
    EloRatingService(world).rebuild_all()
    rebuilt = {(r.team_id, r.game_id): (r.rating_before, r.rating_after) for r in world.exec(select(TeamEloRating)).all()}
    assert incremental.keys() == rebuilt.keys()
    for key, values in incremental.items():
        assert values == pytest.approx(rebuilt[key])
    boston = world.teams["BOS"].id
    assert incremental[(boston, "0022600001")][1] > 1500  # the winner moved up


def test_a_final_game_waiting_for_its_rating_is_rated_without_any_network_call(world):
    game = add_game(world, "BOS", "LAC", TIPOFF_1)
    sync_results(world, FakeProvider(log_rows("0022600001", date(2026, 10, 21), "BOS", "LAC", 112, 104)), NOW)
    for rating in world.exec(select(TeamEloRating)).all():  # simulate an Elo update that failed after the commit
        world.delete(rating)
    world.commit()
    provider = FakeProvider()

    summary = sync_results(world, provider, NOW + timedelta(minutes=15))

    assert provider.calls == [] and summary.elo_catch_up_games == 1 and summary.rating_rows_added == 2
    assert refreshed(world, game).status == "final"


# --- failures -------------------------------------------------------------------------------------------------

def test_a_provider_failure_leaves_games_and_logs_untouched(world):
    game = add_game(world, "BOS", "LAC", TIPOFF_1)
    provider = FakeProvider(error=ResultsProviderError("nba_api is down"))

    with pytest.raises(ResultsProviderError):
        sync_results(world, provider, NOW)

    game = refreshed(world, game)
    assert (game.status, game.home_score, game.nba_game_id) == ("scheduled", None, None)
    assert world.exec(select(PlayerGameLog)).all() == []


def test_a_write_failure_rolls_the_whole_sync_back(world, monkeypatch):
    game = add_game(world, "BOS", "LAC", TIPOFF_1)
    provider = FakeProvider(log_rows("0022600001", date(2026, 10, 21), "BOS", "LAC", 112, 104))

    def boom(*args, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr("app.services.results_sync.load_results", boom)

    with pytest.raises(RuntimeError):
        sync_results(world, provider, NOW)

    assert refreshed(world, game).status == "scheduled"
    assert world.exec(select(PlayerGameLog)).all() == []


# --- pending query ----------------------------------------------------------------------------------------------

def test_find_pending_games_respects_grace_and_lookback(world):
    inside = add_game(world, "BOS", "LAC", NOW - timedelta(hours=3, minutes=1))
    add_game(world, "NYK", "LAL", NOW - timedelta(hours=3))  # exactly at the grace limit: not yet
    add_game(world, "LAC", "BOS", NOW - timedelta(days=15))

    pending, stale = find_pending_games(world, NOW)

    assert [g.id for g in pending] == [inside.id] and stale == 1


# --- the nba_api provider (no network) --------------------------------------------------------------------------

class FakeEndpoint:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.kwargs = []

    def __call__(self, **kwargs):
        self.kwargs.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        frame = pd.DataFrame(outcome)
        return type("Response", (), {"get_data_frames": lambda self: [frame]})()


def test_provider_formats_the_window_and_returns_plain_rows():
    endpoint = FakeEndpoint([log_rows("0022600001", date(2026, 10, 21), "BOS", "LAC", 100, 90)])
    provider = NbaApiResultsProvider(endpoint=endpoint, sleep=lambda s: None)

    fetched = provider.fetch_player_game_logs("2026-27", date(2026, 10, 20), date(2026, 10, 22))

    assert fetched.api_calls == 1 and len(fetched.rows) == 4 and fetched.rows[0]["GAME_ID"] == "0022600001"
    assert endpoint.kwargs[0] == {
        "season_nullable": "2026-27",
        "date_from_nullable": "10/20/2026",
        "date_to_nullable": "10/22/2026",
        "timeout": 40,
    }


def test_provider_retries_twice_with_backoff_then_succeeds():
    sleeps = []
    endpoint = FakeEndpoint([TimeoutError("slow"), ConnectionError("reset"), []])
    provider = NbaApiResultsProvider(endpoint=endpoint, sleep=sleeps.append)

    fetched = provider.fetch_player_game_logs("2026-27", date(2026, 10, 20), date(2026, 10, 22))

    assert fetched.rows == [] and fetched.api_calls == 3
    assert sleeps == [2.0, 4.0]


def test_provider_raises_a_clear_error_after_the_last_retry():
    endpoint = FakeEndpoint([TimeoutError("a"), TimeoutError("b"), TimeoutError("c")])
    provider = NbaApiResultsProvider(endpoint=endpoint, sleep=lambda s: None)

    with pytest.raises(ResultsProviderError, match="failed after 3 attempt.*TimeoutError: c"):
        provider.fetch_player_game_logs("2026-27", date(2026, 10, 20), date(2026, 10, 22))


def test_provider_rejects_an_unexpected_payload():
    endpoint = FakeEndpoint([[{"SOMETHING": 1}]])
    provider = NbaApiResultsProvider(endpoint=endpoint, sleep=lambda s: None)

    with pytest.raises(ResultsProviderError, match="lacks column"):
        provider.fetch_player_game_logs("2026-27", date(2026, 10, 20), date(2026, 10, 22))


def test_elo_catch_up_ignores_game_types_elo_never_rates(db_session):
    from app.services.results_sync import count_final_games_without_ratings

    season = Season(season_label="2026-27", is_active=False)
    home = Team(abbreviation="HHH", full_name="Home Team", city="H", conference="East", division="Atlantic")
    away = Team(abbreviation="AAA", full_name="Away Team", city="A", conference="West", division="Pacific")
    db_session.add_all([season, home, away])
    db_session.commit()
    tip = datetime(2026, 10, 20, 23, 0, tzinfo=timezone.utc)
    for index, nba_id in enumerate(("0012600001", "0032600001", "0022600001")):  # preseason, all-star, regular
        db_session.add(Game(
            nba_game_id=nba_id, provider_event_id=f"ev{index}", season_id=season.id,
            home_team_id=home.id, away_team_id=away.id, commence_time=tip + timedelta(days=index),
            status="final", home_score=100, away_score=90,
        ))
    db_session.commit()

    # only the regular-season game is waiting for ratings
    assert count_final_games_without_ratings(db_session) == 1
