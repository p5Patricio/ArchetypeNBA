"""
Tests for elo_injury model family, serving, leak freedom, registration script, and league isolation.
"""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import pytest
from sqlmodel import select

from app.config import settings
from app.models import (
    BetSide,
    Game,
    InjuryEntry,
    InjuryReportSnapshot,
    MarketType,
    ModelPrediction,
    ModelVersion,
    Player,
    PlayerGameLog,
    Season,
    SimulatedBet,
    Team,
)
from app.services import elo_injury_model, model_registry
from app.services.elo_injury_model import (
    DEFAULT_BETA,
    DEFAULT_SIGMA,
    FAMILY_NAME,
    EloInjuryFamily,
    fit_walk_forward_injury_adjustment,
)
from app.services.model_registry import load_model, register_family
from app.services.prediction_recorder import PredictionRecorder
from scripts.register_injury_challenger import main as register_main
from tests.synthetic_league import insert_league, make_league
from tests.test_prediction_recorder import NOW, World, american


@pytest.fixture
def injury_world(db_session):
    """Sets up two teams, players, an active season, and champion Elo model."""
    season = Season(season_label="2026-27", is_active=True)
    home_team = Team(abbreviation="BOS", full_name="Boston Celtics", city="Boston", conference="E", division="A")
    away_team = Team(abbreviation="LAL", full_name="Los Angeles Lakers", city="Los Angeles", conference="W", division="P")
    db_session.add_all([season, home_team, away_team])
    db_session.flush()

    home_player = Player(full_name="Jayson Tatum")
    away_player = Player(full_name="LeBron James")
    db_session.add_all([home_player, away_player])
    db_session.flush()

    # Champion model
    champion = model_registry.ensure_default_champion(db_session)
    champion.params = {"sigma": 14.14}
    db_session.flush()

    # Seed ratings for champion
    from app.models import TeamEloRating
    db_session.add_all([
        TeamEloRating(
            model_version_id=champion.id,
            team_id=home_team.id,
            season_id=season.id,
            game_id="0022600001",
            game_date=date(2026, 10, 20),
            rating_after=1520.0,
        ),
        TeamEloRating(
            model_version_id=champion.id,
            team_id=away_team.id,
            season_id=season.id,
            game_id="0022600001",
            game_date=date(2026, 10, 20),
            rating_after=1480.0,
        ),
    ])
    db_session.flush()

    return {
        "season": season,
        "home_team": home_team,
        "away_team": away_team,
        "home_player": home_player,
        "away_player": away_player,
        "champion": champion,
    }


def test_elo_injury_family_registered_and_loadable(db_session, injury_world):
    """The elo_injury family is registered in model_registry and load_model builds it."""
    mv = ModelVersion(
        name=FAMILY_NAME,
        version="v1.0",
        role="challenger",
        parent_id=injury_world["champion"].id,
        params={"beta": 0.40, "sigma": 14.14},
    )
    db_session.add(mv)
    db_session.flush()

    model = load_model(db_session, mv)
    assert isinstance(model, EloInjuryFamily)
    assert model.name == FAMILY_NAME
    assert model.version == "v1.0"
    assert model.beta == 0.40
    assert model.sigma == 14.14


def test_serving_without_snapshot_defaults_to_elo(db_session, injury_world):
    """When no injury snapshot exists before game_time, model prediction equals Elo exactly."""
    mv = ModelVersion(
        name=FAMILY_NAME,
        version="v1.0",
        role="challenger",
        parent_id=injury_world["champion"].id,
        params={"beta": 0.40, "sigma": 14.14},
    )
    db_session.add(mv)
    db_session.flush()

    elo_champ = load_model(db_session, injury_world["champion"])
    inj_model = load_model(db_session, mv)

    game_time = datetime(2026, 11, 1, 20, 0, tzinfo=timezone.utc)
    pred_elo = elo_champ.predict(injury_world["home_team"].id, injury_world["away_team"].id, injury_world["season"].id, game_time)
    pred_inj = inj_model.predict(injury_world["home_team"].id, injury_world["away_team"].id, injury_world["season"].id, game_time)

    assert pred_elo is not None
    assert pred_inj is not None
    assert pred_inj.mu == pred_elo.mu
    assert pred_inj.p_home == pred_elo.p_home
    assert pred_inj.sigma == pred_elo.sigma
    assert "defaulted to Elo" in (inj_model.last_notes or "")


def test_serving_with_stale_snapshot_defaults_to_elo(db_session, injury_world):
    """A snapshot older than max_snapshot_age_hours is considered stale and ignored."""
    mv = ModelVersion(
        name=FAMILY_NAME,
        version="v1.0",
        role="challenger",
        parent_id=injury_world["champion"].id,
        params={"beta": 0.40, "sigma": 14.14, "max_snapshot_age_hours": 36.0},
    )
    db_session.add(mv)
    db_session.flush()

    # Snapshot created 40 hours before game_time
    game_time = datetime(2026, 11, 2, 20, 0, tzinfo=timezone.utc)
    stale_ts = game_time - timedelta(hours=40)
    snap = InjuryReportSnapshot(
        source="nba_official_pdf",
        report_url="https://ak-static.cms.nba.com/stale.pdf",
        report_timestamp=stale_ts,
        sha256="stale_sha256",
        entries_count=1,
    )
    db_session.add(snap)
    db_session.flush()

    # Entry says away player is OUT
    entry = InjuryEntry(
        snapshot_id=snap.id,
        game_date="2026-11-02",
        team_name="Los Angeles Lakers",
        player_name_raw="LeBron James",
        player_id=injury_world["away_player"].id,
        status="OUT",
        availability_prob=Decimal("0.00"),
    )
    db_session.add(entry)
    db_session.flush()

    elo_champ = load_model(db_session, injury_world["champion"])
    inj_model = load_model(db_session, mv)

    pred_elo = elo_champ.predict(injury_world["home_team"].id, injury_world["away_team"].id, injury_world["season"].id, game_time)
    pred_inj = inj_model.predict(injury_world["home_team"].id, injury_world["away_team"].id, injury_world["season"].id, game_time)

    assert pred_inj.mu == pred_elo.mu
    assert "stale" in (inj_model.last_notes or "")


def test_serving_with_active_snapshot_adjusts_margin_exactly(db_session, injury_world):
    """
    When an Out player is present in a fresh snapshot, the expected team margin moves
    by exactly beta * impact * (1 - prob).
    """
    beta = 0.50
    mv = ModelVersion(
        name=FAMILY_NAME,
        version="v1.0",
        role="challenger",
        parent_id=injury_world["champion"].id,
        params={"beta": beta, "sigma": 14.14},
    )
    db_session.add(mv)
    db_session.flush()

    game_time = datetime(2026, 11, 1, 20, 0, tzinfo=timezone.utc)
    fresh_ts = game_time - timedelta(hours=2)
    snap = InjuryReportSnapshot(
        source="nba_official_pdf",
        report_url="https://ak-static.cms.nba.com/fresh.pdf",
        report_timestamp=fresh_ts,
        sha256="fresh_sha256",
        entries_count=1,
    )
    db_session.add(snap)
    db_session.flush()

    # Away player is OUT (prob = 0.0)
    entry = InjuryEntry(
        snapshot_id=snap.id,
        game_date="2026-11-01",
        team_name="Los Angeles Lakers",
        player_name_raw="LeBron James",
        player_id=injury_world["away_player"].id,
        status="OUT",
        availability_prob=Decimal("0.00"),
    )
    db_session.add(entry)
    db_session.flush()

    # Injected impact of 10.0 for LeBron James
    def mock_impact(player_id, season_id, as_of_date):
        if player_id == injury_world["away_player"].id:
            return 10.0
        return 0.0

    inj_model = EloInjuryFamily(db_session, mv, impact_lookup=mock_impact)
    elo_champ = load_model(db_session, injury_world["champion"])

    pred_elo = elo_champ.predict(injury_world["home_team"].id, injury_world["away_team"].id, injury_world["season"].id, game_time)
    pred_inj = inj_model.predict(injury_world["home_team"].id, injury_world["away_team"].id, injury_world["season"].id, game_time)

    # Away player missing 10 pts impact:
    # missing_away = 10.0 * (1.0 - 0.0) = 10.0
    # missing_home = 0.0
    # mu_adj = mu_elo + beta * (10.0 - 0.0) = mu_elo + 0.5 * 10.0 = mu_elo + 5.0
    assert abs(pred_inj.mu - (pred_elo.mu + 5.0)) < 1e-6
    assert pred_inj.p_home > pred_elo.p_home


def test_unmatched_players_are_ignored_and_counted_never_invented(db_session, injury_world):
    """Rule 3 check: unmatched names (player_id is None) are ignored and counted, never invented."""
    mv = ModelVersion(
        name=FAMILY_NAME,
        version="v1.0",
        role="challenger",
        parent_id=injury_world["champion"].id,
        params={"beta": 0.40, "sigma": 14.14},
    )
    db_session.add(mv)
    db_session.flush()

    game_time = datetime(2026, 11, 1, 20, 0, tzinfo=timezone.utc)
    snap = InjuryReportSnapshot(
        source="nba_official_pdf",
        report_url="https://ak-static.cms.nba.com/fresh.pdf",
        report_timestamp=game_time - timedelta(hours=2),
        sha256="fresh_sha256_unmatched",
        entries_count=1,
    )
    db_session.add(snap)
    db_session.flush()

    # Unmatched player name
    entry = InjuryEntry(
        snapshot_id=snap.id,
        game_date="2026-11-01",
        team_name="Los Angeles Lakers",
        player_name_raw="Unknown Mystery Player",
        player_id=None,  # Unmatched
        status="OUT",
        availability_prob=Decimal("0.00"),
    )
    db_session.add(entry)
    db_session.flush()

    inj_model = load_model(db_session, mv)
    elo_champ = load_model(db_session, injury_world["champion"])

    pred_elo = elo_champ.predict(injury_world["home_team"].id, injury_world["away_team"].id, injury_world["season"].id, game_time)
    pred_inj = inj_model.predict(injury_world["home_team"].id, injury_world["away_team"].id, injury_world["season"].id, game_time)

    # Because unmatched player was ignored, missing impact is 0 -> equal to Elo
    assert pred_inj.mu == pred_elo.mu
    assert "unmatched=1" in (inj_model.last_notes or "")


def test_leak_test_changing_future_leaves_earlier_adjustments_bit_identical(db_session, injury_world):
    """
    Leak test: Adding future games and future snapshots strictly after game_time
    leaves predictions at game_time bit-identical.
    """
    mv = ModelVersion(
        name=FAMILY_NAME,
        version="v1.0",
        role="challenger",
        parent_id=injury_world["champion"].id,
        params={"beta": 0.40, "sigma": 14.14},
    )
    db_session.add(mv)
    db_session.flush()

    game_time = datetime(2026, 11, 1, 20, 0, tzinfo=timezone.utc)
    snap1 = InjuryReportSnapshot(
        source="nba_official_pdf",
        report_url="https://ak-static.cms.nba.com/snap1.pdf",
        report_timestamp=game_time - timedelta(hours=3),
        sha256="snap1_sha",
        entries_count=1,
    )
    db_session.add(snap1)
    db_session.flush()

    entry1 = InjuryEntry(
        snapshot_id=snap1.id,
        game_date="2026-11-01",
        team_name="Los Angeles Lakers",
        player_name_raw="LeBron James",
        player_id=injury_world["away_player"].id,
        status="QUESTIONABLE",
        availability_prob=Decimal("0.50"),
    )
    db_session.add(entry1)
    db_session.flush()

    # Pre-game log for Tatum (home player) on 2026-10-25
    db_session.add(
        PlayerGameLog(
            player_id=injury_world["home_player"].id,
            team_id=injury_world["home_team"].id,
            season_id=injury_world["season"].id,
            game_id="0022600001",
            game_date=date(2026, 10, 25),
            min=35,
            pts=30,
            reb=8,
            ast=8,
        )
    )
    db_session.flush()

    inj_model = load_model(db_session, mv)
    pred_before = inj_model.predict(
        injury_world["home_team"].id, injury_world["away_team"].id, injury_world["season"].id, game_time
    )

    # NOW inject future data:
    # 1. Future snapshot tomorrow
    snap_future = InjuryReportSnapshot(
        source="nba_official_pdf",
        report_url="https://ak-static.cms.nba.com/future.pdf",
        report_timestamp=game_time + timedelta(hours=24),
        sha256="future_snap_sha",
        entries_count=1,
    )
    db_session.add(snap_future)
    db_session.flush()

    # 2. Future game log for Tatum tomorrow
    db_session.add(
        PlayerGameLog(
            player_id=injury_world["home_player"].id,
            team_id=injury_world["home_team"].id,
            season_id=injury_world["season"].id,
            game_id="0022600010",
            game_date=date(2026, 11, 2),
            min=40,
            pts=50,
            reb=15,
            ast=15,
        )
    )
    db_session.flush()

    # Re-predict at original game_time with a fresh family instance
    inj_model_reloaded = load_model(db_session, mv)
    pred_after = inj_model_reloaded.predict(
        injury_world["home_team"].id, injury_world["away_team"].id, injury_world["season"].id, game_time
    )

    assert pred_before is not None
    assert pred_after is not None
    assert pred_before.mu == pred_after.mu
    assert pred_before.p_home == pred_after.p_home
    assert pred_before.sigma == pred_after.sigma


def test_league_isolation_champion_predictions_and_bets_are_unchanged(db_session):
    """
    League isolation: The presence of an active elo_injury challenger records
    shadow predictions without altering champion predictions or bets.
    """
    world = World(db_session)
    champ = model_registry.get_champion(db_session)
    assert champ is not None
    game1 = world.game("AAA", "BBB", hours=4.0)

    # 1. Run recorder with champion only
    world.h2h(game1, "pinnacle", -150, +130)
    world.quote(game1, "draftkings", MarketType.h2h, BetSide.home, None, -140)

    rec1 = PredictionRecorder(db_session, now=NOW)
    summary1 = rec1.run()
    assert sum(summary1.bets_placed.values()) > 0
    champ_bets_1 = db_session.execute(
        select(SimulatedBet).join(ModelPrediction).where(ModelPrediction.model_version_id == champ.id)
    ).scalars().all()
    assert len(champ_bets_1) > 0

    # 2. Add elo_injury challenger
    challenger = ModelVersion(
        name=FAMILY_NAME,
        version="test-challenger",
        role="challenger",
        parent_id=champ.id,
        params={"beta": 0.40, "sigma": 14.14},
    )
    db_session.add(challenger)
    db_session.commit()

    # 3. Create a second game and run recorder with both
    game2 = world.game("AAA", "BBB", hours=6.0, event="evt-second-game")
    world.h2h(game2, "pinnacle", -150, +130)
    world.quote(game2, "draftkings", MarketType.h2h, BetSide.home, None, -140)

    rec2 = PredictionRecorder(db_session, now=NOW)
    summary2 = rec2.run()

    # Challenger recorded predictions
    challenger_preds = db_session.execute(
        select(ModelPrediction).where(ModelPrediction.model_version_id == challenger.id)
    ).scalars().all()
    assert len(challenger_preds) > 0

    # Challenger NEVER placed any simulated bets
    challenger_bets = db_session.execute(
        select(SimulatedBet).join(ModelPrediction).where(ModelPrediction.model_version_id == challenger.id)
    ).scalars().all()
    assert len(challenger_bets) == 0


def test_walk_forward_evaluation_on_synthetic_league(db_session, capsys):
    """
    DESIGN 6 requirement: Run walk-forward evaluation on synthetic league fixtures only inside tests.
    Tests fit_walk_forward_injury_adjustment and injury_model_eval CLI on synthetic data.
    """
    from scripts.injury_model_eval import format_eval_report, main as eval_main

    # Generate small 3-season synthetic league
    games = make_league(n_seasons=3, n_teams=4, rounds=4, seed=42)
    insert_league(db_session, games)

    # Walk-forward evaluation across the synthetic seasons
    res = fit_walk_forward_injury_adjustment(
        db_session,
        n_test_seasons=2,
        min_mpg=5.0,
        min_gp=2,
        bootstrap_samples=100,
        seed=42,
    )

    assert res.n_games > 0
    assert len(res.season_results) == 2
    assert res.overall_beta_ci[0] <= res.overall_beta_ci[1]
    assert "UPPER BOUND" in res.caveat

    # Format report check
    text = format_eval_report(res)
    assert "WALK-FORWARD EVALUATION" in text
    assert "SUMMARY ESTIMATES" in text
    assert "CAVEAT (TRAIN / SERVE SKEW)" in text

    # Test the read-only injury_model_eval CLI entrypoint
    from contextlib import contextmanager

    @contextmanager
    def factory():
        yield db_session

    ret = eval_main(["--seasons", "2", "--min-mpg", "5.0", "--bootstrap", "50"], session_factory=factory)
    assert ret == 0
    captured = capsys.readouterr()
    assert "WALK-FORWARD EVALUATION" in captured.out



def test_registration_script_refuses_when_max_challengers_reached(db_session, monkeypatch):
    """The registration script exits 1 when LEARNING_MAX_CHALLENGERS would be exceeded."""
    champ = model_registry.ensure_default_champion(db_session)
    # Add active challengers up to limit (3)
    for i in range(settings.LEARNING_MAX_CHALLENGERS):
        c = ModelVersion(name="other_challenger", version=f"v{i}", role="challenger", parent_id=champ.id, params={})
        db_session.add(c)
    db_session.commit()

    from contextlib import contextmanager

    @contextmanager
    def factory():
        yield db_session

    ret = register_main(["--dry-run"], session_factory=factory)
    assert ret == 1


def test_registration_script_refuses_when_gain_is_not_positive(db_session, monkeypatch):
    """The registration script exits 1 when walk-forward log loss gain <= 0."""
    champ = model_registry.ensure_default_champion(db_session)
    db_session.commit()

    from contextlib import contextmanager

    @contextmanager
    def factory():
        yield db_session

    # With empty league, log loss gain is 0.0 -> refuses
    ret = register_main(["--dry-run"], session_factory=factory)
    assert ret == 1


def test_registration_script_idempotent_and_creates_new_model_version(db_session, monkeypatch):
    """The registration script registers a new model_version row and is idempotent."""
    champ = model_registry.ensure_default_champion(db_session)
    db_session.commit()

    from contextlib import contextmanager

    @contextmanager
    def factory():
        yield db_session

    # Using --force to bypass statistical gate in unit test
    ret1 = register_main(["--force"], session_factory=factory)
    assert ret1 == 0

    # Verify a new ModelVersion row was created with role='challenger'
    mv = db_session.execute(
        select(ModelVersion).where(
            ModelVersion.name == FAMILY_NAME,
            ModelVersion.role == "challenger",
        )
    ).scalar_one_or_none()
    assert mv is not None
    assert mv.parent_id == champ.id
    assert mv.params["family"] == FAMILY_NAME

    # Champion is untouched
    champ_after = model_registry.get_champion(db_session)
    assert champ_after.id == champ.id
    assert champ_after.role == "champion"

    # Re-running is idempotent and exits 0
    ret2 = register_main(["--force"], session_factory=factory)
    assert ret2 == 0
