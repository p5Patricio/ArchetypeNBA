"""
HTTP client for the OddsPapi free tier (https://oddspapi.io/en/docs), with a request ledger and a hard monthly budget.

Verified with a capped live probe on 2026-11-07 (``odd/tasks/oddspapi.md``):

* Base ``https://api.oddspapi.io``, endpoints under ``/v4``, key as the ``apiKey`` query parameter.
* Free plan: ``request_limit`` 250 per month (``GET /v4/account``, resets on the 1st). Only the catalogue/listing
  endpoints are billed: ``/v4/historical-odds`` and ``/v4/account`` left ``request_count`` unchanged (7 historical
  calls including a 404 and a 304). When the quota is exhausted every endpoint but ``/v4/account`` answers 429.
* No quota headers exist; the only quota read-out is the body of ``/v4/account`` (free).
* Cooldowns per endpoint: historical odds 5 s (a 304 counts), fixtures 2 s, account/markets/tournaments 1 s.
* Finished fixtures carry an ``ETag``; ``If-None-Match`` returns 304 with an empty body.

Safety
* Every request is written to ``oddspapi_request`` before the response is parsed. A billable request is refused
  (``BudgetExceeded``, no network) when the billable rows of the current UTC month already reach the budget, so
  the budget holds across runs, processes and machines that share the database.
* The key never leaves this module: URLs are built by httpx from ``params`` (httpx INFO logs are silenced),
  exception texts are masked with ``mask_secret``, and the ledger stores the endpoint path only.
"""
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional

import httpx
from sqlalchemy import func, select
from sqlmodel import Session

from app.config import settings
from app.models import OddsPapiRequest

logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)  # httpx INFO lines print full URLs, key included

ENDPOINT_ACCOUNT = "/v4/account"
ENDPOINT_FIXTURES = "/v4/fixtures"
ENDPOINT_HISTORICAL = "/v4/historical-odds"
ENDPOINT_MARKETS = "/v4/markets"
ENDPOINT_TOURNAMENTS = "/v4/tournaments"

UNMETERED_ENDPOINTS = frozenset({ENDPOINT_ACCOUNT})
FREE_ENDPOINTS = frozenset({ENDPOINT_HISTORICAL})  # "always free" (docs) and verified 2026-11-07
COOLDOWN_SECONDS: Dict[str, float] = {
    ENDPOINT_HISTORICAL: 5.0,
    ENDPOINT_FIXTURES: 2.0,
    ENDPOINT_ACCOUNT: 1.0,
    ENDPOINT_MARKETS: 1.0,
    ENDPOINT_TOURNAMENTS: 1.0,
}
DEFAULT_COOLDOWN_SECONDS = 1.0
COOLDOWN_MARGIN_SECONDS = 0.5  # clock skew between us and the vendor
MAX_BOOKMAKERS_PER_CALL = 3
DEFAULT_TIMEOUT = httpx.Timeout(90.0, connect=15.0)  # a 3-book path is ~160 MB uncompressed

_KEY_PATTERN = re.compile(r"(apiKey=)[^&\s'\"]+", re.IGNORECASE)


def mask_secret(text: str, secret: Optional[str] = None) -> str:
    """Removes the key from any text (exception messages, URLs) before it is logged or raised."""
    masked = _KEY_PATTERN.sub(r"\1***", str(text))
    if secret:
        masked = masked.replace(secret, "***")
    return masked


def month_start_utc(now: datetime) -> datetime:
    now = now.astimezone(timezone.utc) if now.tzinfo else now.replace(tzinfo=timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


class OddsPapiError(Exception):
    """Any OddsPapi failure; the message is always masked."""


class BudgetExceeded(OddsPapiError):
    """The monthly budget of billable requests is used up; no request was sent."""


class QuotaExhausted(OddsPapiError):
    """The vendor answered 429 REQUEST_LIMIT_EXCEEDED (every endpoint but /v4/account is blocked)."""


@dataclass
class OddsPapiResponse:
    status_code: int
    data: object = None  # parsed JSON; None on 304 / 404
    etag: Optional[str] = None
    not_modified: bool = False
    response_bytes: int = 0

    @property
    def not_found(self) -> bool:
        return self.status_code == 404


# ------------------------------------------------------------------------------------------------ ledgers

class RequestLedger:
    """Where requests are counted. ``billable_since`` drives the budget; ``record`` is called for every request."""

    def billable_since(self, since: datetime) -> int:  # pragma: no cover - interface
        raise NotImplementedError

    def record(self, row: OddsPapiRequest) -> None:  # pragma: no cover - interface
        raise NotImplementedError


class DbRequestLedger(RequestLedger):
    """The ``oddspapi_request`` table; every row is committed at once so a crash cannot hide a spent request."""

    def __init__(self, session: Session):
        self.session = session

    def billable_since(self, since: datetime) -> int:
        return int(
            self.session.execute(
                select(func.count(OddsPapiRequest.id)).where(
                    OddsPapiRequest.billable.is_(True), OddsPapiRequest.requested_at >= since
                )
            ).scalar_one()
        )

    def record(self, row: OddsPapiRequest) -> None:
        self.session.add(row)
        self.session.commit()


class MemoryLedger(RequestLedger):
    """In-memory ledger for tests and throwaway runs."""

    def __init__(self, rows: Optional[List[OddsPapiRequest]] = None):
        self.rows: List[OddsPapiRequest] = list(rows or [])

    def billable_since(self, since: datetime) -> int:
        def aware(v: datetime) -> datetime:
            return v if v.tzinfo else v.replace(tzinfo=timezone.utc)

        return sum(1 for r in self.rows if r.billable and aware(r.requested_at) >= since)

    def record(self, row: OddsPapiRequest) -> None:
        self.rows.append(row)


# ------------------------------------------------------------------------------------------------ client

class OddsPapiClient:
    def __init__(
        self,
        ledger: RequestLedger,
        *,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        monthly_budget: Optional[int] = None,
        historical_billable: Optional[bool] = None,
        transport: Optional[httpx.BaseTransport] = None,
        timeout: httpx.Timeout = DEFAULT_TIMEOUT,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        source: str = "",
        max_requests: Optional[int] = None,
    ):
        self.ledger = ledger
        self._api_key = (settings.ODDSPAPI_API_KEY if api_key is None else api_key) or ""
        self.base_url = (base_url or settings.ODDSPAPI_BASE_URL).rstrip("/")
        self.monthly_budget = int(settings.ODDSPAPI_MONTHLY_BUDGET if monthly_budget is None else monthly_budget)
        self.historical_billable = bool(
            settings.ODDSPAPI_HISTORICAL_BILLABLE if historical_billable is None else historical_billable
        )
        self._transport = transport
        self._timeout = timeout
        self._clock = clock
        self._sleep = sleep
        self._now = now
        self.source = source
        self.max_requests = max_requests  # per client instance (one run), billable or not
        self.requests_sent = 0
        self.billable_sent = 0
        self._last_call: Dict[str, float] = {}

    # ---------------------------------------------------------------- state

    @property
    def is_configured(self) -> bool:
        key = self._api_key
        return bool(key) and "your_" not in key

    def is_billable(self, endpoint: str) -> bool:
        if endpoint in UNMETERED_ENDPOINTS:
            return False
        if endpoint in FREE_ENDPOINTS:
            return self.historical_billable
        return True

    def billable_used_this_month(self) -> int:
        return self.ledger.billable_since(month_start_utc(self._now()))

    def billable_remaining(self) -> int:
        return max(0, self.monthly_budget - self.billable_used_this_month())

    def mask(self, text: str) -> str:
        return mask_secret(text, self._api_key)

    # ---------------------------------------------------------------- endpoints

    def account(self) -> Dict[str, Optional[int]]:
        """request_limit / request_count of the active subscription (unmetered, works after the quota is spent)."""
        resp = self._get(ENDPOINT_ACCOUNT, {})
        data = resp.data if isinstance(resp.data, dict) else {}
        subs = [s for s in data.get("subscriptions") or [] if isinstance(s, dict)]
        active = [s for s in subs if s.get("is_active")] or subs
        sub = active[0] if active else {}
        out = {"request_limit": sub.get("request_limit"), "request_count": sub.get("request_count")}
        if out["request_limit"] is not None:
            self._annotate_last(out)
        return out

    def list_fixtures(self, tournament_id: int, start: datetime, end: datetime, label: Optional[str] = None) -> List[dict]:
        params = {
            "tournamentId": str(tournament_id),
            "from": start.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "to": end.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        resp = self._get(ENDPOINT_FIXTURES, params, label=label)
        if resp.not_found or resp.data is None:
            return []
        if not isinstance(resp.data, list):
            raise OddsPapiError(f"unexpected fixtures payload type {type(resp.data).__name__}")
        return [f for f in resp.data if isinstance(f, dict)]

    def historical_odds(self, fixture_id: str, bookmakers: List[str], etag: Optional[str] = None) -> OddsPapiResponse:
        books = [b for b in bookmakers if b]
        if not books or len(books) > MAX_BOOKMAKERS_PER_CALL:
            raise ValueError(f"historical odds take 1..{MAX_BOOKMAKERS_PER_CALL} bookmakers, got {len(books)}")
        headers = {"If-None-Match": etag} if etag else None
        return self._get(ENDPOINT_HISTORICAL, {"fixtureId": fixture_id, "bookmakers": ",".join(books)},
                         headers=headers, fixture_id=fixture_id)

    # ---------------------------------------------------------------- transport

    def _respect_cooldown(self, endpoint: str) -> None:
        last = self._last_call.get(endpoint)
        if last is None:
            return
        gap = COOLDOWN_SECONDS.get(endpoint, DEFAULT_COOLDOWN_SECONDS) + COOLDOWN_MARGIN_SECONDS
        wait = last + gap - self._clock()
        if wait > 0:
            self._sleep(wait)

    def _annotate_last(self, account: Dict[str, Optional[int]]) -> None:
        row = getattr(self, "_last_row", None)
        if row is not None:
            row.vendor_request_limit = account.get("request_limit")
            row.vendor_request_count = account.get("request_count")
            try:
                self.ledger.record(row)  # re-save with the quota fields (same object: an update, not a new row)
            except Exception:  # the annotation is informational
                logger.warning("oddspapi: could not annotate the account request with the vendor quota")

    def _get(
        self,
        endpoint: str,
        params: Dict[str, str],
        headers: Optional[Dict[str, str]] = None,
        fixture_id: Optional[str] = None,
        label: Optional[str] = None,
    ) -> OddsPapiResponse:
        if not self.is_configured:
            raise OddsPapiError("ODDSPAPI_API_KEY is not configured")
        if self.max_requests is not None and self.requests_sent >= self.max_requests:
            raise BudgetExceeded(f"per-run request cap reached ({self.max_requests})")
        billable = self.is_billable(endpoint)
        if billable:
            used = self.billable_used_this_month()
            if used + 1 > self.monthly_budget:
                raise BudgetExceeded(
                    f"monthly OddsPapi budget reached: {used} of {self.monthly_budget} billable requests this month"
                )
        self._respect_cooldown(endpoint)

        row = OddsPapiRequest(
            requested_at=self._now(), endpoint=endpoint, billable=billable, fixture_id=fixture_id, label=label,
            source=self.source,
        )
        self.requests_sent += 1
        if billable:
            self.billable_sent += 1
        response: Optional[httpx.Response] = None
        try:
            with httpx.Client(transport=self._transport, timeout=self._timeout) as http:
                response = http.get(
                    f"{self.base_url}{endpoint}", params={**params, "apiKey": self._api_key}, headers=headers
                )
        except httpx.HTTPError as exc:
            # The vendor may or may not have counted it: the ledger keeps it (billable rows count, conservatively).
            self._finish(endpoint, row)
            raise OddsPapiError(self.mask(f"{endpoint} request failed: {type(exc).__name__}: {exc}")) from None
        row.status_code = response.status_code
        row.response_bytes = len(response.content)
        self._finish(endpoint, row)

        status = response.status_code
        etag = response.headers.get("etag")
        if status == 304:
            return OddsPapiResponse(304, None, etag, not_modified=True)
        if status == 404:
            return OddsPapiResponse(404, None, etag, response_bytes=row.response_bytes or 0)
        if status == 429:
            raise QuotaExhausted(self.mask(f"{endpoint}: 429 request limit exceeded: {response.text[:200]}"))
        if status >= 400:
            raise OddsPapiError(self.mask(f"{endpoint}: HTTP {status}: {response.text[:200]}"))
        try:
            data = response.json()
        except ValueError:
            raise OddsPapiError(f"{endpoint}: response is not JSON") from None
        return OddsPapiResponse(status, data, etag, response_bytes=row.response_bytes or 0)

    def _finish(self, endpoint: str, row: OddsPapiRequest) -> None:
        self._last_call[endpoint] = self._clock()
        self._last_row = row
        self.ledger.record(row)
