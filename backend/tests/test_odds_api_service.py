from app.services.odds_api_service import OddsApiService


def test_odds_api_service_consensus_fallback():
    service = OddsApiService(api_key="")
    assert not service.is_configured
    props = service.get_slate_props_map()
    assert "Luka Doncic" in props
    assert "PTS" in props["Luka Doncic"]
    assert props["Luka Doncic"]["PTS"].line > 0


def test_odds_api_quota_tracking():
    service = OddsApiService()
    sample_headers = {
        "x-requests-remaining": "495",
        "x-requests-used": "5",
    }
    service._update_quota(sample_headers)
    assert service.requests_remaining == 495
    assert service.requests_used == 5
