import logging
from collections import Counter
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
import httpx

from app.config import settings
from app.analytics.props_engine import PropBetLine, american_to_decimal

logger = logging.getLogger(__name__)

MARKET_TO_STAT = {
    "player_points": "PTS",
    "player_rebounds": "REB",
    "player_assists": "AST",
}


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

    def fetch_event_prop_quotes(self, event_id: str) -> List[OddsQuote]:
        """
        Fetches every player-prop quote (points, rebounds, assists) offered for an NBA event.
        One OddsQuote per bookmaker / market / player / side; nothing is merged or overwritten.
        """
        if not self.is_configured:
            return []

        url = f"{self.BASE_URL}/events/{event_id}/odds"
        params = {
            "apiKey": self.api_key,
            "regions": "us",
            "markets": ",".join(MARKET_TO_STAT),
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
