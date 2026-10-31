"""
Client and parser for the SportsGameOdds API (https://sportsgameodds.com).

Second odds feed providing game lines (moneyline, spreads, totals) across US bookmakers
on the free Amateur plan (2,500 objects/month, 10 requests/minute, no Pinnacle).
Disabled by default until SPORTSGAMEODDS_API_KEY is configured with a valid key.
"""
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import httpx

from app.config import settings
from app.models import BetSide, MarketType
from app.services.odds_api_service import GameQuote, OddsQuote

logger = logging.getLogger(__name__)

# Keep httpx logging quiet so API keys or parameters are not logged to stdout/files
logging.getLogger("httpx").setLevel(logging.WARNING)

FREE_TIER_MONTHLY_OBJECT_LIMIT = 2500

# Nine US books visible on the SGO Amateur tier (NO Pinnacle)
SGO_ALLOWED_BOOKS = {
    "draftkings",
    "fanduel",
    "betmgm",
    "caesars",
    "espnbet",
    "bovada",
    "pointsbet",
    "unibet",
    "williamhill",
}

# Mapping of SGO prop statID to MarketType key
SGO_PROP_STAT_MAP = {
    "points": "player_points",
    "rebounds": "player_rebounds",
    "assists": "player_assists",
    "points_rebounds_assists": "player_pra",
    "pra": "player_pra",
}


@dataclass(frozen=True)
class ConsensusQuote:
    """Consensus quote (fair price and book average price) for a main game market."""
    event_id: str
    home_team: str
    away_team: str
    commence_time: str
    market: MarketType
    side: BetSide
    line: Optional[float]
    fair_price_american: int
    book_price_american: Optional[int]

# Mapping of bookmakerID strings to canonical display titles
BOOKMAKER_TITLES: Dict[str, str] = {
    "draftkings": "DraftKings",
    "fanduel": "FanDuel",
    "betmgm": "BetMGM",
    "caesars": "Caesars",
    "espnbet": "ESPN BET",
    "bovada": "Bovada",
    "unibet": "Unibet",
    "pointsbet": "PointsBet",
    "williamhill": "William Hill",
    "betrivers": "BetRivers",
    "pinnacle": "Pinnacle",
    "bet365": "Bet365",
    "fanatics": "Fanatics",
    "ballybet": "Bally Bet",
    "betparx": "betPARX",
    "hardrockbet": "Hard Rock Bet",
    "circa": "Circa Sports",
    "fliff": "Fliff",
    "betonline": "BetOnline",
    "lowvig": "LowVig",
    "boylesports": "BoyleSports",
    "1xbet": "1xBet",
    "tipico": "Tipico",
    "betus": "BetUS",
    "coral": "Coral",
    "ladbrokes": "Ladbrokes",
    "paddypower": "Paddy Power",
    "skybet": "Sky Bet",
    "betway": "Betway",
    "nordicbet": "NordicBet",
    "betsson": "Betsson",
    "leovegas": "LeoVegas",
    "casumo": "Casumo",
}


class InsufficientQuotaError(Exception):
    """Raised when an operation would breach the remaining object quota floor."""


def mask_key(key: Optional[str]) -> str:
    """Masks an API key for safe logging (e.g. 'sgo_abc123xyz' -> 'sgo...xyz')."""
    if not key:
        return ""
    if len(key) <= 8:
        return "***"
    return f"{key[:3]}...{key[-3:]}"


def sanitize_message(msg: str, key: Optional[str]) -> str:
    """Replaces any occurrence of the unmasked key in an error or log string."""
    if not key:
        return msg
    return msg.replace(key, mask_key(key))


def american_to_decimal(american_odds: int) -> float:
    """
    Converts American odds (-110, +130) to decimal odds (1.909, 2.30).
    Follows standard sports betting conversion.
    """
    if american_odds > 0:
        return round((american_odds / 100.0) + 1.0, 3)
    elif american_odds < 0:
        return round((100.0 / abs(american_odds)) + 1.0, 3)
    return 1.0


def _aware_utc(value: datetime) -> datetime:
    """Ensures a datetime is timezone-aware and set to UTC."""
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _get_usage_cache_path() -> Path:
    """Locates or creates the persistence path for usage tracking in logs/."""
    app_dir = Path(__file__).resolve().parent.parent.parent
    logs_dir = app_dir.parent / "logs"
    if not logs_dir.exists():
        logs_dir.mkdir(parents=True, exist_ok=True)
    return logs_dir / "sportsgameodds_usage.json"


def _read_local_usage(cache_path: Optional[Path] = None) -> Dict[str, Any]:
    path = cache_path or _get_usage_cache_path()
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"SportsGameOdds: Could not read usage cache: {e}")
    current_month = datetime.now(timezone.utc).strftime("%Y-%m")
    return {
        "month": current_month,
        "objects_used": 0,
        "objects_remaining": FREE_TIER_MONTHLY_OBJECT_LIMIT,
        "last_updated": None,
    }


def _write_local_usage(data: Dict[str, Any], cache_path: Optional[Path] = None) -> None:
    path = cache_path or _get_usage_cache_path()
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.warning(f"SportsGameOdds: Could not write usage cache: {e}")


def parse_american_odds(raw: Any) -> Optional[int]:
    """Parses an American odds value (string, float, or int, e.g. '-112', '+105') into int."""
    if raw is None:
        return None
    try:
        s = str(raw).strip()
        if not s:
            return None
        if s.startswith("+"):
            s = s[1:]
        val = int(float(s))
        if -100 < val < 100:
            return None
        return val
    except (ValueError, TypeError, OverflowError):
        return None


def parse_float_line(raw: Any) -> Optional[float]:
    """Parses a point spread or over/under line into float."""
    if raw is None:
        return None
    try:
        s = str(raw).strip()
        if not s:
            return None
        if s.startswith("+"):
            s = s[1:]
        return float(s)
    except (ValueError, TypeError):
        return None


def parse_sgo_events(payload: Any, sgo_book_prefix: bool = False) -> List[GameQuote]:
    """
    Parses a SportsGameOdds /events response payload into GameQuote instances.
    Skips missing, incomplete or malformed odds without raising.
    Only extracts full game / regulation quotes for main markets:
      - 'ml' (h2h): statID points, statEntityID in ('home', 'away'), sideID in ('home', 'away')
      - 'sp' (spreads): statID points, statEntityID in ('home', 'away'), sideID in ('home', 'away')
      - 'ou' (totals): statID points, periodID game/reg, statEntityID 'all', sideID in ('over', 'under')
    Excludes team totals, player props, partial periods (1h, 1q), eo, and ml3way.
    If sgo_book_prefix is True, filters to SGO_ALLOWED_BOOKS and prefixes bookmaker_key with 'sgo_'.
    """
    quotes: List[GameQuote] = []
    if not isinstance(payload, dict):
        return quotes

    data = payload.get("data")
    if not isinstance(data, list):
        return quotes

    for event in data:
        if not isinstance(event, dict):
            continue

        event_id = event.get("eventID")
        status = event.get("status") or {}
        commence = status.get("startsAt")
        teams = event.get("teams") or {}
        home_node = teams.get("home") or {}
        away_node = teams.get("away") or {}

        # Resolve team display names (prefer long, then medium, then short/teamID)
        home_names = home_node.get("names") or {}
        away_names = away_node.get("names") or {}
        home_team = (
            home_names.get("long")
            or home_names.get("medium")
            or home_names.get("short")
            or home_node.get("teamID")
        )
        away_team = (
            away_names.get("long")
            or away_names.get("medium")
            or away_names.get("short")
            or away_node.get("teamID")
        )

        if not (event_id and commence and home_team and away_team):
            continue

        odds_dict = event.get("odds")
        if not isinstance(odds_dict, dict):
            continue

        for odd_id, odd_obj in odds_dict.items():
            if not isinstance(odd_obj, dict):
                continue

            # Check periodID and statID: must be primary scoring stat (points) for full game or regulation
            period_id = odd_obj.get("periodID")
            bet_type_id = odd_obj.get("betTypeID")
            stat_id = odd_obj.get("statID")
            side_id = odd_obj.get("sideID")
            stat_entity_id = odd_obj.get("statEntityID")

            # Fallback to parsing odd_id if fields omitted: {statID}-{statEntityID}-{periodID}-{betTypeID}-{sideID}
            if not (period_id and bet_type_id and stat_id and stat_entity_id and side_id):
                parts = odd_id.split("-")
                if len(parts) >= 5:
                    stat_id = stat_id or parts[0]
                    stat_entity_id = stat_entity_id or parts[1]
                    period_id = period_id or parts[2]
                    bet_type_id = bet_type_id or parts[3]
                    side_id = side_id or parts[4]

            # Primary scoring stat is points (game lines). Skip non-point props (e.g. weightedCards, cornerKicks)
            if stat_id != "points":
                continue

            # Full game ('game') or regulation ('reg' for soccer/3-way). Skip sub-periods (1h, 1q, etc.)
            if period_id not in ("game", "reg"):
                continue

            # Determine market and side (main markets only; excludes team totals, player props, eo, ml3way)
            market_key: str
            side: str
            if bet_type_id == "ml":
                if stat_entity_id not in ("home", "away"):
                    continue
                if side_id not in ("home", "away"):
                    continue
                market_key = "h2h"
                side = side_id
            elif bet_type_id == "sp":
                if stat_entity_id not in ("home", "away"):
                    continue
                if side_id not in ("home", "away"):
                    continue
                market_key = "spreads"
                side = side_id
            elif bet_type_id == "ou":
                if stat_entity_id != "all":
                    continue
                if side_id not in ("over", "under"):
                    continue
                market_key = "totals"
                side = side_id
            else:
                continue

            by_book = odd_obj.get("byBookmaker")
            if not isinstance(by_book, dict):
                continue

            for book_key, b_info in by_book.items():
                if not isinstance(b_info, dict):
                    continue

                avail = b_info.get("available")
                if not (avail is True or str(avail).lower() == "true"):
                    continue

                book_key_clean = str(book_key).lower().strip()
                if sgo_book_prefix and book_key_clean not in SGO_ALLOWED_BOOKS:
                    continue

                price_american = parse_american_odds(b_info.get("odds"))
                if price_american is None:
                    continue

                line: Optional[float] = None
                if market_key == "spreads":
                    line = parse_float_line(b_info.get("spread"))
                    if line is None:
                        line = parse_float_line(odd_obj.get("bookSpread") or odd_obj.get("fairSpread"))
                    if line is None:
                        continue
                elif market_key == "totals":
                    line = parse_float_line(b_info.get("overUnder"))
                    if line is None:
                        line = parse_float_line(odd_obj.get("bookOverUnder") or odd_obj.get("fairOverUnder"))
                    if line is None:
                        continue

                title = BOOKMAKER_TITLES.get(book_key_clean, book_key_clean.replace("_", " ").title())
                if sgo_book_prefix:
                    final_book_key = f"sgo_{book_key_clean}"
                    final_book_title = f"{title} (SportsGameOdds)"
                else:
                    final_book_key = book_key_clean
                    final_book_title = title

                book_last_update = b_info.get("lastUpdatedAt") or b_info.get("last_updated_at")

                quotes.append(
                    GameQuote(
                        event_id=str(event_id),
                        commence_time=str(commence),
                        home_team=str(home_team),
                        away_team=str(away_team),
                        bookmaker_key=final_book_key,
                        bookmaker_title=final_book_title,
                        market_key=market_key,
                        side=side,
                        line=line,
                        price_american=price_american,
                        book_last_update=str(book_last_update) if book_last_update else None,
                    )
                )

    return quotes


def parse_sgo_props(payload: Any, sgo_book_prefix: bool = True) -> List[OddsQuote]:
    """
    Parses player prop quotes (points, rebounds, assists, pra) from an SGO payload.
    Resolves player name from event.players[playerID].name.
    """
    quotes: List[OddsQuote] = []
    if not isinstance(payload, dict):
        return quotes

    data = payload.get("data")
    if not isinstance(data, list):
        return quotes

    for event in data:
        if not isinstance(event, dict):
            continue

        event_id = event.get("eventID")
        if not event_id:
            continue

        players_map = event.get("players")
        if not isinstance(players_map, dict):
            continue

        odds_dict = event.get("odds")
        if not isinstance(odds_dict, dict):
            continue

        for odd_id, odd_obj in odds_dict.items():
            if not isinstance(odd_obj, dict):
                continue

            period_id = odd_obj.get("periodID")
            bet_type_id = odd_obj.get("betTypeID")
            stat_id = odd_obj.get("statID")
            side_id = odd_obj.get("sideID")
            stat_entity_id = odd_obj.get("statEntityID")

            if not (period_id and bet_type_id and stat_id and stat_entity_id and side_id):
                parts = odd_id.split("-")
                if len(parts) >= 5:
                    stat_id = stat_id or parts[0]
                    stat_entity_id = stat_entity_id or parts[1]
                    period_id = period_id or parts[2]
                    bet_type_id = bet_type_id or parts[3]
                    side_id = side_id or parts[4]

            if stat_id not in SGO_PROP_STAT_MAP:
                continue
            market_key = SGO_PROP_STAT_MAP[stat_id]

            if period_id not in ("game", "reg"):
                continue

            if bet_type_id != "ou":
                continue

            if side_id not in ("over", "under"):
                continue

            if stat_entity_id in ("home", "away", "all"):
                continue

            player_entry = players_map.get(stat_entity_id)
            if not isinstance(player_entry, dict):
                continue
            player_name = player_entry.get("name")
            if not player_name:
                first = player_entry.get("firstName") or ""
                last = player_entry.get("lastName") or ""
                player_name = f"{first} {last}".strip()
            if not player_name:
                continue

            by_book = odd_obj.get("byBookmaker")
            if not isinstance(by_book, dict):
                continue

            for book_key, b_info in by_book.items():
                if not isinstance(b_info, dict):
                    continue

                avail = b_info.get("available")
                if not (avail is True or str(avail).lower() == "true"):
                    continue

                book_key_clean = str(book_key).lower().strip()
                if sgo_book_prefix and book_key_clean not in SGO_ALLOWED_BOOKS:
                    continue

                price_american = parse_american_odds(b_info.get("odds"))
                if price_american is None:
                    continue

                line = parse_float_line(b_info.get("overUnder"))
                if line is None:
                    line = parse_float_line(odd_obj.get("bookOverUnder") or odd_obj.get("fairOverUnder"))
                if line is None:
                    continue

                book_last_update = b_info.get("lastUpdatedAt") or b_info.get("last_updated_at")
                final_book_key = f"sgo_{book_key_clean}" if sgo_book_prefix else book_key_clean

                quotes.append(
                    OddsQuote(
                        event_id=str(event_id),
                        bookmaker_key=final_book_key,
                        market_key=market_key,
                        stat_type=stat_id,
                        player_name=player_name,
                        side=side_id,
                        line=line,
                        price_american=price_american,
                        book_last_update=str(book_last_update) if book_last_update else None,
                    )
                )

    return quotes


def parse_sgo_consensus(payload: Any) -> List[ConsensusQuote]:
    """
    Parses market consensus quotes (fairOdds, bookOdds) for MAIN game markets (h2h, spreads, totals).
    Consensus rows are stored in market_consensus_snapshot, NEVER in odds_history.
    """
    quotes: List[ConsensusQuote] = []
    if not isinstance(payload, dict):
        return quotes

    data = payload.get("data")
    if not isinstance(data, list):
        return quotes

    for event in data:
        if not isinstance(event, dict):
            continue

        event_id = event.get("eventID")
        status = event.get("status") or {}
        commence = status.get("startsAt")
        teams = event.get("teams") or {}
        home_node = teams.get("home") or {}
        away_node = teams.get("away") or {}
        home_names = home_node.get("names") or {}
        away_names = away_node.get("names") or {}
        home_team = (
            home_names.get("long")
            or home_names.get("medium")
            or home_names.get("short")
            or home_node.get("teamID")
        )
        away_team = (
            away_names.get("long")
            or away_names.get("medium")
            or away_names.get("short")
            or away_node.get("teamID")
        )

        if not (event_id and commence and home_team and away_team):
            continue

        odds_dict = event.get("odds")
        if not isinstance(odds_dict, dict):
            continue

        for odd_id, odd_obj in odds_dict.items():
            if not isinstance(odd_obj, dict):
                continue

            stat_id = odd_obj.get("statID")
            period_id = odd_obj.get("periodID")
            bet_type_id = odd_obj.get("betTypeID")
            side_id = odd_obj.get("sideID")
            stat_entity_id = odd_obj.get("statEntityID")

            if not (period_id and bet_type_id and stat_id and stat_entity_id and side_id):
                parts = odd_id.split("-")
                if len(parts) >= 5:
                    stat_id = stat_id or parts[0]
                    stat_entity_id = stat_entity_id or parts[1]
                    period_id = period_id or parts[2]
                    bet_type_id = bet_type_id or parts[3]
                    side_id = side_id or parts[4]

            if stat_id != "points" or period_id not in ("game", "reg"):
                continue

            market: MarketType
            side: BetSide
            line: Optional[float] = None

            if bet_type_id == "ml":
                if stat_entity_id not in ("home", "away") or side_id not in ("home", "away"):
                    continue
                market = MarketType.h2h
                side = BetSide.home if side_id == "home" else BetSide.away
            elif bet_type_id == "sp":
                if stat_entity_id not in ("home", "away") or side_id not in ("home", "away"):
                    continue
                market = MarketType.spreads
                side = BetSide.home if side_id == "home" else BetSide.away
                line = parse_float_line(odd_obj.get("fairSpread") or odd_obj.get("bookSpread"))
                if line is None:
                    continue
            elif bet_type_id == "ou":
                if stat_entity_id != "all" or side_id not in ("over", "under"):
                    continue
                market = MarketType.totals
                side = BetSide.over if side_id == "over" else BetSide.under
                line = parse_float_line(odd_obj.get("fairOverUnder") or odd_obj.get("bookOverUnder"))
                if line is None:
                    continue
            else:
                continue

            fair_price = parse_american_odds(odd_obj.get("fairOdds"))
            if fair_price is None:
                continue

            book_price = parse_american_odds(odd_obj.get("bookOdds"))

            quotes.append(
                ConsensusQuote(
                    event_id=str(event_id),
                    home_team=str(home_team),
                    away_team=str(away_team),
                    commence_time=str(commence),
                    market=market,
                    side=side,
                    line=line,
                    fair_price_american=fair_price,
                    book_price_american=book_price,
                )
            )

    return quotes


class SportsGameOddsService:
    """
    Client for the SportsGameOdds API (v2).
    Implements OddsProvider protocol.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        min_remaining_objects: Optional[int] = None,
        transport: Optional[httpx.BaseTransport] = None,
        usage_cache_path: Optional[Path] = None,
    ):
        self.api_key = api_key if api_key is not None else settings.SPORTSGAMEODDS_API_KEY
        self.base_url = (base_url or settings.SPORTSGAMEODDS_BASE_URL).rstrip("/")
        self.min_remaining_objects = (
            min_remaining_objects
            if min_remaining_objects is not None
            else settings.SPORTSGAMEODDS_MIN_REMAINING_OBJECTS
        )
        self.transport = transport
        self.usage_cache_path = usage_cache_path
        self.last_call_ok: bool = False
        self.objects_remaining: Optional[int] = None

    @property
    def name(self) -> str:
        return "sportsgameodds"

    @property
    def is_configured(self) -> bool:
        """Disabled when key is empty or contains 'your_' placeholder."""
        return bool(self.api_key and "your_" not in self.api_key)

    def _client(self) -> httpx.Client:
        headers = {}
        if self.api_key:
            headers["x-api-key"] = self.api_key
        return httpx.Client(
            base_url=self.base_url,
            headers=headers,
            timeout=30.0,
            transport=self.transport,
        )

    def _execute_with_retry(self, method: str, path: str, params: Optional[Dict[str, Any]] = None) -> Optional[httpx.Response]:
        """Sends an HTTP request with timeout 30s and exactly one retry on transient failure."""
        client = self._client()
        clean_params = dict(params or {})
        # Also provide apiKey in params if requested by API, while header is set
        if self.api_key and "apiKey" not in clean_params:
            clean_params["apiKey"] = self.api_key

        last_exc: Optional[Exception] = None
        for attempt in (1, 2):
            try:
                res = client.request(method, path, params=clean_params)
                if res.status_code >= 500 and attempt == 1:
                    logger.warning(f"SportsGameOdds: Server returned {res.status_code}; retrying once...")
                    continue
                return res
            except (httpx.RequestError, httpx.TimeoutException) as exc:
                last_exc = exc
                if attempt == 1:
                    masked_exc = sanitize_message(str(exc), self.api_key)
                    logger.warning(f"SportsGameOdds: Transient error ({masked_exc}); retrying once...")
                    continue

        if last_exc:
            masked = sanitize_message(str(last_exc), self.api_key)
            logger.error(f"SportsGameOdds: Request failed after retry: {masked}")
        return None

    def fetch_account_usage(self) -> Optional[Dict[str, Any]]:
        """
        Calls GET /account/usage (free utility endpoint) to verify remaining objects.
        Returns data dictionary if successful; does not count against quota.
        """
        if not self.is_configured:
            return None

        res = self._execute_with_retry("GET", "/account/usage")
        if res and res.status_code == 200:
            try:
                body = res.json()
                if body.get("success") and "data" in body:
                    data = body["data"]
                    rem = data.get("objectsRemainingThisMonth")
                    if rem is None and isinstance(data.get("rateLimits"), dict):
                        month_limits = data["rateLimits"].get("per-month") or {}
                        max_ent = month_limits.get("max-entities")
                        cur_ent = month_limits.get("current-entities")
                        if isinstance(max_ent, (int, float)) and isinstance(cur_ent, (int, float)):
                            rem = int(max_ent - cur_ent)
                    if rem is not None:
                        self.objects_remaining = int(rem)
                        local = _read_local_usage(self.usage_cache_path)
                        local["objects_remaining"] = self.objects_remaining
                        local["last_updated"] = datetime.now(timezone.utc).isoformat()
                        _write_local_usage(local, self.usage_cache_path)
                    return data
            except Exception as e:
                logger.warning(f"SportsGameOdds: Error parsing /account/usage response: {e}")
        return None

    def check_quota(self, expected_objects: int = 1) -> Tuple[bool, str]:
        """
        Evaluates whether an upcoming request would violate the remaining objects floor.
        Checks cached API usage first, then falls back to local tracking.
        """
        # Read local tracking
        current_month = datetime.now(timezone.utc).strftime("%Y-%m")
        local = _read_local_usage(self.usage_cache_path)
        if local.get("month") != current_month:
            local = {
                "month": current_month,
                "objects_used": 0,
                "objects_remaining": FREE_TIER_MONTHLY_OBJECT_LIMIT,
                "last_updated": None,
            }
            _write_local_usage(local, self.usage_cache_path)

        remaining = self.objects_remaining
        if remaining is None:
            remaining = local.get("objects_remaining", FREE_TIER_MONTHLY_OBJECT_LIMIT)

        if remaining - expected_objects < self.min_remaining_objects:
            reason = (
                f"Remaining objects ({remaining}) after call would fall below floor "
                f"({self.min_remaining_objects})."
            )
            return False, reason
        return True, "OK"

    def record_objects_consumed(self, count: int) -> None:
        """Updates local accounting counter after events have been received."""
        current_month = datetime.now(timezone.utc).strftime("%Y-%m")
        local = _read_local_usage(self.usage_cache_path)
        if local.get("month") != current_month:
            local = {
                "month": current_month,
                "objects_used": 0,
                "objects_remaining": FREE_TIER_MONTHLY_OBJECT_LIMIT,
                "last_updated": None,
            }
            self.objects_remaining = FREE_TIER_MONTHLY_OBJECT_LIMIT

        used = local.get("objects_used", 0) + count
        local["objects_used"] = used

        current_rem = (
            self.objects_remaining
            if self.objects_remaining is not None
            else local.get("objects_remaining", FREE_TIER_MONTHLY_OBJECT_LIMIT)
        )
        new_rem = max(0, current_rem - count)
        self.objects_remaining = new_rem
        local["objects_remaining"] = new_rem
        local["last_updated"] = datetime.now(timezone.utc).isoformat()
        _write_local_usage(local, self.usage_cache_path)

    def fetch_game_lines(
        self,
        bookmakers: Optional[Sequence[str]] = None,
        limit: int = 20,
    ) -> List[GameQuote]:
        """
        Fetches upcoming NBA game lines (moneyline, spreads, totals).
        Returns empty list when unconfigured, when quota floor is breached, or on error.
        """
        self.last_call_ok = False
        if not self.is_configured:
            logger.debug("SportsGameOddsService: Not configured (missing or placeholder key).")
            return []

        # Check quota floor
        allowed, reason = self.check_quota(expected_objects=1)
        if not allowed:
            logger.warning(f"SportsGameOddsService: Quota guard blocked fetch: {reason}")
            raise InsufficientQuotaError(reason)

        params: Dict[str, Any] = {
            "leagueID": "NBA",
            "oddsAvailable": "true",
            "limit": limit,
        }
        if bookmakers:
            params["bookmakerID"] = ",".join(bookmakers)

        res = self._execute_with_retry("GET", "/events", params=params)
        if res is None:
            return []

        if res.status_code != 200:
            msg = sanitize_message(f"HTTP {res.status_code}: {res.text}", self.api_key)
            logger.error(f"SportsGameOddsService: Error fetching events: {msg}")
            return []

        try:
            payload = res.json()
        except Exception as e:
            logger.error(f"SportsGameOddsService: Failed to parse JSON response: {e}")
            return []

        if isinstance(payload, dict):
            notice = payload.get("notice")
            if notice:
                sanitized_notice = sanitize_message(str(notice), self.api_key)
                logger.info(f"SportsGameOddsService notice: {sanitized_notice}")

        quotes = parse_sgo_events(payload)
        events_returned = len(payload.get("data") or [])
        if events_returned > 0:
            self.record_objects_consumed(events_returned)

        self.last_call_ok = True
        return quotes

    def fetch_daily_events(
        self,
        now: Optional[datetime] = None,
        max_objects: int = 30,
    ) -> Tuple[List[dict], int]:
        """
        Fetches upcoming NBA events for the next 36 hours using cursor pagination.
        Enforces daily max_objects budget and monthly remaining objects floor.
        Returns (list_of_event_dicts, objects_consumed).
        """
        self.last_call_ok = False
        if not self.is_configured:
            logger.debug("SportsGameOddsService: Not configured; skipping daily fetch.")
            return [], 0

        now_utc = _aware_utc(now) if now is not None else datetime.now(timezone.utc)
        starts_after = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        starts_before = (now_utc + timedelta(hours=36)).strftime("%Y-%m-%dT%H:%M:%SZ")

        params: Dict[str, Any] = {
            "leagueID": "NBA",
            "oddsAvailable": "true",
            "startsAfter": starts_after,
            "startsBefore": starts_before,
            "limit": 50,
        }

        all_events: List[dict] = []
        total_consumed = 0
        cursor: Optional[str] = None

        while len(all_events) < max_objects:
            allowed, reason = self.check_quota(expected_objects=1)
            if not allowed:
                logger.warning(f"SportsGameOddsService: Quota guard stopped daily fetch: {reason}")
                break

            page_params = dict(params)
            if cursor:
                page_params["cursor"] = cursor

            res = self._execute_with_retry("GET", "/events", params=page_params)
            if res is None:
                break
            if res.status_code != 200:
                msg = sanitize_message(f"HTTP {res.status_code}: {res.text}", self.api_key)
                logger.error(f"SportsGameOddsService: Error fetching daily events: {msg}")
                break

            try:
                payload = res.json()
            except Exception as e:
                logger.error(f"SportsGameOddsService: Failed to parse daily events JSON: {e}")
                break

            if isinstance(payload, dict):
                notice = payload.get("notice")
                if notice:
                    logger.info(f"SportsGameOddsService notice: {sanitize_message(str(notice), self.api_key)}")

            data = payload.get("data") if isinstance(payload, dict) else None
            if not isinstance(data, list) or not data:
                break

            batch_count = len(data)
            self.record_objects_consumed(batch_count)
            total_consumed += batch_count

            for event in data:
                if isinstance(event, dict):
                    all_events.append(event)
                    if len(all_events) >= max_objects:
                        break

            next_cursor = payload.get("nextCursor")
            if not next_cursor or next_cursor == cursor:
                break
            cursor = str(next_cursor)

        self.last_call_ok = True
        return all_events, total_consumed
