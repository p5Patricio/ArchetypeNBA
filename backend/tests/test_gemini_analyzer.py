import json
import logging
import httpx
import pytest

from app.services.gemini_analyzer import GeminiAnalyzerService, PlayerQualitativeModifier
from app.services.injury_scraper import InjuryItem


def _sample_injuries():
    return [
        InjuryItem(
            game_date="2026-09-08",
            matchup="DAL @ BOS",
            team="Dallas Mavericks",
            player_name="Luka Doncic",
            status="Out",
            reason="Knee sprain",
        ),
        InjuryItem(
            game_date="2026-09-08",
            matchup="LAL @ GSW",
            team="Los Angeles Lakers",
            player_name="LeBron James",
            status="Questionable",
            reason="Ankle sore",
        ),
    ]


def _gemini_response_body(payload_data) -> bytes:
    return json.dumps({
        "candidates": [
            {
                "content": {
                    "parts": [
                        {"text": json.dumps(payload_data)}
                    ]
                }
            }
        ]
    }).encode("utf-8")


def test_gemini_analyzer_heuristics():
    analyzer = GeminiAnalyzerService(api_key="")
    assert not analyzer.is_configured

    sample_injuries = _sample_injuries()
    result = analyzer.analyze_injuries_and_news(sample_injuries)
    assert len(result.modifiers) == 2
    assert result.engine_source == "HEURISTIC"
    assert result.model_used is None

    luka_mod = next(m for m in result.modifiers if m.player_name == "Luka Doncic")
    assert luka_mod.status == "OUT"
    assert luka_mod.minute_multiplier == 0.0
    assert luka_mod.risk_level == "EXTREME"

    lebron_mod = next(m for m in result.modifiers if m.player_name == "LeBron James")
    assert lebron_mod.status == "QUESTIONABLE"
    assert lebron_mod.minute_multiplier < 1.0


def test_gemini_analyzer_empty_injuries():
    analyzer = GeminiAnalyzerService(api_key="valid-key")
    result = analyzer.analyze_injuries_and_news([])
    assert result.engine_source == "HEURISTIC"
    assert result.model_used is None
    assert result.modifiers == []


def test_gemini_analyzer_primary_ok():
    recorded_requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        recorded_requests.append(request)
        if "gemini-3.8-flash" in str(request.url):
            payload = {
                "modifiers": [
                    {
                        "player_name": "Luka Doncic",
                        "team": "Dallas Mavericks",
                        "status": "OUT",
                        "minute_multiplier": 0.0,
                        "usage_multiplier": 0.0,
                        "risk_level": "EXTREME",
                        "tactical_summary": "Ruled out with knee injury.",
                    }
                ],
                "slate_summary": "Luka confirmed OUT.",
            }
            return httpx.Response(200, content=_gemini_response_body(payload))
        return httpx.Response(404, text="Not Found")

    transport = httpx.MockTransport(handler)
    analyzer = GeminiAnalyzerService(
        api_key="valid-test-key",
        model="gemini-3.8-flash",
        fallback_model="gemini-3.6-flash",
        transport=transport,
    )

    result = analyzer.analyze_injuries_and_news(_sample_injuries())

    assert result.engine_source == "GEMINI"
    assert result.model_used == "gemini-3.8-flash"
    assert len(result.modifiers) == 1
    assert result.modifiers[0].player_name == "Luka Doncic"
    assert "Luka confirmed OUT" in result.slate_summary

    assert len(recorded_requests) == 1
    assert "gemini-3.8-flash:generateContent" in str(recorded_requests[0].url)
    assert recorded_requests[0].headers.get("x-goog-api-key") == "valid-test-key"


def test_gemini_analyzer_primary_404_fallback_ok():
    recorded_requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        recorded_requests.append(request)
        if "gemini-3.8-flash" in str(request.url):
            return httpx.Response(404, json={"error": {"code": 404, "message": "models/gemini-3.8-flash not found"}})
        if "gemini-3.6-flash" in str(request.url):
            payload = [
                {
                    "player_name": "Luka Doncic",
                    "team": "Dallas Mavericks",
                    "status": "OUT",
                    "minute_multiplier": 0.0,
                    "usage_multiplier": 0.0,
                    "risk_level": "EXTREME",
                    "tactical_summary": "Fallback model analysis.",
                }
            ]
            return httpx.Response(200, content=_gemini_response_body(payload))
        return httpx.Response(500, text="Unexpected model")

    transport = httpx.MockTransport(handler)
    analyzer = GeminiAnalyzerService(
        api_key="valid-test-key",
        model="gemini-3.8-flash",
        fallback_model="gemini-3.6-flash",
        transport=transport,
    )

    result = analyzer.analyze_injuries_and_news(_sample_injuries())

    assert result.engine_source == "GEMINI"
    assert result.model_used == "gemini-3.6-flash"
    assert len(result.modifiers) == 1

    # Exactly 2 requests: primary then fallback
    assert len(recorded_requests) == 2
    assert "gemini-3.8-flash:generateContent" in str(recorded_requests[0].url)
    assert "gemini-3.6-flash:generateContent" in str(recorded_requests[1].url)


def test_gemini_analyzer_primary_429_fallback_ok():
    recorded_requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        recorded_requests.append(request)
        if "gemini-3.8-flash" in str(request.url):
            return httpx.Response(429, json={"error": {"code": 429, "message": "Resource exhausted"}})
        if "gemini-3.6-flash" in str(request.url):
            payload = {
                "modifiers": [
                    {
                        "player_name": "LeBron James",
                        "team": "Los Angeles Lakers",
                        "status": "QUESTIONABLE",
                        "minute_multiplier": 0.8,
                        "usage_multiplier": 1.0,
                        "risk_level": "MEDIUM",
                        "tactical_summary": "Questionable on back to back.",
                    }
                ],
                "slate_summary": "Analyzed via fallback.",
            }
            return httpx.Response(200, content=_gemini_response_body(payload))
        return httpx.Response(500, text="Unexpected model")

    transport = httpx.MockTransport(handler)
    analyzer = GeminiAnalyzerService(
        api_key="valid-test-key",
        model="gemini-3.8-flash",
        fallback_model="gemini-3.6-flash",
        transport=transport,
    )

    result = analyzer.analyze_injuries_and_news(_sample_injuries())

    assert result.engine_source == "GEMINI"
    assert result.model_used == "gemini-3.6-flash"
    assert len(result.modifiers) == 1
    assert len(recorded_requests) == 2


def test_gemini_analyzer_both_fail_heuristic():
    recorded_requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        recorded_requests.append(request)
        if "gemini-3.8-flash" in str(request.url):
            return httpx.Response(404, json={"error": "Model not found"})
        if "gemini-3.6-flash" in str(request.url):
            return httpx.Response(429, json={"error": "Rate limited"})
        return httpx.Response(500, text="Server error")

    transport = httpx.MockTransport(handler)
    analyzer = GeminiAnalyzerService(
        api_key="valid-test-key",
        model="gemini-3.8-flash",
        fallback_model="gemini-3.6-flash",
        transport=transport,
    )

    result = analyzer.analyze_injuries_and_news(_sample_injuries())

    # Falls back to heuristic rules
    assert result.engine_source == "HEURISTIC"
    assert result.model_used is None
    assert len(result.modifiers) == 2
    # Never retried more than once: exactly 2 requests made
    assert len(recorded_requests) == 2


def test_gemini_analyzer_key_never_appears_in_logs(caplog):
    secret_key = "super_secret_token_gemini_xyz_998877"

    # 1. Primary OK
    def handler_ok(request: httpx.Request) -> httpx.Response:
        payload = {"modifiers": [], "slate_summary": "All good"}
        return httpx.Response(200, content=_gemini_response_body(payload))

    with caplog.at_level(logging.DEBUG):
        analyzer = GeminiAnalyzerService(
            api_key=secret_key,
            transport=httpx.MockTransport(handler_ok),
        )
        analyzer.analyze_injuries_and_news(_sample_injuries())
        assert secret_key not in caplog.text

    caplog.clear()

    # 2. Primary 404, fallback OK
    def handler_fallback(request: httpx.Request) -> httpx.Response:
        if "gemini-3.8-flash" in str(request.url):
            return httpx.Response(404, text=f"Model not found {secret_key}")
        return httpx.Response(200, content=_gemini_response_body({"modifiers": []}))

    with caplog.at_level(logging.DEBUG):
        analyzer = GeminiAnalyzerService(
            api_key=secret_key,
            transport=httpx.MockTransport(handler_fallback),
        )
        analyzer.analyze_injuries_and_news(_sample_injuries())
        assert secret_key not in caplog.text

    caplog.clear()

    # 3. Both fail with exception
    def handler_error(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"Connection failed for {secret_key}")

    with caplog.at_level(logging.DEBUG):
        analyzer = GeminiAnalyzerService(
            api_key=secret_key,
            transport=httpx.MockTransport(handler_error),
        )
        analyzer.analyze_injuries_and_news(_sample_injuries())
        assert secret_key not in caplog.text
