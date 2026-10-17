"""Tests for the Elo backfill/evaluation service (app.services.elo_service) on a synthetic in-memory DB."""
from datetime import date, timedelta

import pytest
from sqlmodel import select

from app.analytics import elo
from app.models import ModelVersion, Player, PlayerGameLog, Season, Team, TeamEloRating
from app.services.elo_service import (
    DEFAULT_SIGMA,
    EloRatingService,
    out_of_sample_summary,
    replay_games,
)

TEAMS = ["ATL", "BOS", "BKN", "NJN", "NOP", "NOH", "EST"]  # EST = All-Star junk row, not an NBA franchise


@pytest.fixture
def world(db_session):
    seasons = {}
    for label in ("2003-04", "2004-05", "2005-06"):
        season = Season(season_label=label)
        db_session.add(season)
        db_session.flush()
        seasons[label] = season.id
    teams = {}
    for abbr in TEAMS:
        team = Team(abbreviation=abbr, full_name=abbr, city=abbr, conference="E", division="X")
        db_session.add(team)
        db_session.flush()
        teams[abbr] = team.id
    players = {}
    for abbr in TEAMS:
        for n in (1, 2):
            player = Player(full_name=f"{abbr} player {n}")
            db_session.add(player)
            db_session.flush()
            players[(abbr, n)] = player.id
    db_session.commit()
    return {"session": db_session, "seasons": seasons, "teams": teams, "players": players}


def add_game(world, game_id, game_date, season, home, away, home_pts, away_pts, home_marker="vs.", away_marker="@"):
    """Two player rows per team whose pts sum to the team score (as in player_game_log)."""
    session = world["session"]
    sides = [
        (home, away, home_pts, f"{home} {home_marker} {away}"),
        (away, home, away_pts, f"{away} {away_marker} {home}"),
    ]
    for abbr, _, pts, matchup in sides:
        for n, share in ((1, pts // 2), (2, pts - pts // 2)):
            session.add(
                PlayerGameLog(
                    player_id=world["players"][(abbr, n)],
                    team_id=world["teams"][abbr],
                    season_id=world["seasons"][season],
                    game_id=game_id,
                    game_date=game_date,
                    matchup=matchup,
                    pts=share,
                )
            )
    session.commit()


def all_rows(session):
    return session.exec(
        select(TeamEloRating).order_by(TeamEloRating.game_date, TeamEloRating.game_id, TeamEloRating.team_id)
    ).all()


def snapshot(session):
    return [
        (r.team_id, r.season_id, r.game_id, r.rating_before, r.rating_after, r.result, r.win_probability)
        for r in all_rows(session)
    ]


def assert_snapshots_equal(a, b):
    assert len(a) == len(b)
    for left, right in zip(a, b):
        assert left[:3] == right[:3]
        assert left[5] == right[5]
        assert left[3:5] + left[6:] == pytest.approx(right[3:5] + right[6:])


def populate_three_seasons(world):
    """12 deterministic games over three seasons between ATL, BOS, BKN/NJN and NOP/NOH."""
    start = date(2003, 11, 1)
    schedule = [
        ("0020300001", "2003-04", "ATL", "BOS", 100, 95),
        ("0020300002", "2003-04", "NJN", "NOH", 90, 99),
        ("0020300003", "2003-04", "BOS", "NJN", 110, 100),
        ("0020300004", "2003-04", "NOH", "ATL", 97, 101),
        ("0020400001", "2004-05", "ATL", "NJN", 88, 102),
        ("0020400002", "2004-05", "BOS", "NOP", 105, 90),
        ("0020400003", "2004-05", "NJN", "ATL", 99, 98),
        ("0020400004", "2004-05", "NOP", "BOS", 101, 111),
        ("0020500001", "2005-06", "BKN", "NOP", 120, 100),
        ("0020500002", "2005-06", "ATL", "BOS", 90, 93),
        ("0020500003", "2005-06", "NOP", "ATL", 94, 107),
        ("0020500004", "2005-06", "BOS", "BKN", 99, 96),
    ]
    for i, (game_id, season, home, away, home_pts, away_pts) in enumerate(schedule):
        add_game(world, game_id, start + timedelta(days=i * 100), season, home, away, home_pts, away_pts)
    return schedule


def test_load_games_reconstructs_scores_and_home_away(world):
    add_game(world, "0020300001", date(2003, 11, 1), "2003-04", "ATL", "BOS", 101, 98)
    games = EloRatingService(world["session"]).load_games()
    assert len(games) == 1
    game = games[0]
    assert game.home_team_id == world["teams"]["ATL"]
    assert game.away_team_id == world["teams"]["BOS"]
    assert (game.home_pts, game.away_pts) == (101, 98)
    assert game.game_date == date(2003, 11, 1)
    assert game.season_id == world["seasons"]["2003-04"]


def test_load_games_is_chronological_and_filters_by_since(world):
    add_game(world, "0020300009", date(2003, 12, 5), "2003-04", "BOS", "ATL", 100, 90)
    add_game(world, "0020300001", date(2003, 11, 1), "2003-04", "ATL", "BOS", 101, 98)
    service = EloRatingService(world["session"])
    assert [g.game_id for g in service.load_games()] == ["0020300001", "0020300009"]
    assert [g.game_id for g in service.load_games(since=date(2003, 12, 1))] == ["0020300009"]


def test_preseason_and_all_star_are_excluded_but_other_types_counted(world):
    for i, game_type in enumerate("123456"):
        add_game(world, f"00{game_type}0300{i:03d}"[:10], date(2003, 11, 1 + i), "2003-04", "ATL", "BOS", 100, 90)
    ids = [g.game_id for g in EloRatingService(world["session"]).load_games()]
    assert sorted(i[2] for i in ids) == ["2", "4", "5", "6"]


def test_games_with_non_nba_team_are_skipped_and_reported(world):
    add_game(world, "0020300001", date(2003, 11, 1), "2003-04", "ATL", "EST", 100, 90)
    service = EloRatingService(world["session"])
    assert service.load_games() == []
    assert service.last_load_report.unmapped_abbreviations["EST"] == 1


def test_game_with_one_team_or_ambiguous_home_away_is_skipped(world):
    session = world["session"]
    session.add(
        PlayerGameLog(
            player_id=world["players"][("ATL", 1)],
            team_id=world["teams"]["ATL"],
            season_id=world["seasons"]["2003-04"],
            game_id="0020300001",
            game_date=date(2003, 11, 1),
            matchup="ATL vs. BOS",
            pts=100,
        )
    )
    session.commit()
    # neutral-site style game: both rows say '@'
    add_game(world, "0020300002", date(2003, 11, 2), "2003-04", "ATL", "BOS", 100, 90, home_marker="@")
    service = EloRatingService(session)
    assert service.load_games() == []
    assert service.last_load_report.skipped_not_two_teams == 1
    assert service.last_load_report.skipped_home_away == 1


def test_franchise_mapping_keeps_a_single_rating_line(world):
    teams = world["teams"]
    add_game(world, "0020300001", date(2003, 11, 1), "2003-04", "NJN", "ATL", 100, 90)
    add_game(world, "0020500001", date(2005, 11, 1), "2005-06", "BKN", "ATL", 100, 90)
    add_game(world, "0020300002", date(2003, 11, 2), "2003-04", "NOH", "ATL", 100, 90)
    add_game(world, "0020500002", date(2005, 11, 2), "2005-06", "NOP", "ATL", 100, 90)
    service = EloRatingService(world["session"])
    games = service.load_games()
    assert {g.home_team_id for g in games} == {teams["BKN"], teams["NOP"]}

    service.rebuild_all()
    team_ids = {r.team_id for r in all_rows(world["session"])}
    assert team_ids == {teams["BKN"], teams["NOP"], teams["ATL"]}
    bkn = [r for r in all_rows(world["session"]) if r.team_id == teams["BKN"]]
    assert [r.game_id for r in bkn] == ["0020300001", "0020500001"]
    assert bkn[1].rating_before == pytest.approx(elo.season_carryover(bkn[0].rating_after))


def test_rebuild_persists_two_rows_per_game_with_consistent_fields(world):
    add_game(world, "0020300001", date(2003, 11, 1), "2003-04", "ATL", "BOS", 110, 100)
    summary = EloRatingService(world["session"]).rebuild_all()
    rows = all_rows(world["session"])
    assert summary.games_used == 1
    assert summary.rows_written == len(rows) == 2

    atl = next(r for r in rows if r.team_id == world["teams"]["ATL"])
    bos = next(r for r in rows if r.team_id == world["teams"]["BOS"])
    assert (atl.result, bos.result) == ("W", "L")
    assert atl.opponent_team_id == bos.team_id and bos.opponent_team_id == atl.team_id
    assert atl.rating_before == bos.rating_before == elo.INITIAL_RATING
    assert atl.win_probability == pytest.approx(elo.expected_home_win_prob(1500, 1500))
    assert atl.win_probability + bos.win_probability == pytest.approx(1.0)
    assert atl.rating_after + bos.rating_after == pytest.approx(3000)
    assert atl.k_factor == elo.K and atl.season_id == world["seasons"]["2003-04"]


def test_season_carryover_is_applied_on_first_game_of_new_season(world):
    add_game(world, "0020300001", date(2004, 4, 1), "2003-04", "ATL", "BOS", 110, 100)
    add_game(world, "0020400001", date(2004, 11, 1), "2004-05", "ATL", "BOS", 100, 99)
    EloRatingService(world["session"]).rebuild_all()
    atl = [r for r in all_rows(world["session"]) if r.team_id == world["teams"]["ATL"]]
    assert atl[1].rating_before == pytest.approx(elo.season_carryover(atl[0].rating_after))
    assert atl[1].rating_before != pytest.approx(atl[0].rating_after)


def test_rebuild_is_idempotent(world):
    populate_three_seasons(world)
    service = EloRatingService(world["session"])
    service.rebuild_all()
    first = snapshot(world["session"])
    service.rebuild_all()
    second = snapshot(world["session"])
    assert len(first) == len(second) == 24
    assert_snapshots_equal(first, second)


def test_dry_run_writes_nothing(world):
    populate_three_seasons(world)
    summary = EloRatingService(world["session"]).rebuild_all(dry_run=True)
    assert summary.rows_written == 24 and summary.dry_run
    assert all_rows(world["session"]) == []


def test_rebuild_removes_rows_a_replay_no_longer_produces(world):
    populate_three_seasons(world)
    world["session"].add(
        TeamEloRating(team_id=world["teams"]["NJN"], season_id=world["seasons"]["2003-04"], game_id="0020300001")
    )
    world["session"].commit()
    summary = EloRatingService(world["session"]).rebuild_all()
    assert summary.rows_deleted == 1
    assert world["teams"]["NJN"] not in {r.team_id for r in all_rows(world["session"])}


def test_update_new_games_equals_full_rebuild(world):
    schedule = populate_three_seasons(world)
    session = world["session"]

    # Pretend the last 5 games arrive later: hide them, rate the rest, then reveal and update.
    late_ids = [g[0] for g in schedule[7:]]
    hidden = session.exec(select(PlayerGameLog).where(PlayerGameLog.game_id.in_(late_ids))).all()
    stash = [
        dict(
            player_id=r.player_id, team_id=r.team_id, season_id=r.season_id, game_id=r.game_id,
            game_date=r.game_date, matchup=r.matchup, pts=r.pts,
        )
        for r in hidden
    ]
    for row in hidden:
        session.delete(row)
    session.commit()

    service = EloRatingService(session)
    service.rebuild_all()
    assert len(all_rows(session)) == 14

    for values in stash:
        session.add(PlayerGameLog(**values))
    session.commit()
    summary = service.update_new_games()
    assert not summary.rebuilt and summary.games_used == 5
    incremental = snapshot(session)

    for row in all_rows(session):
        session.delete(row)
    session.commit()
    service.rebuild_all()
    assert_snapshots_equal(incremental, snapshot(session))


def test_update_with_nothing_new_changes_nothing(world):
    populate_three_seasons(world)
    service = EloRatingService(world["session"])
    service.rebuild_all()
    before = snapshot(world["session"])
    summary = service.update_new_games()
    assert summary.games_used == 0 and summary.rows_written == 0
    assert_snapshots_equal(before, snapshot(world["session"]))


def test_update_falls_back_to_rebuild_when_a_game_arrives_out_of_order(world):
    add_game(world, "0020300001", date(2003, 11, 1), "2003-04", "ATL", "BOS", 100, 90)
    add_game(world, "0020300003", date(2003, 11, 5), "2003-04", "BOS", "ATL", 105, 100)
    service = EloRatingService(world["session"])
    service.rebuild_all()
    add_game(world, "0020300002", date(2003, 11, 3), "2003-04", "ATL", "BOS", 99, 98)

    summary = service.update_new_games()
    assert summary.rebuilt
    incremental = snapshot(world["session"])
    for row in all_rows(world["session"]):
        world["session"].delete(row)
    world["session"].commit()
    service.rebuild_all()
    assert_snapshots_equal(incremental, snapshot(world["session"]))


def test_current_ratings_apply_carryover_only_for_a_new_season(world):
    add_game(world, "0020300001", date(2004, 4, 1), "2003-04", "ATL", "BOS", 110, 100)
    service = EloRatingService(world["session"])
    service.rebuild_all()
    atl_id = world["teams"]["ATL"]
    raw = service.current_ratings()[atl_id]
    assert raw > 1500
    assert service.current_ratings(for_season_id=world["seasons"]["2003-04"])[atl_id] == pytest.approx(raw)
    assert service.current_ratings(for_season_id=world["seasons"]["2004-05"])[atl_id] == pytest.approx(
        elo.season_carryover(raw)
    )
    assert service.current_ratings(as_of=date(2004, 3, 31)) == {}


def test_predict_uses_ratings_and_registered_sigma(world):
    teams = world["teams"]
    service = EloRatingService(world["session"])
    prediction = service.predict(teams["ATL"], teams["BOS"], ratings={teams["ATL"]: 1600.0, teams["BOS"]: 1500.0})
    assert prediction.p_home == pytest.approx(elo.expected_home_win_prob(1600, 1500))
    assert prediction.expected_margin == pytest.approx(elo.expected_margin(1600, 1500))
    assert prediction.sigma == DEFAULT_SIGMA

    service.register_model_version(sigma=13.5, brier_oos=0.21)
    assert EloRatingService(world["session"]).predict(teams["ATL"], teams["BOS"], ratings={}).sigma == 13.5
    assert EloRatingService(world["session"], sigma=9.0).predict(teams["ATL"], teams["BOS"], ratings={}).sigma == 9.0


def test_evaluate_walk_forward_returns_one_metrics_row_per_season(world):
    populate_three_seasons(world)
    metrics = EloRatingService(world["session"]).evaluate_walk_forward()
    assert [m.season_label for m in metrics] == ["2003-04", "2004-05", "2005-06"]
    assert [m.n_games for m in metrics] == [4, 4, 4]
    for m in metrics:
        assert 0.0 <= m.brier <= 1.0
        assert m.log_loss > 0.0
        assert 0.0 <= m.accuracy <= 1.0
        assert m.mae_margin >= 0.0 and m.residual_std >= 0.0

    only = EloRatingService(world["session"]).evaluate_walk_forward(seasons=["2004-05"])
    assert [m.season_label for m in only] == ["2004-05"]


def test_walk_forward_first_game_uses_initial_ratings(world):
    add_game(world, "0020300001", date(2003, 11, 1), "2003-04", "ATL", "BOS", 110, 100)
    (metrics,) = EloRatingService(world["session"]).evaluate_walk_forward()
    p = elo.expected_home_win_prob(1500, 1500)
    assert metrics.brier == pytest.approx((p - 1.0) ** 2)
    assert metrics.accuracy == 1.0
    assert metrics.mae_margin == pytest.approx(abs(10 - elo.expected_margin(1500, 1500)))


def test_out_of_sample_summary_uses_last_completed_seasons(world):
    populate_three_seasons(world)
    metrics = EloRatingService(world["session"]).evaluate_walk_forward()
    sigma, brier = out_of_sample_summary(metrics, last_n=2)
    assert brier == pytest.approx((metrics[1].brier + metrics[2].brier) / 2)
    assert sigma > 0
    with pytest.raises(ValueError):
        out_of_sample_summary([])


def test_register_model_version_is_idempotent(world):
    session = world["session"]
    service = EloRatingService(session)
    service.register_model_version(
        sigma=12.34567, brier_oos=0.2105678, trained_through=date(2026, 4, 12), seasons_evaluated=["2024-25", "2025-26"]
    )
    service.register_model_version(sigma=13.0, brier_oos=0.2201, trained_through=date(2026, 4, 13))

    rows = session.exec(select(ModelVersion)).all()
    assert len(rows) == 1
    row = rows[0]
    assert (row.name, row.version) == ("elo_538", "1.1")
    assert float(row.brier_oos) == pytest.approx(0.2201)
    assert row.params["sigma"] == 13.0
    assert row.params["trained_through"] == "2026-04-13"
    for key, value in (("K", 20.0), ("home_advantage", 60.0), ("carryover", 0.75), ("mean_rating", 1505.0),
                       ("elo_per_point", 28.0)):
        assert row.params[key] == value


def test_replay_games_is_pure_and_continues_from_state(world):
    populate_three_seasons(world)
    games = EloRatingService(world["session"]).load_games()
    full, full_state = replay_games(games)
    head, head_state = replay_games(games[:5])
    tail, tail_state = replay_games(games[5:], head_state)
    assert [r.home_after for r in full] == pytest.approx([r.home_after for r in head + tail])
    assert {k: v[0] for k, v in full_state.items()} == pytest.approx({k: v[0] for k, v in tail_state.items()})
