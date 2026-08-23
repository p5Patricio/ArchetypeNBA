from fastapi.testclient import TestClient
from sqlmodel import Session, select
from app.models import Player, Team, Season, PlayerSeasonStats
from app.services.training import TrainingService


def test_training_service_and_endpoints(client: TestClient, db_session: Session):
    session = db_session

    # Create season
    season = session.exec(select(Season).where(Season.season_label == "2023-24-TR")).first()
    if not season:
        season = Season(season_label="2023-24-TR", is_active=True)
        session.add(season)
        session.commit()
        session.refresh(season)

    # Create team
    team = session.exec(select(Team).where(Team.abbreviation == "GSW_TR")).first()
    if not team:
        team = Team(abbreviation="GSW_TR", full_name="Golden State Warriors Test", city="San Francisco", conference="West", division="Pacific")
        session.add(team)
        session.commit()
        session.refresh(team)

    # Create target player (Curry - Guard)
    p_curry = session.exec(select(Player).where(Player.full_name == "Stephen Curry Test")).first()
    if not p_curry:
        p_curry = Player(full_name="Stephen Curry Test", position="PG", height_cm=188, weight_kg=84)
        session.add(p_curry)
        session.commit()
        session.refresh(p_curry)

    # Create cohort peer (Guard)
    p_peer = session.exec(select(Player).where(Player.full_name == "Luka Doncic Test")).first()
    if not p_peer:
        p_peer = Player(full_name="Luka Doncic Test", position="PG", height_cm=201, weight_kg=104)
        session.add(p_peer)
        session.commit()
        session.refresh(p_peer)

    # Create stats
    stat_curry = PlayerSeasonStats(
        player_id=p_curry.id,
        team_id=team.id,
        season_id=season.id,
        gp=74,
        pts=1956.0,
        reb=330.0,
        ast=379.0,
        stl=55.0,
        blk=25.0,
        tov=206.0,
        pf=120.0,
        fg3m=357.0,
        fg_pct=0.450,
        fg3_pct=0.408,
        ft_pct=0.923,
        min=2421.0,
        cluster_id=5,
    )
    session.add(stat_curry)

    stat_peer = PlayerSeasonStats(
        player_id=p_peer.id,
        team_id=team.id,
        season_id=season.id,
        gp=70,
        pts=2370.0,
        reb=647.0,
        ast=686.0,
        stl=99.0,
        blk=38.0,
        tov=282.0,
        pf=150.0,
        fg3m=284.0,
        fg_pct=0.487,
        fg3_pct=0.382,
        ft_pct=0.786,
        min=2624.0,
        cluster_id=4,
    )
    session.add(stat_peer)
    session.commit()

    # 1. Test TrainingService directly
    service = TrainingService(session)
    res = service.get_training_analysis(player_name="Stephen Curry Test", season_id=season.id)

    assert res.player_name == "Stephen Curry Test"
    assert res.position == "PG"
    assert res.position_group == "Guard"
    assert res.role_fulfillment.overall_score >= 50.0
    assert len(res.stat_gaps) > 0
    assert len(res.training_regimes) == 4
    assert len(res.radar_labels) == 6
    assert len(res.radar_player_values) == 6
    assert len(res.radar_benchmark_values) == 6
    assert len(res.radar_projected_values) == 6

    # 2. Test GET /api/v1/training/analyze API
    response = client.get(f"/api/v1/training/analyze?player_name=Stephen+Curry+Test&season_id={season.id}")
    assert response.status_code == 200
    data = response.json()
    assert data["player_name"] == "Stephen Curry Test"
    assert data["role_fulfillment"]["letter_grade"] in ["A+", "A", "B+", "B", "C+", "C", "D"]
    assert "current_stats" in data
    assert "positional_benchmark" in data
    assert "projected_stats" in data
    assert "recommended_drills" in data

    # 3. Test GET /api/v1/training/drills catalog endpoint
    drills_resp = client.get("/api/v1/training/drills")
    assert drills_resp.status_code == 200
    drills_list = drills_resp.json()
    assert len(drills_list) >= 8
