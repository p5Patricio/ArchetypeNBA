from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
import pytest

from scripts.log_lineups import (
    build_lineup_record,
    extract_team_lineup_info,
    log_lineups,
    parse_game_tipoff,
)


def test_parse_game_tipoff():
    assert parse_game_tipoff({}) is None
    assert parse_game_tipoff({"gameTimeUTC": "invalid"}) is None

    dt = parse_game_tipoff({"gameTimeUTC": "2026-10-28T19:30:00Z"})
    assert dt is not None
    assert dt.tzinfo is not None
    assert dt.year == 2026
    assert dt.month == 10
    assert dt.day == 28
    assert dt.hour == 19
    assert dt.minute == 30


def test_extract_team_lineup_info():
    team_data = {
        "teamTricode": "BOS",
        "players": [
            {"name": "Jaylen Brown", "starter": "1", "status": "ACTIVE"},
            {"name": "Jayson Tatum", "starter": "1", "status": "ACTIVE"},
            {"name": "Derrick White", "starter": "1", "status": "ACTIVE"},
            {"name": "Jrue Holiday", "starter": "1", "status": "ACTIVE"},
            {"name": "Al Horford", "starter": "1", "status": "ACTIVE"},
            {"name": "Payton Pritchard", "starter": "0", "status": "ACTIVE"},
            {
                "name": "Kristaps Porzingis",
                "starter": "0",
                "status": "INACTIVE",
                "notPlayingReason": "Injury/Illness",
                "notPlayingDescription": "Surgery rehabilitation",
            },
            {
                "name": "Luke Kornet",
                "starter": "0",
                "status": "ACTIVE",
                "notPlayingReason": "Coach's Decision",
            },
        ],
    }

    info = extract_team_lineup_info(team_data)
    assert info["tricode"] == "BOS"
    assert info["starters_count"] == 5
    assert info["not_playing_count"] == 2
    assert len(info["not_playing_players"]) == 2

    kp = next(p for p in info["not_playing_players"] if p["name"] == "Kristaps Porzingis")
    assert kp["status"] == "INACTIVE"
    assert "Injury/Illness" in kp["reason"]

    lk = next(p for p in info["not_playing_players"] if p["name"] == "Luke Kornet")
    assert lk["reason"] == "Coach's Decision"


def test_log_lineups_in_window(tmp_path):
    log_file = tmp_path / "lineups.jsonl"
    fixed_now = datetime(2026, 10, 28, 18, 45, 0, tzinfo=timezone.utc)

    # 3 games: Game 1 in 45m (in window), Game 2 in 120m (outside), Game 3 started 15m ago (outside)
    mock_games = [
        {"gameId": "0022600001", "gameTimeUTC": "2026-10-28T19:30:00Z"},
        {"gameId": "0022600002", "gameTimeUTC": "2026-10-28T20:45:00Z"},
        {"gameId": "0022600003", "gameTimeUTC": "2026-10-28T18:30:00Z"},
    ]

    mock_boxscore = {
        "homeTeam": {
            "teamTricode": "DET",
            "players": [
                {"name": "Cade Cunningham", "starter": "1", "status": "ACTIVE"},
                {"name": "Isaiah Stewart", "starter": "0", "status": "INACTIVE", "notPlayingReason": "Ankle"},
            ],
        },
        "awayTeam": {
            "teamTricode": "BOS",
            "players": [
                {"name": "Jaylen Brown", "starter": "1", "status": "ACTIVE"},
                {"name": "Kristaps Porzingis", "starter": "0", "status": "INACTIVE", "notPlayingReason": "Knee"},
            ],
        },
    }

    called_boxscores = []

    def fake_scoreboard():
        return mock_games

    def fake_boxscore(game_id: str):
        called_boxscores.append(game_id)
        return mock_boxscore

    count = log_lineups(
        window_minutes=60,
        dry_run=False,
        log_file=log_file,
        now=fixed_now,
        scoreboard_fetcher=fake_scoreboard,
        boxscore_fetcher=fake_boxscore,
    )

    assert count == 1
    assert called_boxscores == ["0022600001"]
    assert log_file.exists()

    with open(log_file, "r", encoding="utf-8") as f:
        lines = f.readlines()

    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["game_id"] == "0022600001"
    assert entry["minutes_to_tipoff"] == 45.0
    assert entry["away_team"]["tricode"] == "BOS"
    assert entry["away_team"]["starters_count"] == 1
    assert entry["away_team"]["not_playing_count"] == 1
    assert entry["away_team"]["not_playing_players"][0]["name"] == "Kristaps Porzingis"
    assert entry["home_team"]["tricode"] == "DET"
    assert entry["home_team"]["starters_count"] == 1
    assert entry["home_team"]["not_playing_count"] == 1


def test_log_lineups_dry_run(tmp_path, capsys):
    log_file = tmp_path / "lineups.jsonl"
    fixed_now = datetime(2026, 10, 28, 19, 0, 0, tzinfo=timezone.utc)
    mock_games = [{"gameId": "0022600001", "gameTimeUTC": "2026-10-28T19:30:00Z"}]
    mock_boxscore = {
        "homeTeam": {"teamTricode": "DET", "players": []},
        "awayTeam": {"teamTricode": "BOS", "players": []},
    }

    count = log_lineups(
        window_minutes=60,
        dry_run=True,
        log_file=log_file,
        now=fixed_now,
        scoreboard_fetcher=lambda: mock_games,
        boxscore_fetcher=lambda gid: mock_boxscore,
    )

    assert count == 1
    assert not log_file.exists()  # dry-run does not write to file
    captured = capsys.readouterr()
    assert "[dry-run]" in captured.out
    assert "0022600001" in captured.out


def test_log_lineups_resilience_and_retry(tmp_path):
    log_file = tmp_path / "lineups.jsonl"
    fixed_now = datetime(2026, 10, 28, 19, 0, 0, tzinfo=timezone.utc)

    # 1. Scoreboard fails on attempt 1, succeeds on attempt 2
    attempts = [0]

    def flaky_scoreboard():
        attempts[0] += 1
        if attempts[0] == 1:
            raise RuntimeError("Temporary network timeout")
        return [{"gameId": "0022600001", "gameTimeUTC": "2026-10-28T19:30:00Z"}]

    count = log_lineups(
        window_minutes=60,
        dry_run=False,
        log_file=log_file,
        now=fixed_now,
        scoreboard_fetcher=flaky_scoreboard,
        boxscore_fetcher=lambda gid: {"homeTeam": {}, "awayTeam": {}},
    )
    assert count == 1
    assert attempts[0] == 2

    # 2. Fatal scoreboard failure logs and returns 0 without raising
    def fatal_scoreboard():
        raise RuntimeError("Fatal network error")

    count_fatal = log_lineups(
        window_minutes=60,
        dry_run=False,
        log_file=log_file,
        now=fixed_now,
        scoreboard_fetcher=fatal_scoreboard,
        boxscore_fetcher=lambda gid: {},
    )
    assert count_fatal == 0


def test_log_lineups_db_storage_and_idempotency(db_session, tmp_path):
    from sqlmodel import select
    from app.models import Game, LineupSnapshot, Season, Team

    session = db_session
    log_file = tmp_path / "lineups.jsonl"
    fixed_now = datetime(2026, 10, 28, 19, 0, 0, tzinfo=timezone.utc)
    tipoff = datetime(2026, 10, 28, 19, 30, 0, tzinfo=timezone.utc)

    # Seed Season, Teams and Game
    season = Season(season_label="2026-27", is_active=True)
    session.add(season)
    session.flush()

    home_t = Team(abbreviation="DET", full_name="Detroit Pistons", city="Detroit", conference="East", division="Central")
    away_t = Team(abbreviation="BOS", full_name="Boston Celtics", city="Boston", conference="East", division="Atlantic")
    session.add_all([home_t, away_t])
    session.flush()

    game = Game(
        season_id=season.id,
        home_team_id=home_t.id,
        away_team_id=away_t.id,
        commence_time=tipoff,
        nba_game_id="0022600001",
        status="scheduled",
    )
    session.add(game)
    session.commit()

    mock_games = [{"gameId": "0022600001", "gameTimeUTC": "2026-10-28T19:30:00Z"}]
    mock_boxscore = {
        "homeTeam": {
            "teamTricode": "DET",
            "players": [{"name": "Cade Cunningham", "starter": "1", "status": "ACTIVE"}],
        },
        "awayTeam": {
            "teamTricode": "BOS",
            "players": [{"name": "Jaylen Brown", "starter": "1", "status": "ACTIVE"}],
        },
    }

    # First call: writes to JSONL AND inserts DB rows
    count = log_lineups(
        window_minutes=60,
        dry_run=False,
        log_file=log_file,
        now=fixed_now,
        scoreboard_fetcher=lambda: mock_games,
        boxscore_fetcher=lambda gid: mock_boxscore,
        session=session,
    )
    assert count == 1
    assert log_file.exists()

    db_snaps = session.exec(select(LineupSnapshot).where(LineupSnapshot.game_id == game.id)).all()
    assert len(db_snaps) == 2
    sides = {s.side for s in db_snaps}
    assert sides == {"home", "away"}
    for s in db_snaps:
        assert s.starters_count == 1
        assert s.not_playing_count == 0
        assert s.minutes_to_tipoff == Decimal("30.0")

    # Second call (same captured_at): idempotent, no duplicate rows created
    count2 = log_lineups(
        window_minutes=60,
        dry_run=False,
        log_file=log_file,
        now=fixed_now,
        scoreboard_fetcher=lambda: mock_games,
        boxscore_fetcher=lambda gid: mock_boxscore,
        session=session,
    )
    assert count2 == 1
    db_snaps2 = session.exec(select(LineupSnapshot).where(LineupSnapshot.game_id == game.id)).all()
    assert len(db_snaps2) == 2

