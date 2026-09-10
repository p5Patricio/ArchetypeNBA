from datetime import datetime, timezone
import logging
from pathlib import Path
from typing import List, Optional
from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.config import settings
from app.services.injury_scraper import InjuryScraperService
from app.services.gemini_analyzer import GeminiAnalyzerService
from app.services.odds_api_service import OddsApiService
from app.analytics.props_engine import (
    PropsEngine,
    PropBetLine,
    PropSimulationResult,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/props", tags=["props"])

# Simple memory cache to keep API responses ultra-fast (<10ms)
_cached_response = None
_last_computed_time = None
CACHE_TTL_SECONDS = 600  # 10 minutes


class PropItemResponse(BaseModel):
    player_name: str
    team: str
    stat_type: str
    line: float
    over_odds: int
    projected_mean: float
    projected_median: float
    projected_p10: float
    projected_p90: float
    prob_over: float
    book_implied_prob: float
    edge_pct: float
    expected_value_pct: float
    kelly_stake_pct: float
    recommendation: str
    risk_level: str
    reasoning: str


class TodayPropsResponse(BaseModel):
    date: str
    ai_engine: str
    odds_source: str
    slate_summary: str
    total_props: int
    value_picks_count: int
    items: List[PropItemResponse]


def _compute_today_props() -> TodayPropsResponse:
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # 1. Scrape injury report
    scraper = InjuryScraperService()
    injury_items = scraper.fetch_injury_report()

    # 2. Qualitative analysis with Gemini AI
    analyzer = GeminiAnalyzerService()
    analysis = analyzer.analyze_injuries_and_news(injury_items)
    modifier_map = {m.player_name.lower(): m for m in analysis.modifiers}

    # 3. Retrieve live sportsbook lines via The Odds API
    odds_service = OddsApiService()
    props_map = odds_service.get_slate_props_map()

    # 4. Quantitative simulations with PropsEngine
    engine = PropsEngine(simulation_runs=settings.PROPS_SIMULATION_RUNS)
    backend_dir = Path(__file__).resolve().parents[3]
    db_file = backend_dir / "nba_platform.db"

    all_baselines = engine.load_baselines_from_db(db_path=db_file)
    target_names = {
        "luka doncic", "nikola jokic", "giannis antetokounmpo", "lebron james",
        "anthony davis", "kyrie irving", "stephen curry", "jayson tatum"
    }
    baselines = [b for b in all_baselines if b.name.lower() in target_names]
    if not baselines:
        baselines = engine.get_standard_star_baselines()

    items: List[PropItemResponse] = []
    value_count = 0

    for player in baselines:
        player_props = props_map.get(player.name, {})
        # Evaluate available props (PTS, REB, AST, PRA)
        available_lines = [
            player_props.get("PTS", PropBetLine(stat_type="PTS", line=22.5)),
            player_props.get("REB"),
            player_props.get("AST"),
            player_props.get("PRA"),
        ]

        mod = modifier_map.get(player.name.lower())
        min_mult = mod.minute_multiplier if mod else 1.0
        usage_mult = mod.usage_multiplier if mod else 1.0
        risk = mod.risk_level if mod else "LOW"
        summary = mod.tactical_summary if mod else "Standard rotation baseline."

        for prop_line in available_lines:
            if not prop_line:
                continue

            res: PropSimulationResult = engine.evaluate_prop(
                player=player,
                prop=prop_line,
                minute_multiplier=min_mult,
                usage_multiplier=usage_mult,
                risk_level=risk,
                tactical_summary=summary,
            )

            if res.edge_pct > 0 and "PASS" not in res.recommendation:
                value_count += 1

            items.append(
                PropItemResponse(
                    player_name=res.player_name,
                    team=res.team,
                    stat_type=res.stat_type,
                    line=res.sportsbook_line,
                    over_odds=res.over_odds,
                    projected_mean=res.projected_mean,
                    projected_median=res.projected_median,
                    projected_p10=res.projected_p10,
                    projected_p90=res.projected_p90,
                    prob_over=res.prob_over,
                    book_implied_prob=res.book_implied_prob,
                    edge_pct=res.edge_pct,
                    expected_value_pct=res.expected_value_pct,
                    kelly_stake_pct=res.kelly_stake_pct,
                    recommendation=res.recommendation,
                    risk_level=res.risk_level,
                    reasoning=res.reasoning,
                )
            )

    model_label = settings.GEMINI_MODEL.replace("models/", "").replace("-", " ").title()
    ai_label = model_label if analysis.engine_source == "GEMINI" else "Modo Heurístico Local"
    odds_label = "The Odds API (En Vivo)" if odds_service.is_configured else "The Odds API (Consenso)"

    return TodayPropsResponse(
        date=today_str,
        ai_engine=ai_label,
        odds_source=odds_label,
        slate_summary=analysis.slate_summary,
        total_props=len(items),
        value_picks_count=value_count,
        items=items,
    )


@router.get("/today", response_model=TodayPropsResponse)
def get_today_props(
    stat_type: Optional[str] = Query(None, description="Filter by stat type: PTS, REB, AST, PRA"),
    only_value: bool = Query(False, description="Filter only picks with positive edge"),
    refresh: bool = Query(False, description="Force recompute bypassing 10-minute cache"),
):
    """
    Returns today's player props predictions, +EV value edge, and Gemini injury reasoning.
    """
    global _cached_response, _last_computed_time
    now = datetime.now(timezone.utc).timestamp()

    if refresh or _cached_response is None or (_last_computed_time and (now - _last_computed_time > CACHE_TTL_SECONDS)):
        _cached_response = _compute_today_props()
        _last_computed_time = now

    response_data = _cached_response

    # Apply filters
    filtered_items = response_data.items
    if stat_type:
        filtered_items = [i for i in filtered_items if i.stat_type.upper() == stat_type.upper()]
    if only_value:
        filtered_items = [i for i in filtered_items if i.edge_pct > 0 and "PASS" not in i.recommendation]

    return TodayPropsResponse(
        date=response_data.date,
        ai_engine=response_data.ai_engine,
        odds_source=response_data.odds_source,
        slate_summary=response_data.slate_summary,
        total_props=len(filtered_items),
        value_picks_count=sum(1 for i in filtered_items if i.edge_pct > 0 and "PASS" not in i.recommendation),
        items=filtered_items,
    )
