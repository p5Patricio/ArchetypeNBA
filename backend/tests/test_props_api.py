import json

import pytest
from fastapi.testclient import TestClient

from app.analytics.props_engine import PropBetLine, PropsEngine
from app.api.v1 import props as props_module
from app.main import app
from app.services.gemini_analyzer import GeminiAnalyzerService, SlateAnalysisResult
from app.services.injury_scraper import InjuryScraperService
from app.services.odds_api_service import OddsApiService

client = TestClient(app)


@pytest.fixture(autouse=True)
def isolated_props(monkeypatch, tmp_path):
    """Isolates the props endpoints from the user's cache file, the network and the SQLite stats DB."""
    monkeypatch.setattr(props_module, "CACHE_FILE", tmp_path / "last_props_cache.json")
    monkeypatch.setattr(props_module, "_cached_response", None)
    monkeypatch.setattr(props_module, "_last_computed_time", None)
    monkeypatch.setattr(InjuryScraperService, "fetch_injury_report", lambda self: [])
    monkeypatch.setattr(
        GeminiAnalyzerService,
        "analyze_injuries_and_news",
        lambda self, items: SlateAnalysisResult(modifiers=[], slate_summary="Test slate."),
    )
    monkeypatch.setattr(
        PropsEngine, "load_baselines_from_db", lambda self, *a, **k: self.get_standard_star_baselines()
    )


def _no_live_lines(monkeypatch):
    def fake(self):
        self.last_fetch_live = False
        return {}

    monkeypatch.setattr(OddsApiService, "get_slate_props_map", fake)


def _live_lines(monkeypatch, lines):
    def fake(self):
        self.last_fetch_live = True
        return lines

    monkeypatch.setattr(OddsApiService, "get_slate_props_map", fake)


def test_refresh_without_live_lines_returns_an_honest_empty_slate(monkeypatch):
    _no_live_lines(monkeypatch)

    response = client.get("/api/v1/props/today?refresh=true")

    assert response.status_code == 200
    data = response.json()
    assert data["items"] == []
    assert data["total_props"] == 0
    assert data["value_picks_count"] == 0
    assert "Sin líneas en vivo" in data["odds_source"]
    assert "Consenso" not in data["odds_source"]


def test_run_analysis_without_live_lines_never_invents_picks(monkeypatch):
    _no_live_lines(monkeypatch)

    response = client.post("/api/v1/props/run-analysis")

    assert response.status_code == 200
    data = response.json()
    assert data["items"] == []
    assert "Sin líneas en vivo" in data["odds_source"]


def test_live_lines_produce_items_with_side_and_bookmaker(monkeypatch):
    # Luka is far below the line on points, so the two-sided market should surface the under.
    _live_lines(
        monkeypatch,
        {
            "Luka Doncic": {
                "PTS": PropBetLine(
                    stat_type="PTS", line=44.5, over_odds=-110, under_odds=-110, bookmaker="bravo"
                ),
            }
        },
    )

    response = client.get("/api/v1/props/today?refresh=true")

    assert response.status_code == 200
    data = response.json()
    assert data["odds_source"] == "The Odds API (En Vivo)"
    # Only the player/stat with a real line is evaluated; nobody else gets a made-up line.
    assert [(i["player_name"], i["stat_type"]) for i in data["items"]] == [("Luka Doncic", "PTS")]

    item = data["items"][0]
    assert item["line"] == 44.5
    assert item["bookmaker"] == "bravo"
    assert item["under_odds"] == -110
    assert item["devigged"] is True
    assert item["fair_prob"] == pytest.approx(0.5)
    assert item["side"] == "under"
    assert item["prob_under"] > item["prob_over"]


def test_persisted_cache_round_trips_new_fields(monkeypatch):
    _live_lines(
        monkeypatch,
        {"Luka Doncic": {"PTS": PropBetLine(stat_type="PTS", line=30.5, over_odds=-115, bookmaker="alpha")}},
    )
    client.get("/api/v1/props/today?refresh=true")

    loaded = props_module._load_cache_from_file()

    assert loaded is not None
    assert loaded.items[0].bookmaker == "alpha"
    assert loaded.items[0].devigged is False
    assert loaded.items[0].under_odds is None


def test_cache_written_before_side_fields_still_loads():
    legacy_item = {
        "player_name": "LeBron James",
        "team": "LAL",
        "stat_type": "PTS",
        "line": 22.5,
        "over_odds": -110,
        "projected_mean": 16.8,
        "projected_median": 16.0,
        "projected_p10": 9.0,
        "projected_p90": 26.0,
        "prob_over": 0.1892,
        "book_implied_prob": 0.5238,
        "edge_pct": -33.5,
        "expected_value_pct": -63.9,
        "kelly_stake_pct": 0.0,
        "recommendation": "PASS",
        "risk_level": "MEDIUM",
        "reasoning": "legacy",
    }
    legacy = {
        "date": "2026-09-13",
        "ai_engine": "Modo Heurístico Local",
        "odds_source": "The Odds API (En Vivo)",
        "slate_summary": "legacy",
        "total_props": 1,
        "value_picks_count": 0,
        "items": [legacy_item],
    }
    props_module.CACHE_FILE.write_text(json.dumps(legacy), encoding="utf-8")

    loaded = props_module._load_cache_from_file()

    assert loaded is not None
    item = loaded.items[0]
    assert item.side == "over"
    assert item.bookmaker is None
    assert item.under_odds is None
    assert item.prob_under is None
    assert item.devigged is False

    # And the endpoint serves it instead of crashing.
    response = client.get("/api/v1/props/today")
    assert response.status_code == 200
    assert response.json()["items"][0]["player_name"] == "LeBron James"


def test_idle_state_without_cache_is_empty():
    response = client.get("/api/v1/props/today")

    assert response.status_code == 200
    assert response.json()["items"] == []


def test_stat_type_filter_only_returns_requested_stat(monkeypatch):
    _live_lines(
        monkeypatch,
        {
            "Luka Doncic": {
                "PTS": PropBetLine(stat_type="PTS", line=30.5, over_odds=-110, under_odds=-110),
                "REB": PropBetLine(stat_type="REB", line=8.5, over_odds=-110, under_odds=-110),
            }
        },
    )
    client.get("/api/v1/props/today?refresh=true")

    data = client.get("/api/v1/props/today?stat_type=PTS").json()

    assert data["items"]
    assert all(item["stat_type"] == "PTS" for item in data["items"])


def test_telegram_report_shows_chosen_side_price_probability_and_bookmaker(monkeypatch):
    _live_lines(
        monkeypatch,
        {
            "Luka Doncic": {
                "PTS": PropBetLine(
                    stat_type="PTS", line=44.5, over_odds=-110, under_odds=+120, bookmaker="bravo"
                ),
            }
        },
    )
    response = props_module._compute_today_props()
    item = response.items[0]
    assert item.side == "under"

    sent = []
    monkeypatch.setattr(props_module.settings, "TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setattr(props_module.settings, "TELEGRAM_CHAT_ID", "chat")
    monkeypatch.setattr(
        props_module.TelegramService, "send_message_sync", lambda self, msg: sent.append(msg) or True
    )

    assert props_module._send_telegram_report(response) is True

    message = sent[0]
    assert "Cuota Under: +120 · bravo" in message
    assert f"Prob. Under:* `{item.prob_under * 100:.1f}%`" in message
    assert "Cuota Over" not in message
