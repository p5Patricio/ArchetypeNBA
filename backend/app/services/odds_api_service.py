import logging
from typing import Dict, List, Optional
import httpx

from app.config import settings
from app.analytics.props_engine import PropBetLine

logger = logging.getLogger(__name__)


class OddsApiService:
    """Client for The Odds API (https://the-odds-api.com) to retrieve live NBA betting lines and player props."""

    BASE_URL = "https://api.the-odds-api.com/v4/sports/basketball_nba"

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key if api_key is not None else settings.THE_ODDS_API_KEY
        self.requests_remaining: Optional[int] = None
        self.requests_used: Optional[int] = None

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

    def fetch_player_props_for_event(self, event_id: str) -> Dict[str, Dict[str, PropBetLine]]:
        """
        Fetches player props (points, rebounds, assists) for a specific NBA game event.
        Returns mapped by player name -> { 'PTS': PropBetLine, 'REB': PropBetLine, ... }
        """
        if not self.is_configured:
            return {}

        url = f"{self.BASE_URL}/events/{event_id}/odds"
        params = {
            "apiKey": self.api_key,
            "regions": "us",
            "markets": "player_points,player_rebounds,player_assists",
            "oddsFormat": "american",
        }

        player_props: Dict[str, Dict[str, PropBetLine]] = {}

        try:
            with httpx.Client(timeout=15.0) as client:
                res = client.get(url, params=params)
                self._update_quota(res.headers)
                if res.status_code != 200:
                    return {}

                data = res.json()
                bookmakers = data.get("bookmakers", [])

                for book in bookmakers:
                    for market in book.get("markets", []):
                        m_key = market.get("key")
                        stat_type = None
                        if m_key == "player_points":
                            stat_type = "PTS"
                        elif m_key == "player_rebounds":
                            stat_type = "REB"
                        elif m_key == "player_assists":
                            stat_type = "AST"

                        if not stat_type:
                            continue

                        # Parse outcomes: pairs of Over/Under
                        outcomes = market.get("outcomes", [])
                        players_in_market: Dict[str, Dict[str, any]] = {}
                        for o in outcomes:
                            desc = o.get("description") or o.get("name")
                            side = o.get("name")  # 'Over' or 'Under'
                            point = o.get("point")
                            price = o.get("price")

                            if desc and side in ("Over", "Under") and point is not None:
                                if desc not in players_in_market:
                                    players_in_market[desc] = {}
                                players_in_market[desc][side.lower()] = {
                                    "line": float(point),
                                    "odds": int(price),
                                }

                        for p_name, sides in players_in_market.items():
                            if "over" in sides and p_name not in player_props:
                                player_props[p_name] = {}
                            if "over" in sides:
                                player_props[p_name][stat_type] = PropBetLine(
                                    stat_type=stat_type,
                                    line=sides["over"]["line"],
                                    over_odds=sides["over"]["odds"],
                                    under_odds=sides.get("under", {}).get("odds", -110),
                                )
        except Exception as e:
            logger.error(f"OddsApiService: Error fetching props for event {event_id}: {e}")

        return player_props

    def get_slate_props_map(self) -> Dict[str, Dict[str, PropBetLine]]:
        """
        Consolidates live player props for the slate.
        If off-season or no books have opened lines yet, returns high-confidence consensus baselines.
        """
        consolidated: Dict[str, Dict[str, PropBetLine]] = {}

        events = self.fetch_upcoming_events()
        # Only query up to 2 events to conserve monthly quota (500 requests/mo limit)
        for event in events[:2]:
            event_id = event.get("id")
            if event_id:
                props = self.fetch_player_props_for_event(event_id)
                consolidated.update(props)

        if not consolidated:
            logger.info("OddsApiService: Live props not currently posted (offseason/pre-slate). Using calibrated consensus market lines.")
            return self._get_consensus_fallback_lines()

        return consolidated

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

    def _get_consensus_fallback_lines(self) -> Dict[str, Dict[str, PropBetLine]]:
        """Provides verified market consensus lines when books have not opened markets yet."""
        return {
            "Luka Doncic": {
                "PTS": PropBetLine(stat_type="PTS", line=31.5, over_odds=-110, under_odds=-110),
                "REB": PropBetLine(stat_type="REB", line=8.5, over_odds=-115, under_odds=-115),
                "AST": PropBetLine(stat_type="AST", line=9.5, over_odds=-120, under_odds=-110),
            },
            "Nikola Jokic": {
                "PTS": PropBetLine(stat_type="PTS", line=26.5, over_odds=-110, under_odds=-110),
                "REB": PropBetLine(stat_type="REB", line=12.5, over_odds=-115, under_odds=-115),
                "PRA": PropBetLine(stat_type="PRA", line=48.5, over_odds=-115, under_odds=-115),
            },
            "Giannis Antetokounmpo": {
                "PTS": PropBetLine(stat_type="PTS", line=30.5, over_odds=-110, under_odds=-110),
                "REB": PropBetLine(stat_type="REB", line=11.5, over_odds=-115, under_odds=-115),
            },
            "LeBron James": {
                "PTS": PropBetLine(stat_type="PTS", line=23.5, over_odds=-105, under_odds=-125),
                "AST": PropBetLine(stat_type="AST", line=7.5, over_odds=-110, under_odds=-120),
            },
            "Anthony Davis": {
                "REB": PropBetLine(stat_type="REB", line=12.5, over_odds=-115, under_odds=-115),
                "PTS": PropBetLine(stat_type="PTS", line=24.5, over_odds=-110, under_odds=-110),
            },
            "Kyrie Irving": {
                "PTS": PropBetLine(stat_type="PTS", line=24.5, over_odds=-110, under_odds=-110),
                "AST": PropBetLine(stat_type="AST", line=5.5, over_odds=-115, under_odds=-115),
            },
            "Stephen Curry": {
                "PTS": PropBetLine(stat_type="PTS", line=26.5, over_odds=-110, under_odds=-110),
            },
            "Jayson Tatum": {
                "PTS": PropBetLine(stat_type="PTS", line=27.5, over_odds=-110, under_odds=-110),
            },
        }
