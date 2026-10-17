from fastapi.testclient import TestClient


def test_health_endpoint(client: TestClient):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"


def test_root_endpoint(client: TestClient):
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert "NBA Analytics Platform API" in data["message"]


def test_players_empty(client: TestClient):
    response = client.get("/api/v1/players")
    assert response.status_code == 200
    assert response.json() == []


def test_teams_empty(client: TestClient):
    response = client.get("/api/v1/teams")
    assert response.status_code == 200
    assert response.json() == []


def test_seasons_hide_empty_inactive_seasons_but_keep_the_active_one(client: TestClient, db_session):
    from app.models import PlayerSeasonStats, Season

    active = Season(season_label="2025-26", is_active=True)
    played = Season(season_label="2024-25")
    upcoming = Season(season_label="2026-27")  # created ahead of time by odds ingestion
    db_session.add_all([active, played, upcoming])
    db_session.commit()
    db_session.add(PlayerSeasonStats(player_id=1, team_id=1, season_id=played.id))
    db_session.commit()

    data = client.get("/api/v1/seasons").json()

    assert [(s["season_label"], s["is_active"], s["players_count"]) for s in data] == [
        ("2025-26", True, 0),
        ("2024-25", False, 1),
    ]
