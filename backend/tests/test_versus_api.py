from fastapi.testclient import TestClient
from sqlmodel import Session, select
from app.models import Player, Team, Season, PlayerSeasonStats, PlayerAdvancedStats


def test_versus_endpoints(client: TestClient, db_session: Session):
    session = db_session

    # Fetch or create seasons
    s1 = session.exec(select(Season).where(Season.season_label == "2023-24-V1")).first()
    if not s1:
        s1 = Season(season_label="2023-24-V1", is_active=True)
        session.add(s1)
        session.commit()
        session.refresh(s1)

    s2 = session.exec(select(Season).where(Season.season_label == "1995-96-V1")).first()
    if not s2:
        s2 = Season(season_label="1995-96-V1", is_active=False)
        session.add(s2)
        session.commit()
        session.refresh(s2)

    team1 = session.exec(select(Team).where(Team.abbreviation == "VL1")).first()
    if not team1:
        team1 = Team(abbreviation="VL1", full_name="Versus Team 1", city="Los Angeles", conference="West", division="Pacific")
        session.add(team1)
        session.commit()
        session.refresh(team1)

    team2 = session.exec(select(Team).where(Team.abbreviation == "VC1")).first()
    if not team2:
        team2 = Team(abbreviation="VC1", full_name="Versus Team 2", city="Chicago", conference="East", division="Central")
        session.add(team2)
        session.commit()
        session.refresh(team2)

    p1 = session.exec(select(Player).where(Player.full_name == "LeBron James")).first()
    if not p1:
        p1 = Player(full_name="LeBron James", position="F", height_cm=206, weight_kg=113)
        session.add(p1)
        session.commit()
        session.refresh(p1)

    p2 = session.exec(select(Player).where(Player.full_name == "Michael Jordan")).first()
    if not p2:
        p2 = Player(full_name="Michael Jordan", position="G", height_cm=198, weight_kg=98)
        session.add(p2)
        session.commit()
        session.refresh(p2)

    stat1 = session.exec(select(PlayerSeasonStats).where(PlayerSeasonStats.player_id == p1.id, PlayerSeasonStats.season_id == s1.id)).first()
    if not stat1:
        stat1 = PlayerSeasonStats(player_id=p1.id, team_id=team1.id, season_id=s1.id, gp=70, pts=1800.0, reb=500.0, ast=550.0, stl=80.0, blk=40.0, fg_pct=0.54, fg3_pct=0.41, ft_pct=0.75, min=2400.0)
        session.add(stat1)
        session.commit()

    stat2 = session.exec(select(PlayerSeasonStats).where(PlayerSeasonStats.player_id == p2.id, PlayerSeasonStats.season_id == s2.id)).first()
    if not stat2:
        stat2 = PlayerSeasonStats(player_id=p2.id, team_id=team2.id, season_id=s2.id, gp=82, pts=2600.0, reb=500.0, ast=450.0, stl=180.0, blk=60.0, fg_pct=0.53, fg3_pct=0.35, ft_pct=0.85, min=3000.0)
        session.add(stat2)
        session.commit()

    # Test /api/v1/versus/players
    resp = client.get("/api/v1/versus/players")
    assert resp.status_code == 200
    players_data = resp.json()
    assert len(players_data) >= 2
    names = [p["player_name"] for p in players_data]
    assert "LeBron James" in names
    assert "Michael Jordan" in names

    # Test /api/v1/versus/matchup
    resp_match = client.get(f"/api/v1/versus/matchup?player1_id={p1.id}&player2_id={p2.id}")
    assert resp_match.status_code == 200
    data = resp_match.json()
    assert data["player1"]["player_name"] == "LeBron James"
    assert data["player2"]["player_name"] == "Michael Jordan"
    assert "simulation" in data
    assert "p1_win_prob" in data["simulation"]
    assert "p2_win_prob" in data["simulation"]
    assert len(data["simulation"]["dimensions"]) == 7
    assert len(data["stat_comparisons"]) >= 10
    assert len(data["accolades_comparisons"]) >= 5
