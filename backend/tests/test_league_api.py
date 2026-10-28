"""
Tests for the Model League API (GET /api/v1/league) and its in-memory TTL cache.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.api.v1 import league as league_module
from app.api.v1.league import league_cache
from app.models import ModelVersion
from sqlmodel import select
from tests.test_model_evaluation import NOW, SIGMA, League, simulate


@pytest.fixture(autouse=True)
def reset_cache():
    """Ensure cache is clean before and after each test."""
    league_cache.clear()
    original_clock = league_cache._clock
    yield
    league_cache.clear()
    league_cache._clock = original_clock


def test_empty_database_returns_200_with_empty_structure(client: TestClient):
    """An empty database returns 200 OK with a clear empty structure."""
    response = client.get("/api/v1/league")
    assert response.status_code == 200
    data = response.json()

    assert data["champion"] is None
    assert data["challengers"] == []
    assert data["changes"] == []
    assert data["last_proposal"] is None
    assert data["last_proposal_summary"] is None
    assert data["min_games"] == 150
    assert "now" in data


def test_populated_league_returns_full_structure(client: TestClient, db_session):
    """A populated league returns champion, challengers, gains, and gate status."""
    league = League(db_session)
    win, margin, mu_champion, mu_challenger = simulate(12, 3, 6.0, 5.0)
    league.populate(win, margin, mu_champion, mu_challenger, days=5)

    response = client.get("/api/v1/league")
    assert response.status_code == 200
    data = response.json()

    # Champion checks
    assert data["champion"] is not None
    assert data["champion"]["label"] == "elo_538 1.1"
    assert data["champion"]["role"] == "champion"
    assert data["champion"]["predictions"] == 12

    # Challenger checks
    assert len(data["challengers"]) == 1
    challenger = data["challengers"][0]
    assert challenger["label"] == "elo_538 lab-x"
    assert challenger["role"] == "challenger"
    assert challenger["paired_n"] == 12
    assert challenger["target_n"] == 150
    assert challenger["days_live"] is not None
    assert "needs 138 more games" in challenger["gate_text"]
    assert "more days" in challenger["gate_text"]
    assert challenger["decision"] == "insufficient_data"

    # Gains
    assert challenger["log_loss_gain"] is not None
    assert isinstance(challenger["log_loss_gain"]["mean"], float)
    assert challenger["log_loss_gain"]["ci_low"] is not None
    assert challenger["log_loss_gain"]["ci_high"] is not None
    assert challenger["margin_nll_gain"] is not None
    assert isinstance(challenger["margin_nll_gain"]["mean"], float)


def test_cache_avoids_recomputing_within_ttl(client: TestClient, db_session):
    """Successive requests within the TTL return the cached response without calling build_league."""
    db_session.add(ModelVersion(name="elo_538", version="1.1", role="champion", params={"sigma": SIGMA}))
    db_session.commit()

    with patch("app.api.v1.league.build_league", wraps=league_module.build_league) as mock_build:
        resp1 = client.get("/api/v1/league")
        assert resp1.status_code == 200
        assert mock_build.call_count == 1

        resp2 = client.get("/api/v1/league")
        assert resp2.status_code == 200
        assert mock_build.call_count == 1  # Returned from cache!

        assert resp1.json() == resp2.json()


def test_cache_expires_after_ttl(client: TestClient, db_session):
    """After 5 minutes (300 s), the cache expires and recomputes on next request."""
    db_session.add(ModelVersion(name="elo_538", version="1.1", role="champion", params={"sigma": SIGMA}))
    db_session.commit()

    current_time = 1000.0

    def mock_clock():
        return current_time

    league_cache._clock = mock_clock

    with patch("app.api.v1.league.build_league", wraps=league_module.build_league) as mock_build:
        resp1 = client.get("/api/v1/league")
        assert resp1.status_code == 200
        assert mock_build.call_count == 1

        # Advance 299 seconds -> still cached
        current_time += 299.0
        resp2 = client.get("/api/v1/league")
        assert resp2.status_code == 200
        assert mock_build.call_count == 1

        # Advance past 300 seconds -> expired, triggers recompute
        current_time += 2.0  # 301.0 total
        resp3 = client.get("/api/v1/league")
        assert resp3.status_code == 200
        assert mock_build.call_count == 2


def test_get_league_does_not_write_to_database(client: TestClient, db_session):
    """Calling the endpoint never creates or alters database records."""
    db_session.add(ModelVersion(name="elo_538", version="1.1", role="champion", params={"sigma": SIGMA}))
    db_session.commit()

    models_before = len(db_session.exec(select(ModelVersion)).all())

    response = client.get("/api/v1/league")
    assert response.status_code == 200

    models_after = len(db_session.exec(select(ModelVersion)).all())
    assert models_before == models_after
