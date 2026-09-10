import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_get_parallel_shot_zones_default():
    response = client.get("/api/v1/shot-zones/parallel?season=2023-24")
    assert response.status_code == 200
    data = response.json()
    assert data["season"] == "2023-24"
    assert data["total_players"] >= 290
    assert "league_averages" in data
    assert "paint" in data["league_averages"]
    assert "mid" in data["league_averages"]
    assert "ft" in data["league_averages"]
    assert "three" in data["league_averages"]
    assert len(data["players"]) >= 290

    # Verify Steph Curry stats
    curry = next((p for p in data["players"] if p["name"] == "Stephen Curry"), None)
    assert curry is not None
    assert curry["zones"]["three"]["rank_score"] == 1
    assert curry["zones"]["three"]["pctile_score"] == 100.0

    # Verify Giannis Antetokounmpo stats
    giannis = next((p for p in data["players"] if p["name"] == "Giannis Antetokounmpo"), None)
    assert giannis is not None
    assert giannis["zones"]["paint"]["rank_score"] == 1
    assert giannis["zones"]["paint"]["pctile_score"] == 100.0


def test_get_parallel_shot_zones_filter_players():
    # Filter for Curry (201939) and Giannis (203507)
    response = client.get("/api/v1/shot-zones/parallel?season=2023-24&player_ids=201939,203507")
    assert response.status_code == 200
    data = response.json()
    assert len(data["players"]) == 2
    names = {p["name"] for p in data["players"]}
    assert "Stephen Curry" in names
    assert "Giannis Antetokounmpo" in names


def test_get_shot_zones_presets():
    response = client.get("/api/v1/shot-zones/presets")
    assert response.status_code == 200
    presets = response.json()
    assert len(presets) >= 4
    preset_ids = [p["id"] for p in presets]
    assert "curry_vs_giannis" in preset_ids
    assert "elite_all_zones" in preset_ids
