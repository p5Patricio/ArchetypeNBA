import httpx
import pytest

from app.services import odds_api_service
from app.services.odds_api_service import OddsApiService, OddsQuote, select_best_lines

REAL_CLIENT = httpx.Client


def _outcome(side, player, point, price):
    return {"name": side, "description": player, "point": point, "price": price}


def _book(key, last_update, market_key, outcomes):
    return {
        "key": key,
        "last_update": last_update,
        "markets": [{"key": market_key, "outcomes": outcomes}],
    }


EVENT_PAYLOAD = {
    "id": "evt1",
    "bookmakers": [
        # alpha: two-sided at 24.5, worse over price
        _book("alpha", "2026-10-06T18:00:00Z", "player_points", [
            _outcome("Over", "Test Player", 24.5, -115),
            _outcome("Under", "Test Player", 24.5, -105),
        ]),
        # bravo: two-sided at 24.5, best over price
        _book("bravo", "2026-10-06T18:05:00Z", "player_points", [
            _outcome("Over", "Test Player", 24.5, -105),
            _outcome("Under", "Test Player", 24.5, -125),
        ]),
        # charlie: only an over, at a different line (must not overwrite or win)
        _book("charlie", "2026-10-06T18:10:00Z", "player_points", [
            _outcome("Over", "Test Player", 25.5, +100),
        ]),
        # delta: rebounds, over only -> under must stay missing
        _book("delta", "2026-10-06T18:15:00Z", "player_rebounds", [
            _outcome("Over", "Test Player", 7.5, -120),
        ]),
    ],
}


@pytest.fixture
def mock_http(monkeypatch):
    """Routes the service's httpx.Client through an in-process MockTransport."""
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        headers = {"x-requests-remaining": "490", "x-requests-used": "10"}
        if request.url.path.endswith("/events"):
            return httpx.Response(200, json=[{"id": "evt1"}], headers=headers)
        return httpx.Response(200, json=EVENT_PAYLOAD, headers=headers)

    def client_factory(*args, **kwargs):
        return REAL_CLIENT(transport=httpx.MockTransport(handler), timeout=kwargs.get("timeout"))

    monkeypatch.setattr(odds_api_service.httpx, "Client", client_factory)
    return calls


def test_unconfigured_service_returns_no_lines():
    service = OddsApiService(api_key="")
    assert not service.is_configured
    assert service.get_slate_props_map() == {}
    assert service.last_fetch_live is False


def test_odds_api_quota_tracking():
    service = OddsApiService()
    sample_headers = {
        "x-requests-remaining": "495",
        "x-requests-used": "5",
    }
    service._update_quota(sample_headers)
    assert service.requests_remaining == 495
    assert service.requests_used == 5


def test_quotes_keep_bookmaker_attribution_and_nothing_is_overwritten(mock_http):
    service = OddsApiService(api_key="real-key")
    quotes = service.fetch_event_prop_quotes("evt1")

    # 2 + 2 + 1 + 1 outcomes, one quote each
    assert len(quotes) == 6
    pts = [q for q in quotes if q.stat_type == "PTS"]
    assert {q.bookmaker_key for q in pts} == {"alpha", "bravo", "charlie"}

    bravo_over = next(q for q in quotes if q.bookmaker_key == "bravo" and q.side == "over")
    assert bravo_over.price_american == -105
    assert bravo_over.line == 24.5
    assert bravo_over.market_key == "player_points"
    assert bravo_over.player_name == "Test Player"
    assert bravo_over.book_last_update == "2026-10-06T18:05:00Z"

    alpha_over = next(q for q in quotes if q.bookmaker_key == "alpha" and q.side == "over")
    assert alpha_over.price_american == -115  # not replaced by a later book


def test_slate_map_picks_best_two_sided_pair_and_carries_bookmaker(mock_http):
    service = OddsApiService(api_key="real-key")
    props = service.get_slate_props_map()

    assert service.last_fetch_live is True
    pts = props["Test Player"]["PTS"]
    # modal two-sided line is 24.5; bravo has the best over price there
    assert pts.line == 24.5
    assert pts.bookmaker == "bravo"
    assert pts.over_odds == -105
    assert pts.under_odds == -125  # bravo's own under, not alpha's


def test_slate_map_missing_under_stays_none(mock_http):
    service = OddsApiService(api_key="real-key")
    reb = service.get_slate_props_map()["Test Player"]["REB"]

    assert reb.bookmaker == "delta"
    assert reb.over_odds == -120
    assert reb.under_odds is None


def test_no_events_means_no_lines_and_not_live(monkeypatch):
    def handler(request):
        return httpx.Response(200, json=[])

    monkeypatch.setattr(
        odds_api_service.httpx,
        "Client",
        lambda *a, **k: REAL_CLIENT(transport=httpx.MockTransport(handler)),
    )
    service = OddsApiService(api_key="real-key")
    assert service.get_slate_props_map() == {}
    assert service.last_fetch_live is False


def _q(book, side, line, price, player="P", stat="PTS"):
    return OddsQuote(
        event_id="e", bookmaker_key=book, market_key="player_points", stat_type=stat,
        player_name=player, side=side, line=line, price_american=price,
    )


def test_selection_uses_modal_line_across_books():
    quotes = [
        _q("a", "over", 20.5, -110), _q("a", "under", 20.5, -110),
        _q("b", "over", 21.5, +105), _q("b", "under", 21.5, -135),  # odd one out, better price
        _q("c", "over", 20.5, -112), _q("c", "under", 20.5, -108),
    ]
    line = select_best_lines(quotes)["P"]["PTS"]
    assert line.line == 20.5
    assert line.bookmaker == "a"  # -110 beats -112


def test_selection_ties_break_on_bookmaker_key():
    quotes = [
        _q("zeta", "over", 20.5, -110), _q("zeta", "under", 20.5, -110),
        _q("alpha", "over", 20.5, -110), _q("alpha", "under", 20.5, -110),
    ]
    assert select_best_lines(quotes)["P"]["PTS"].bookmaker == "alpha"


def test_selection_prefers_two_sided_over_better_one_sided_price():
    quotes = [
        _q("a", "over", 20.5, -120), _q("a", "under", 20.5, +100),
        _q("b", "over", 20.5, +150),  # better over price but no under from b
    ]
    line = select_best_lines(quotes)["P"]["PTS"]
    assert line.bookmaker == "a"
    assert line.under_odds == 100


def test_selection_ignores_under_only_players():
    assert select_best_lines([_q("a", "under", 20.5, -110)]) == {}
