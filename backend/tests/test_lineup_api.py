from fastapi.testclient import TestClient
from sqlmodel import Session, select
from app.models import Player, Team, Season, PlayerSeasonStats, PlayerAdvancedStats


def test_lineup_endpoints(client: TestClient, db_session: Session):
    session = db_session

    # Fetch or create seasons
    s1 = session.exec(select(Season).where(Season.season_label == "2023-24-LIN")).first()
    if not s1:
        s1 = Season(season_label="2023-24-LIN", is_active=True)
        session.add(s1)
        session.commit()
        session.refresh(s1)

    team1 = session.exec(select(Team).where(Team.abbreviation == "TL1")).first()
    if not team1:
        team1 = Team(abbreviation="TL1", full_name="Team Lineup 1", city="Los Angeles", conference="West", division="Pacific")
        session.add(team1)
        session.commit()
        session.refresh(team1)

    # Create 5 players for a full test lineup
    players_data = [
        ("Test PG Lin", "G", 190, 85, 20.0, 4.0, 9.0, 1.5, 0.2, 0.45, 0.38, 0.88, 6),
        ("Test SG Lin", "G", 198, 95, 26.0, 5.0, 4.0, 1.8, 0.5, 0.48, 0.40, 0.85, 5),
        ("Test SF Lin", "F", 203, 105, 24.0, 7.0, 6.0, 1.2, 0.8, 0.50, 0.36, 0.75, 4),
        ("Test PF Lin", "F", 208, 110, 18.0, 9.0, 3.0, 0.8, 1.4, 0.52, 0.33, 0.80, 0),
        ("Test C Lin", "C", 216, 120, 16.0, 12.0, 2.0, 0.5, 2.2, 0.60, 0.10, 0.70, 2),
    ]

    slots = []
    positions = ["PG", "SG", "SF", "PF", "C"]
    for i, (name, pos, h, w, pts, reb, ast, stl, blk, fg, fg3, ft, clus) in enumerate(players_data):
        p = session.exec(select(Player).where(Player.full_name == name)).first()
        if not p:
            p = Player(full_name=name, position=pos, height_cm=h, weight_kg=w)
            session.add(p)
            session.commit()
            session.refresh(p)

        stat = session.exec(select(PlayerSeasonStats).where(PlayerSeasonStats.player_id == p.id, PlayerSeasonStats.season_id == s1.id)).first()
        if not stat:
            stat = PlayerSeasonStats(
                player_id=p.id,
                team_id=team1.id,
                season_id=s1.id,
                gp=70,
                pts=pts * 70,
                reb=reb * 70,
                ast=ast * 70,
                stl=stl * 70,
                blk=blk * 70,
                fg_pct=fg,
                fg3_pct=fg3,
                ft_pct=ft,
                min=2400.0,
                cluster_id=clus,
            )
            session.add(stat)
            session.commit()

        adv = session.exec(select(PlayerAdvancedStats).where(PlayerAdvancedStats.player_id == p.id, PlayerAdvancedStats.season_id == s1.id)).first()
        if not adv:
            adv = PlayerAdvancedStats(
                player_id=p.id,
                season_id=s1.id,
                per=22.0,
                bpm=4.5,
                ts_pct=0.58,
                usg_pct=0.25,
            )
            session.add(adv)
            session.commit()

        slots.append({"position": positions[i], "player_id": p.id, "season_id": s1.id})

    # 1. Test GET /api/v1/lineup/presets
    resp_presets = client.get("/api/v1/lineup/presets")
    assert resp_presets.status_code == 200
    presets_data = resp_presets.json()
    assert len(presets_data) >= 5
    assert any(p["id"] == "bulls_1996" for p in presets_data)
    assert any(p["id"] == "warriors_2017" for p in presets_data)

    # 2. Test POST /api/v1/lineup/evaluate
    eval_payload = {
        "team_name": "Test Dream Team",
        "slots": slots,
    }
    resp_eval = client.post("/api/v1/lineup/evaluate", json=eval_payload)
    if resp_eval.status_code != 200:
        print("EVAL FAILED BODY:", resp_eval.text)
    assert resp_eval.status_code == 200
    eval_data = resp_eval.json()
    assert eval_data["team_name"] == "Test Dream Team"
    assert len(eval_data["slots"]) == 5
    assert "metrics" in eval_data
    assert eval_data["metrics"]["ortg"] > 0
    assert eval_data["metrics"]["chemistry_score"] >= 20

    # 3. Test POST /api/v1/lineup/simulate
    sim_payload = {
        "team1": {"team_name": "Team Red", "slots": slots},
        "team2": {"team_name": "Team Blue", "slots": slots},
    }
    resp_sim = client.post("/api/v1/lineup/simulate", json=sim_payload)
    assert resp_sim.status_code == 200
    sim_data = resp_sim.json()
    assert sim_data["team1_name"] == "Team Red"
    assert sim_data["team2_name"] == "Team Blue"
    assert sim_data["team1_score"] > 50
    assert sim_data["team2_score"] > 50
    assert len(sim_data["team1_boxscore"]) == 5
    assert len(sim_data["team2_boxscore"]) == 5
    assert len(sim_data["quarter_scores_t1"]) == 4
    assert len(sim_data["quarter_scores_t2"]) == 4
    assert sim_data["game_mvp_name"] != ""
