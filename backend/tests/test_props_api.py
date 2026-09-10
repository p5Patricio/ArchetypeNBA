import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_get_today_props_api():
    response = client.get("/api/v1/props/today")
    assert response.status_code == 200
    data = response.json()

    assert "date" in data
    assert "ai_engine" in data
    assert "odds_source" in data
    assert "slate_summary" in data
    assert "items" in data
    assert isinstance(data["items"], list)
    assert len(data["items"]) > 0

    first_item = data["items"][0]
    assert "player_name" in first_item
    assert "stat_type" in first_item
    assert "line" in first_item
    assert "prob_over" in first_item
    assert "edge_pct" in first_item
    assert "recommendation" in first_item


def test_get_today_props_api_filter():
    response = client.get("/api/v1/props/today?stat_type=PTS")
    assert response.status_code == 200
    data = response.json()
    for item in data["items"]:
        assert item["stat_type"] == "PTS"
