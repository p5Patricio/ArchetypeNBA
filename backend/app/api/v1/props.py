from datetime import datetime, timezone
import json
import logging
from pathlib import Path
from typing import List, Optional
from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.config import settings
from app.services.injury_scraper import InjuryScraperService
from app.services.gemini_analyzer import GeminiAnalyzerService
from app.services.odds_api_service import OddsApiService
from app.services.telegram_service import TelegramService
from app.analytics.props_engine import (
    PropsEngine,
    PropSimulationResult,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/props", tags=["props"])

# Cache file in backend/app/data/last_props_cache.json
DATA_DIR = Path(__file__).resolve().parents[2] / "data"
CACHE_FILE = DATA_DIR / "last_props_cache.json"

# Simple memory cache
_cached_response: Optional["TodayPropsResponse"] = None
_last_computed_time: Optional[float] = None
CACHE_TTL_SECONDS = 3600  # 1 hour in memory

ODDS_SOURCE_LIVE = "The Odds API (En Vivo)"
ODDS_SOURCE_NO_LIVE = "The Odds API (Sin líneas en vivo)"


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
    # Fields below default so slates cached before they existed still load. edge_pct, expected_value_pct,
    # kelly_stake_pct and book_implied_prob refer to `side`; prob_over and over_odds keep their meaning.
    side: str = "over"
    under_odds: Optional[int] = None
    prob_under: Optional[float] = None
    bookmaker: Optional[str] = None
    devigged: bool = False
    fair_prob: Optional[float] = None


class TodayPropsResponse(BaseModel):
    date: str
    ai_engine: str
    odds_source: str
    slate_summary: str
    total_props: int
    value_picks_count: int
    items: List[PropItemResponse]


def _save_cache_to_file(response: TodayPropsResponse) -> None:
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(response.model_dump(), f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"Could not persist props cache to {CACHE_FILE}: {e}")


def _load_cache_from_file() -> Optional[TodayPropsResponse]:
    if not CACHE_FILE.exists():
        return None
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return TodayPropsResponse(**data)
    except Exception as e:
        logger.warning(f"Could not read props cache from {CACHE_FILE}: {e}")
        return None


def _send_telegram_report(response: TodayPropsResponse) -> bool:
    if not settings.TELEGRAM_BOT_TOKEN or not settings.TELEGRAM_CHAT_ID:
        logger.info("Telegram not configured. Skipping report dispatch.")
        return False

    telegram = TelegramService()
    header = (
        f"🏀 *NBA PROPS INTEL — {response.date}*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🧠 *Cerebro IA:* {response.ai_engine}\n"
        f"📊 *Líneas Deportivas:* {response.odds_source}\n"
        f"🎲 *Simulaciones:* {settings.PROPS_SIMULATION_RUNS:,} corridas Monte Carlo\n\n"
    )
    context_sec = f"📋 *Contexto de Lesiones & Minutos:*\n_{response.slate_summary}_\n\n"
    picks_sec = "🎯 *TOP PICKS CON VALOR (+EV):*\n"

    value_picks = [p for p in response.items if p.edge_pct > 0 and "PASS" not in p.recommendation]
    if not value_picks:
        value_picks = sorted(response.items, key=lambda x: x.edge_pct, reverse=True)[:3]

    if not value_picks:
        picks_sec += "_Sin líneas en vivo: no hay picks para evaluar._\n\n"

    for p in value_picks[:4]:
        side_label = p.side.capitalize()
        side_odds = p.under_odds if p.side == "under" and p.under_odds is not None else p.over_odds
        if p.side == "under" and p.prob_under is not None:
            side_prob = p.prob_under
        elif p.side == "under":
            side_prob = 1.0 - p.prob_over  # slate cached before prob_under existed
        else:
            side_prob = p.prob_over
        book_note = f" · {p.bookmaker}" if p.bookmaker else ""
        emoji = "🟢" if "STRONG" in p.recommendation else "🟡"
        edge_fmt = f"+{p.edge_pct:.1f}%" if p.edge_pct > 0 else f"{p.edge_pct:.1f}%"
        ev_fmt = f"+{p.expected_value_pct:.1f}%" if p.expected_value_pct > 0 else f"{p.expected_value_pct:.1f}%"
        picks_sec += (
            f"{emoji} *{p.player_name}* ({p.team})\n"
            f"   • *Prop:* {p.stat_type} Línea: *{p.line}* (Cuota {side_label}: {side_odds:+d}{book_note})\n"
            f"   • *Dictamen:* {p.recommendation} | *Edge:* `{edge_fmt}` | *EV:* `{ev_fmt}`\n"
            f"   • *Proyección:* Media: *{p.projected_mean:.1f}* | Rango P10-P90: [{p.projected_p10:.1f} - {p.projected_p90:.1f}]\n"
            f"   • *Prob. {side_label}:* `{side_prob * 100:.1f}%` (Libro: `{p.book_implied_prob * 100:.1f}%`)\n"
        )
        if p.reasoning:
            picks_sec += f"   • *Contexto IA:* _{p.reasoning}_\n"
        picks_sec += "\n"

    inactive_picks = [p for p in response.items if "PASS" in p.recommendation or p.risk_level in ("HIGH", "EXTREME")]
    alerts_sec = ""
    if inactive_picks:
        alerts_sec = "⚠️ *ALERTAS DE RIESGO & BAJAS:*\n"
        for r in inactive_picks[:3]:
            alerts_sec += f"   ⛔ *{r.player_name}*: {r.reasoning}\n"
        alerts_sec += "\n"

    footer = (
        "━━━━━━━━━━━━━━━━━━━━\n"
        "💡 *Estrategia:* Gestión de banca prudente (Quarter-Kelly). "
        "Las probabilidades se basan en distribuciones Binomial Negativa calibradas."
    )

    msg = header + context_sec + picks_sec + alerts_sec + footer
    return telegram.send_message_sync(msg)


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
        # Only real quoted lines are evaluated; a player without a live line is skipped.
        player_props = props_map.get(player.name, {})
        available_lines = [player_props.get(stat) for stat in ("PTS", "REB", "AST", "PRA")]

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
                    side=res.side,
                    under_odds=res.under_odds,
                    prob_under=res.prob_under,
                    bookmaker=res.bookmaker,
                    devigged=res.devigged,
                    fair_prob=res.fair_prob,
                )
            )

    model_label = settings.GEMINI_MODEL.replace("models/", "").replace("-", " ").title()
    ai_label = model_label if analysis.engine_source == "GEMINI" else "Modo Heurístico Local"
    odds_label = ODDS_SOURCE_LIVE if odds_service.last_fetch_live else ODDS_SOURCE_NO_LIVE

    resp = TodayPropsResponse(
        date=today_str,
        ai_engine=ai_label,
        odds_source=odds_label,
        slate_summary=analysis.slate_summary,
        total_props=len(items),
        value_picks_count=value_count,
        items=items,
    )

    # Persist to disk cache
    _save_cache_to_file(resp)
    return resp


@router.get("/today", response_model=TodayPropsResponse)
def get_today_props(
    stat_type: Optional[str] = Query(None, description="Filter by stat type: PTS, REB, AST, PRA"),
    only_value: bool = Query(False, description="Filter only picks with positive edge"),
    refresh: bool = Query(False, description="Force recompute bypassing cache"),
):
    """
    Returns today's player props predictions. Reads from cache by default to protect Gemini/Odds API quota.
    """
    global _cached_response, _last_computed_time
    now = datetime.now(timezone.utc).timestamp()

    if refresh:
        _cached_response = _compute_today_props()
        _last_computed_time = now
    elif _cached_response is None:
        _cached_response = _load_cache_from_file()
        if _cached_response is not None:
            _last_computed_time = now

    if _cached_response is None:
        # Idle state: do not automatically consume quota until the user clicks the action button
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return TodayPropsResponse(
            date=today_str,
            ai_engine="Gemini 3.6 Flash (En Pausa)",
            odds_source="The Odds API",
            slate_summary="Análisis en pausa para ahorrar cuota. Hacé clic en 'Ejecutar Análisis IA' para iniciar las simulaciones de hoy.",
            total_props=0,
            value_picks_count=0,
            items=[],
        )

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


@router.post("/run-analysis", response_model=TodayPropsResponse)
def run_props_analysis(
    send_telegram: bool = Query(False, description="Dispatch executive summary to Telegram"),
):
    """
    On-demand analysis runner triggered explicitly from the frontend.
    Consumes Gemini API & The Odds API only when requested by the user.
    """
    global _cached_response, _last_computed_time
    _cached_response = _compute_today_props()
    _last_computed_time = datetime.now(timezone.utc).timestamp()

    if send_telegram:
        _send_telegram_report(_cached_response)

    return _cached_response
