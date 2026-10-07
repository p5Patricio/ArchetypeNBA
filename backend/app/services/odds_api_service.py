import logging
from collections import Counter
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple
import httpx

from app.config import settings
from app.analytics.props_engine import PropBetLine, american_to_decimal

logger = logging.getLogger(__name__)

MARKET_TO_STAT = {
    "player_points": "PTS",
    "player_rebounds": "REB",
    "player_assists": "AST",
}


GAME_LINE_MARKETS = ("h2h", "spreads", "totals")
# Pinnacle (sharp reference) is only listed in the `eu` region; `bookmakers=` reaches it directly.
DEFAULT_BOOKMAKERS = (
    "pinnacle",
    "draftkings",
    "fanduel",
    "betmgm",
    "williamhill_us",
    "betrivers",
    "bovada",
)
MAX_BOOKMAKERS_PER_CALL = 10  # The Odds API bills one "region" per group of 10 bookmakers


@dataclass(frozen=True)
class GameQuote:
    """A single price offered by one bookmaker for one side of one game market (moneyline, spread, total)."""

    event_id: str
    commence_time: str  # ISO 8601 as returned by the API
    home_team: str
    away_team: str
    bookmaker_key: str
    bookmaker_title: str
    market_key: str  # 'h2h', 'spreads' or 'totals'
    side: str  # 'home', 'away', 'over' or 'under'
    line: Optional[float]  # None for h2h
    price_american: int
    book_last_update: Optional[str] = None  # market `last_update` (falls back to the bookmaker's)


@dataclass(frozen=True)
class OddsQuote:
    """A single price offered by one bookmaker for one side of one player prop."""

    event_id: str
    bookmaker_key: str
    market_key: str
    stat_type: str
    player_name: str
    side: str  # 'over' or 'under'
    line: float
    price_american: int
    book_last_update: Optional[str] = None  # bookmaker `last_update` as returned by the API (ISO 8601)


def _modal_line(lines: List[float]) -> float:
    """Most common line; ties resolve to the lowest line so the result is deterministic."""
    counts = Counter(lines)
    top = max(counts.values())
    return min(line for line, n in counts.items() if n == top)


def _best_over_at_line(
    candidates: List[Tuple[OddsQuote, Optional[OddsQuote]]], line: float
) -> Tuple[OddsQuote, Optional[OddsQuote]]:
    """Picks the pair with the best over price at `line`; ties break on bookmaker key (ascending)."""
    at_line = [c for c in candidates if c[0].line == line]
    return min(at_line, key=lambda c: (-american_to_decimal(c[0].price_american), c[0].bookmaker_key))


def select_best_lines(quotes: List[OddsQuote]) -> Dict[str, Dict[str, PropBetLine]]:
    """
    Reduces all quotes to one PropBetLine per player/stat, deterministically.

    1. Prefer two-sided pairs: an over and an under from the SAME book at the SAME line.
       Take the modal line across books, then the pair with the best over price at that line
       (tie-break: bookmaker key ascending).
    2. If no two-sided pair exists, fall back to over-only quotes with the same line/price/tie-break
       rules; under_odds stays None (a missing side is never invented).
    """
    grouped: Dict[Tuple[str, str], List[OddsQuote]] = {}
    for q in quotes:
        grouped.setdefault((q.player_name, q.stat_type), []).append(q)

    result: Dict[str, Dict[str, PropBetLine]] = {}
    for (player, stat_type), group in grouped.items():
        ordered = sorted(group, key=lambda q: (q.bookmaker_key, q.line))
        overs = {(q.bookmaker_key, q.line): q for q in ordered if q.side == "over"}
        unders = {(q.bookmaker_key, q.line): q for q in ordered if q.side == "under"}

        pairs = [(o, unders[key]) for key, o in overs.items() if key in unders]
        if pairs:
            line = _modal_line([o.line for o, _ in pairs])
            over_q, under_q = _best_over_at_line(pairs, line)
        elif overs:
            one_sided = [(o, None) for o in overs.values()]
            line = _modal_line([o.line for o, _ in one_sided])
            over_q, under_q = _best_over_at_line(one_sided, line)
        else:
            continue

        result.setdefault(player, {})[stat_type] = PropBetLine(
            stat_type=stat_type,
            line=over_q.line,
            over_odds=over_q.price_american,
            under_odds=under_q.price_american if under_q else None,
            bookmaker=over_q.bookmaker_key,
        )

    return result


def _team_side(name: str, home_team: str, away_team: str) -> Optional[str]:
    cleaned = (name or "").strip().lower()
    if cleaned == home_team.strip().lower():
        return "home"
    if cleaned == away_team.strip().lower():
        return "away"
    return None


def parse_game_quotes(events: object) -> List[GameQuote]:
    """Flattens a /odds payload into GameQuotes, skipping any event, market or outcome that is incomplete."""
    quotes: List[GameQuote] = []
    if not isinstance(events, list):
        return quotes

    for event in events:
        if not isinstance(event, dict):
            continue
        event_id = event.get("id")
        commence = event.get("commence_time")
        home = event.get("home_team")
        away = event.get("away_team")
        if not (event_id and commence and home and away):
            continue

        for book in event.get("bookmakers") or []:
            book_key = book.get("key")
            if not book_key:
                continue
            book_title = book.get("title") or book_key

            for market in book.get("markets") or []:
                m_key = market.get("key")
                if m_key not in GAME_LINE_MARKETS:
                    continue
                updated = market.get("last_update") or book.get("last_update")

                for o in market.get("outcomes") or []:
                    name = o.get("name")
                    price = o.get("price")
                    point = o.get("point")
                    if price is None:
                        continue

                    if m_key == "totals":
                        side = (name or "").strip().lower()
                        if side not in ("over", "under") or point is None:
                            continue
                    else:
                        side = _team_side(name, home, away)
                        if side is None or (m_key == "spreads" and point is None):
                            continue

                    try:
                        line = float(point) if m_key != "h2h" else None
                        price_american = int(price)
                    except (TypeError, ValueError):
                        continue

                    quotes.append(
                        GameQuote(
                            event_id=event_id,
                            commence_time=commence,
                            home_team=home,
                            away_team=away,
                            bookmaker_key=book_key,
                            bookmaker_title=book_title,
                            market_key=m_key,
                            side=side,
                            line=line,
                            price_american=price_american,
                            book_last_update=updated,
                        )
                    )
    return quotes


class OddsApiService:
    """Client for The Odds API (https://the-odds-api.com) to retrieve live NBA betting lines and player props."""

    BASE_URL = "https://api.the-odds-api.com/v4/sports/basketball_nba"

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key if api_key is not None else settings.THE_ODDS_API_KEY
        self.requests_remaining: Optional[int] = None
        self.requests_used: Optional[int] = None
        self.last_fetch_live: bool = False  # True only if the last get_slate_props_map() returned live lines

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key and "your_" not in self.api_key)

    def fetch_upcoming_events(self) -> List[Dict]:
        """Retrieves upcoming NBA games and their event IDs."""
        if not self.is_configured:
            logger.warning("OddsApiService: API Key not configured.")
            return []

        url = f"{self.BASE_URL}/events"
        params = {"apiKey": self.api_key}

        try:
            with httpx.Client(timeout=15.0) as client:
                res = client.get(url, params=params)
                self._update_quota(res.headers)
                if res.status_code == 200:
                    return res.json()
                else:
                    logger.error(f"OddsApiService: Error fetching events: {res.status_code} - {res.text}")
        except Exception as e:
            logger.error(f"OddsApiService: Exception during fetch_upcoming_events: {e}")

        return []

    def fetch_game_lines(self, bookmakers: Optional[Sequence[str]] = None) -> List[GameQuote]:
        """
        Fetches moneyline, spread and total quotes for every upcoming NBA game in ONE call
        (cost: 3 markets x 1 = 3 credits for up to 10 bookmakers). One GameQuote per
        bookmaker / market / side; malformed outcomes are skipped, never repaired.
        """
        if not self.is_configured:
            return []

        books = list(bookmakers) if bookmakers else list(DEFAULT_BOOKMAKERS)
        if len(books) > MAX_BOOKMAKERS_PER_CALL:
            logger.warning(
                f"OddsApiService: {len(books)} bookmakers requested; using the first {MAX_BOOKMAKERS_PER_CALL}."
            )
            books = books[:MAX_BOOKMAKERS_PER_CALL]

        url = f"{self.BASE_URL}/odds"
        params = {
            "apiKey": self.api_key,
            "bookmakers": ",".join(books),
            "markets": ",".join(GAME_LINE_MARKETS),
            "oddsFormat": "american",
        }

        try:
            with httpx.Client(timeout=15.0) as client:
                res = client.get(url, params=params)
                self._update_quota(res.headers)
                if res.status_code != 200:
                    logger.error(f"OddsApiService: Error fetching game lines: {res.status_code} - {res.text}")
                    return []
                return parse_game_quotes(res.json())
        except Exception as e:
            logger.error(f"OddsApiService: Exception during fetch_game_lines: {e}")
            return []

    def fetch_event_prop_quotes(
        self, event_id: str, markets: Optional[Sequence[str]] = None
    ) -> List[OddsQuote]:
        """
        Fetches player-prop quotes for an NBA event (all of points/rebounds/assists by default; each
        market costs 1 credit). One OddsQuote per bookmaker / market / player / side; nothing is
        merged or overwritten.
        """
        if not self.is_configured:
            return []

        wanted = [m for m in (markets or MARKET_TO_STAT) if m in MARKET_TO_STAT]
        if not wanted:
            return []

        url = f"{self.BASE_URL}/events/{event_id}/odds"
        params = {
            "apiKey": self.api_key,
            "regions": "us",
            "markets": ",".join(wanted),
            "oddsFormat": "american",
        }

        quotes: List[OddsQuote] = []
        try:
            with httpx.Client(timeout=15.0) as client:
                res = client.get(url, params=params)
                self._update_quota(res.headers)
                if res.status_code != 200:
                    logger.error(f"OddsApiService: Error fetching props for event {event_id}: {res.status_code}")
                    return []

                for book in res.json().get("bookmakers", []):
                    book_key = book.get("key")
                    if not book_key:
                        continue
                    book_updated = book.get("last_update")

                    for market in book.get("markets", []):
                        m_key = market.get("key")
                        stat_type = MARKET_TO_STAT.get(m_key)
                        if not stat_type:
                            continue

                        for o in market.get("outcomes", []):
                            side = (o.get("name") or "").lower()
                            player = o.get("description")
                            point = o.get("point")
                            price = o.get("price")
                            if side not in ("over", "under") or not player or point is None or price is None:
                                continue
                            quotes.append(
                                OddsQuote(
                                    event_id=event_id,
                                    bookmaker_key=book_key,
                                    market_key=m_key,
                                    stat_type=stat_type,
                                    player_name=player,
                                    side=side,
                                    line=float(point),
                                    price_american=int(price),
                                    book_last_update=book_updated,
                                )
                            )
        except Exception as e:
            logger.error(f"OddsApiService: Error fetching props for event {event_id}: {e}")
            return []

        return quotes

    def get_slate_props_map(self) -> Dict[str, Dict[str, PropBetLine]]:
        """
        Consolidates live player props for the slate into one line per player/stat (see select_best_lines).
        Returns an empty dict when no key is configured or no book has posted lines; never invents lines.
        `last_fetch_live` tells callers whether the result came from live market data.
        """
        self.last_fetch_live = False

        if not self.is_configured:
            logger.warning("OddsApiService: API key not configured; no live lines available.")
            return {}

        quotes: List[OddsQuote] = []
        # Only query up to 2 events to conserve monthly quota (500 requests/mo limit)
        for event in self.fetch_upcoming_events()[:2]:
            event_id = event.get("id")
            if event_id:
                quotes.extend(self.fetch_event_prop_quotes(event_id))

        props_map = select_best_lines(quotes)
        if not props_map:
            logger.info("OddsApiService: No live player props posted (offseason/pre-slate).")
            return {}

        self.last_fetch_live = True
        return props_map

    def _update_quota(self, headers) -> None:
        """Parses API quota headers to monitor usage."""
        rem = headers.get("x-requests-remaining")
        used = headers.get("x-requests-used")
        if rem is not None:
            self.requests_remaining = int(rem)
        if used is not None:
            self.requests_used = int(used)
        if self.requests_remaining is not None:
            logger.info(f"OddsApiService: Quota Remaining: {self.requests_remaining} requests.")
