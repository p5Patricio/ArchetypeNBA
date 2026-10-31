#!/usr/bin/env python3
"""
CLI tool to probe the SportsGameOdds API and inspect its live payload format.

Usage:
    python scripts/sgo_probe.py [--dry-run]

When executed:
    - With --dry-run: prints the request that would be made without sending it.
    - With a configured key: makes ONE small request (limit 2 events, NBA, oddsAvailable)
      and prints key-level schema breakdown (never the API key) and parsed GameQuotes.
    - Without a key: explains that SPORTSGAMEODDS_API_KEY is unset and exits cleanly.

NOT wired into the tick; NOT scheduled.
"""
import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict

# Add backend directory to sys.path
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

import httpx

from app.config import settings
from app.services.odds_providers.sportsgameodds import (
    SportsGameOddsService,
    mask_key,
    parse_sgo_events,
    sanitize_message,
)


def _safe_structure_summary(obj: Any, depth: int = 0, max_depth: int = 3) -> Any:
    """Recursively summarizes keys and types of an object without exposing secrets."""
    if depth >= max_depth:
        if isinstance(obj, dict):
            return f"<dict with {len(obj)} keys>"
        if isinstance(obj, list):
            return f"<list with {len(obj)} items>"
        return type(obj).__name__

    if isinstance(obj, dict):
        summary = {}
        for k, v in list(obj.items())[:10]:
            if k in ("apiKey", "x-api-key", "token", "secret", "password"):
                summary[k] = "<redacted>"
            elif isinstance(v, (dict, list)):
                summary[k] = _safe_structure_summary(v, depth + 1, max_depth)
            else:
                summary[k] = f"{type(v).__name__} ({str(v)[:40]})"
        if len(obj) > 10:
            summary["..."] = f"<+{len(obj) - 10} more keys>"
        return summary
    elif isinstance(obj, list):
        if not obj:
            return []
        return [_safe_structure_summary(obj[0], depth + 1, max_depth), f"<+{len(obj) - 1} more items>"] if len(obj) > 1 else [_safe_structure_summary(obj[0], depth + 1, max_depth)]
    else:
        return f"{type(obj).__name__} ({str(obj)[:40]})"


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe the SportsGameOdds API live structure.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the planned HTTP request without sending network traffic.",
    )
    parser.add_argument(
        "--capture-dry-run",
        action="store_true",
        help="Print what the daily capture step would request and its object cost estimate.",
    )
    args = parser.parse_args()

    svc = SportsGameOddsService()
    masked = mask_key(svc.api_key)

    print("==================================================")
    print(" SportsGameOdds API Probe")
    print("==================================================")
    print(f"Base URL:              {svc.base_url}")
    print(f"Configured:            {svc.is_configured}")
    print(f"API Key:               {masked or '(not configured)'}")
    print(f"Min Remaining Objects: {svc.min_remaining_objects}")
    print("==================================================")

    url = f"{svc.base_url}/events"
    params = {
        "leagueID": "NBA",
        "oddsAvailable": "true",
        "limit": 2,
    }

    if args.capture_dry_run:
        now_utc = datetime.now(timezone.utc)
        starts_after = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        starts_before = (now_utc + timedelta(hours=36)).strftime("%Y-%m-%dT%H:%M:%SZ")
        daily_params = {
            "leagueID": "NBA",
            "oddsAvailable": "true",
            "startsAfter": starts_after,
            "startsBefore": starts_before,
            "limit": 50,
        }
        budget = getattr(settings, "SGO_DAILY_OBJECT_BUDGET", 30)
        print("\n[CAPTURE DRY RUN] SportsGameOdds Daily Capture Step:")
        print(f"Method:        GET")
        print(f"URL:           {url}")
        print(f"Params:        {daily_params}")
        print(f"Pagination:    cursor pagination (param named 'cursor')")
        print(f"Headers:       {{'x-api-key': '{masked or '<UNSET>'}'}}")
        print(f"Daily Budget:  {budget} object(s)/day")
        print(f"Cost Estimate: ~12-15 object(s)/day (1 object per upcoming NBA event within 36h)")
        print(f"Storage:       Main lines + player props into odds_history (sgo_<book>), consensus into market_consensus_snapshot")
        print("\nCapture dry run finished successfully (no network calls made).")
        return 0

    if args.dry_run:
        print("\n[DRY RUN] Would execute the following request:")
        print(f"Method:  GET")
        print(f"URL:     {url}")
        print(f"Params:  {params}")
        print(f"Headers: {{'x-api-key': '{masked or '<UNSET>'}'}}")
        print("\nProbe dry run finished successfully (no network calls made).")
        return 0

    if not svc.is_configured:
        print("\nSPORTSGAMEODDS_API_KEY is not configured or contains placeholder ('your_').")
        print("To probe live responses, set SPORTSGAMEODDS_API_KEY in backend/.env.")
        print("Probe finished cleanly (nothing fetched).")
        return 0

    print("\nSending live probe request (limit 2 NBA events)...")
    try:
        with httpx.Client(base_url=svc.base_url, timeout=30.0, headers={"x-api-key": svc.api_key}) as client:
            res = client.get("/events", params={**params, "apiKey": svc.api_key})
            print(f"Response Status: {res.status_code}")
            if res.status_code != 200:
                print(f"Error response: {sanitize_message(res.text[:300], svc.api_key)}")
                return 1

            payload = res.json()
            print("\nResponse Top-Level Structure:")
            print(json.dumps(_safe_structure_summary(payload), indent=2))

            # Parse quotes
            quotes = parse_sgo_events(payload)
            print(f"\nParser extracted {len(quotes)} GameQuote(s):")
            market_counts: Dict[str, int] = {}
            book_counts: Dict[str, int] = {}
            for q in quotes:
                market_counts[q.market_key] = market_counts.get(q.market_key, 0) + 1
                book_counts[q.bookmaker_key] = book_counts.get(q.bookmaker_key, 0) + 1

            print(f"  Markets:    {market_counts}")
            print(f"  Bookmakers: {book_counts}")
            if quotes:
                sample = quotes[0]
                print(f"\nSample GameQuote:")
                print(f"  Event:     {sample.event_id} ({sample.away_team} @ {sample.home_team})")
                print(f"  Commence:  {sample.commence_time}")
                print(f"  Bookmaker: {sample.bookmaker_title} ({sample.bookmaker_key})")
                print(f"  Market:    {sample.market_key} ({sample.side}) line={sample.line}")
                print(f"  Price:     {sample.price_american}")
                print(f"  Updated:   {sample.book_last_update}")

            return 0
    except Exception as e:
        print(f"Probe encountered error: {sanitize_message(str(e), svc.api_key)}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
