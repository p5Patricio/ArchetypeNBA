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


def _patch_client(monkeypatch, handler):
    monkeypatch.setattr(
        odds_api_service.httpx,
        "Client",
        lambda *a, **k: REAL_CLIENT(transport=httpx.MockTransport(handler)),
    )


def test_quotes_with_missing_point_or_price_are_skipped(monkeypatch):
    payload = {
        "bookmakers": [
            _book("alpha", "2026-10-06T18:00:00Z", "player_points", [
                {"name": "Over", "description": "Test Player", "price": -110},  # no point
                {"name": "Under", "description": "Test Player", "point": 24.5},  # no price
                {"name": "Over", "description": None, "point": 24.5, "price": -110},  # no player
                {"name": "Push", "description": "Test Player", "point": 24.5, "price": -110},  # unknown side
                _outcome("Over", "Test Player", 25.5, -108),  # the only complete quote
            ]),
        ]
    }
    _patch_client(monkeypatch, lambda request: httpx.Response(200, json=payload))

    quotes = OddsApiService(api_key="real-key").fetch_event_prop_quotes("evt1")

    assert len(quotes) == 1
    assert (quotes[0].line, quotes[0].price_american, quotes[0].side) == (25.5, -108, "over")


def test_non_200_props_response_returns_no_quotes_and_not_live(monkeypatch):
    def handler(request):
        if request.url.path.endswith("/events"):
            return httpx.Response(200, json=[{"id": "evt1"}])
        return httpx.Response(500, json={"message": "boom"})

    _patch_client(monkeypatch, handler)
    service = OddsApiService(api_key="real-key")

    assert service.fetch_event_prop_quotes("evt1") == []
    assert service.get_slate_props_map() == {}
    assert service.last_fetch_live is False


def test_http_exception_returns_no_quotes_and_not_live(monkeypatch):
    def handler(request):
        raise httpx.ConnectError("network down", request=request)

    _patch_client(monkeypatch, handler)
    service = OddsApiService(api_key="real-key")

    assert service.fetch_upcoming_events() == []
    assert service.fetch_event_prop_quotes("evt1") == []
    assert service.get_slate_props_map() == {}
    assert service.last_fetch_live is False


def test_failed_refetch_resets_last_fetch_live(monkeypatch):
    state = {"fail": False}

    def handler(request):
        if state["fail"]:
            return httpx.Response(503, json={})
        if request.url.path.endswith("/events"):
            return httpx.Response(200, json=[{"id": "evt1"}])
        return httpx.Response(200, json=EVENT_PAYLOAD)

    _patch_client(monkeypatch, handler)
    service = OddsApiService(api_key="real-key")

    assert service.get_slate_props_map()
    assert service.last_fetch_live is True

    state["fail"] = True
    assert service.get_slate_props_map() == {}
    assert service.last_fetch_live is False

# --- game lines (/odds: h2h, spreads, totals) ---------------------------------

GAME_EVENT = {
    "id": "game1",
    "commence_time": "2026-10-21T00:00:00Z",
    "home_team": "Boston Celtics",
    "away_team": "LA Clippers",
    "bookmakers": [
        {
            "key": "pinnacle",
            "title": "Pinnacle",
            "last_update": "2026-10-20T20:00:00Z",
            "markets": [
                {"key": "h2h", "last_update": "2026-10-20T20:01:00Z", "outcomes": [
                    {"name": "Boston Celtics", "price": -150},
                    {"name": "LA Clippers", "price": 130},
                ]},
                {"key": "spreads", "outcomes": [
                    {"name": "Boston Celtics", "price": -105, "point": -3.5},
                    {"name": "LA Clippers", "price": -115, "point": 3.5},
                ]},
                {"key": "totals", "outcomes": [
                    {"name": "Over", "price": -110, "point": 221.5},
                    {"name": "Under", "price": -110, "point": 221.5},
                ]},
            ],
        },
        {
            "key": "draftkings",
            "title": "DraftKings",
            "last_update": "2026-10-20T20:02:00Z",
            "markets": [
                {"key": "h2h", "outcomes": [
                    {"name": "Boston Celtics", "price": -145},
                    {"name": "Mystery Team", "price": 120},  # unknown team name -> skipped
                    {"name": "LA Clippers"},  # no price -> skipped
                ]},
                {"key": "spreads", "outcomes": [
                    {"name": "Boston Celtics", "price": -110},  # no point -> skipped
                ]},
                {"key": "totals", "outcomes": [
                    {"name": "Push", "price": -110, "point": 221.5},  # not over/under -> skipped
                    {"name": "Over", "price": "n/a", "point": 221.5},  # unparsable price -> skipped
                    {"name": "Under", "price": -108, "point": 221.5},
                ]},
                {"key": "player_points", "outcomes": [{"name": "Over", "price": -110, "point": 20.5}]},
            ],
        },
        {"title": "No key", "markets": []},
    ],
}


@pytest.fixture
def game_lines_http(monkeypatch):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            200,
            json=[GAME_EVENT, {"id": "broken", "home_team": "Boston Celtics"}],
            headers={"x-requests-remaining": "497", "x-requests-used": "3"},
        )

    monkeypatch.setattr(
        odds_api_service.httpx,
        "Client",
        lambda *a, **k: REAL_CLIENT(transport=httpx.MockTransport(handler), timeout=k.get("timeout")),
    )
    return calls


def test_game_lines_are_parsed_per_bookmaker_with_sides_and_lines(game_lines_http):
    quotes = OddsApiService(api_key="real-key").fetch_game_lines(["pinnacle", "draftkings"])

    pinnacle = [q for q in quotes if q.bookmaker_key == "pinnacle"]
    assert len(pinnacle) == 6
    ml_away = next(q for q in pinnacle if q.market_key == "h2h" and q.side == "away")
    assert (ml_away.price_american, ml_away.line) == (130, None)
    assert ml_away.home_team == "Boston Celtics" and ml_away.away_team == "LA Clippers"
    assert ml_away.book_last_update == "2026-10-20T20:01:00Z"  # market-level update wins

    spread_home = next(q for q in pinnacle if q.market_key == "spreads" and q.side == "home")
    assert (spread_home.line, spread_home.price_american) == (-3.5, -105)
    assert spread_home.book_last_update == "2026-10-20T20:00:00Z"  # falls back to the bookmaker's

    total_over = next(q for q in pinnacle if q.market_key == "totals" and q.side == "over")
    assert total_over.line == 221.5
    assert pinnacle[0].bookmaker_title == "Pinnacle"


def test_game_lines_skip_malformed_outcomes_and_events(game_lines_http):
    quotes = OddsApiService(api_key="real-key").fetch_game_lines(["pinnacle", "draftkings"])

    dk = [q for q in quotes if q.bookmaker_key == "draftkings"]
    # kept: Boston h2h, Under -108. Dropped: unknown team, missing price/point, Push, bad price,
    # prop market and the book without a key. The incomplete event ("broken") yields nothing.
    assert {(q.market_key, q.side, q.price_american) for q in dk} == {
        ("h2h", "home", -145),
        ("totals", "under", -108),
    }
    assert {q.event_id for q in quotes} == {"game1"}


def test_game_lines_request_uses_bookmakers_param_and_tracks_quota(game_lines_http):
    service = OddsApiService(api_key="real-key")
    service.fetch_game_lines(["pinnacle", "fanduel"])

    params = game_lines_http[0].url.params
    assert game_lines_http[0].url.path.endswith("/basketball_nba/odds")
    assert params["bookmakers"] == "pinnacle,fanduel"
    assert params["markets"] == "h2h,spreads,totals"
    assert "regions" not in params
    assert service.requests_remaining == 497


def test_game_lines_default_bookmakers_include_pinnacle_and_cap_at_ten(game_lines_http):
    service = OddsApiService(api_key="real-key")
    service.fetch_game_lines()
    assert game_lines_http[0].url.params["bookmakers"].split(",")[0] == "pinnacle"

    service.fetch_game_lines([f"book{i}" for i in range(14)])
    assert len(game_lines_http[1].url.params["bookmakers"].split(",")) == 10


def test_game_lines_unconfigured_non_200_and_exception_return_empty(monkeypatch):
    assert OddsApiService(api_key="").fetch_game_lines() == []

    monkeypatch.setattr(
        odds_api_service.httpx,
        "Client",
        lambda *a, **k: REAL_CLIENT(
            transport=httpx.MockTransport(lambda request: httpx.Response(401, text="bad key"))
        ),
    )
    assert OddsApiService(api_key="real-key").fetch_game_lines() == []

    def boom(request):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(
        odds_api_service.httpx, "Client", lambda *a, **k: REAL_CLIENT(transport=httpx.MockTransport(boom))
    )
    assert OddsApiService(api_key="real-key").fetch_game_lines() == []


def test_prop_quotes_request_only_the_requested_markets(mock_http):
    OddsApiService(api_key="real-key").fetch_event_prop_quotes("evt1", markets=["player_points"])

    assert mock_http[0].url.params["markets"] == "player_points"
