# SportsGameOdds Documentation Example Fixtures

These fixtures contain example JSON responses extracted verbatim from the official SportsGameOdds documentation (https://sportsgameodds.com/docs) and its associated OpenAPI 3.1 specification (https://sportsgameodds.com/openapi.json).

**Retrieval Date**: 2026-10-28  
**Notice**: These are official **documentation examples**, NOT live network captures. No live API key was used to retrieve or generate these files.

---

## Files and Exact Sources

| File | Exact Source URL | Description |
|------|------------------|-------------|
| `get_events_future.json` | `https://sportsgameodds.com/docs/endpoints/getEvents` (rendered example) / `https://sportsgameodds.com/openapi.json` (`#/components/examples/EventsExample-Future`) | Example of `GET /events` returning 3 upcoming matches with odds across moneyline, spreads, totals, and props. |
| `events_live.json` | `https://sportsgameodds.com/openapi.json` (`#/components/examples/EventsExample-Live`) | Example of `GET /events` returning a live match event with live available quotes (including Pinnacle). |
| `events_past_match.json` | `https://sportsgameodds.com/openapi.json` (`#/components/examples/EventsExample-PastMatch`) | Example of `GET /events` returning a completed match event with final scores and closed quotes (`available: false`). |
| `odds_data_type.json` | `https://sportsgameodds.com/docs/data-types/odds` (pre code block 1) | Data type example showing `eventID` and structured `odds` dictionary for moneyline and totals. |
| `account_usage.json` | `https://sportsgameodds.com/docs/endpoints/getUsageData` / `https://sportsgameodds.com/openapi.json` (`#/components/examples/AccountUsageExample`) | Example of `GET /account/usage` returning plan limits (Amateur), object quotas, and reset date. |
