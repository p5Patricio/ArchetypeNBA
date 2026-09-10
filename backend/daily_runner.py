#!/usr/bin/env python
"""
daily_runner.py — Master orchestrator for automated NBA Player Props analysis.
Runs daily on system startup:
1. Ingests official NBA injury report.
2. Extracts qualitative context with Gemini AI.
3. Simulates player props distributions (Negative Binomial + Monte Carlo).
4. Dispatches an executive report to Telegram.
"""

import argparse
from datetime import datetime, timezone
import logging
import os
import sys
from pathlib import Path

# Ensure backend directory is in sys.path
backend_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(backend_dir))

# UTF-8 stdout configuration for Windows consoles
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from app.config import settings
from app.services.injury_scraper import InjuryScraperService
from app.services.gemini_analyzer import GeminiAnalyzerService
from app.services.telegram_service import TelegramService
from app.services.odds_api_service import OddsApiService
from app.analytics.props_engine import (
    PropsEngine,
    PropBetLine,
    PropSimulationResult,
    PlayerBaseline,
)

# Setup logging
log_file = backend_dir / "daily_runner.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(log_file, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("DailyRunner")


def build_telegram_message(
    date_str: str,
    slate_summary: str,
    results: list[PropSimulationResult],
    gemini_active: bool,
    odds_source: str = "The Odds API (Consenso Vegas)",
) -> str:
    """Formats an executive summary report optimized for Telegram Markdown."""
    model_label = settings.GEMINI_MODEL.replace("models/", "").replace("-", " ").title()
    header = (
        f"🏀 *NBA PROPS INTEL — {date_str}*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🧠 *Cerebro IA:* {model_label if gemini_active else 'Modo Heurístico Local'}\n"
        f"📊 *Líneas Deportivas:* {odds_source}\n"
        f"🎲 *Simulaciones:* {settings.PROPS_SIMULATION_RUNS:,} corridas Monte Carlo\n\n"
    )

    context_sec = f"📋 *Contexto de Lesiones & Minutos:*\n_{slate_summary}_\n\n"

    picks_sec = "🎯 *TOP PICKS CON VALOR (+EV):*\n"
    # Filter for picks with positive edge
    value_picks = [r for r in results if r.edge_pct > 0 and "PASS" not in r.recommendation]
    if not value_picks:
        value_picks = sorted(results, key=lambda x: x.edge_pct, reverse=True)[:3]

    for p in value_picks[:4]:
        recommendation_emoji = "🟢" if "STRONG" in p.recommendation else "🟡"
        edge_fmt = f"+{p.edge_pct:.1f}%" if p.edge_pct > 0 else f"{p.edge_pct:.1f}%"
        ev_fmt = f"+{p.expected_value_pct:.1f}%" if p.expected_value_pct > 0 else f"{p.expected_value_pct:.1f}%"
        picks_sec += (
            f"{recommendation_emoji} *{p.player_name}* ({p.team})\n"
            f"   • *Prop:* {p.stat_type} Línea: *{p.sportsbook_line}* (Cuota: {p.over_odds:+d})\n"
            f"   • *Dictamen:* {p.recommendation} | *Edge:* `{edge_fmt}` | *EV:* `{ev_fmt}`\n"
            f"   • *Proyección:* Media: *{p.projected_mean}* | Rango P10-P90: [{p.projected_p10} - {p.projected_p90}]\n"
            f"   • *Prob. Over:* `{p.prob_over * 100:.1f}%` (Libro: `{p.book_implied_prob * 100:.1f}%`)\n"
        )
        if p.reasoning:
            picks_sec += f"   • *Contexto IA:* _{p.reasoning}_\n"
        picks_sec += "\n"

    # Inactives & high-risk warnings
    inactive_picks = [r for r in results if "PASS" in r.recommendation or r.risk_level in ("HIGH", "EXTREME")]
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

    return header + context_sec + picks_sec + alerts_sec + footer


def run_pipeline(dry_run: bool = False) -> bool:
    """Executes the complete daily props intelligence workflow."""
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    logger.info(f"=== Starting NBA Daily Props Pipeline for {today_str} ===")

    # 1. Scrape official injury report
    logger.info("Step 1: Ingesting official injury report...")
    scraper = InjuryScraperService()
    injury_items = scraper.fetch_injury_report()
    logger.info(f"Fetched {len(injury_items)} injury entries.")

    # 2. Qualitative analysis with Gemini AI
    logger.info("Step 2: Processing qualitative intelligence with Gemini...")
    analyzer = GeminiAnalyzerService()
    analysis = analyzer.analyze_injuries_and_news(injury_items)
    logger.info(f"Gemini Slate Summary: {analysis.slate_summary}")

    # Build lookup map for qualitative modifiers
    modifier_map = {m.player_name.lower(): m for m in analysis.modifiers}

    # 3. Retrieve live sportsbook lines via The Odds API
    logger.info("Step 3: Fetching sportsbook lines via The Odds API...")
    odds_service = OddsApiService()
    props_map = odds_service.get_slate_props_map()

    # 4. Quantitative simulations with PropsEngine
    logger.info("Step 4: Running Negative Binomial + Monte Carlo prop models...")
    engine = PropsEngine(simulation_runs=settings.PROPS_SIMULATION_RUNS)
    
    # Load dynamic multi-season recency-weighted baselines from database (2025-26 latest teams)
    db_file = backend_dir / "nba_platform.db"
    all_baselines = engine.load_baselines_from_db(db_path=db_file)
    target_names = {"luka doncic", "nikola jokic", "giannis antetokounmpo", "lebron james", "anthony davis", "kyrie irving", "stephen curry", "jayson tatum"}
    baselines = [b for b in all_baselines if b.name.lower() in target_names]
    if not baselines:
        baselines = engine.get_standard_star_baselines()

    results: list[PropSimulationResult] = []
    for player in baselines:
        player_props = props_map.get(player.name, {})
        # Use available stat prop (prefer PTS or PRA or REB)
        prop_line = (
            player_props.get("PTS")
            or player_props.get("PRA")
            or player_props.get("REB")
            or PropBetLine(stat_type="PTS", line=22.5)
        )
        mod = modifier_map.get(player.name.lower())

        min_mult = mod.minute_multiplier if mod else 1.0
        usage_mult = mod.usage_multiplier if mod else 1.0
        risk = mod.risk_level if mod else "LOW"
        summary = mod.tactical_summary if mod else "Standard rotation baseline."

        res = engine.evaluate_prop(
            player=player,
            prop=prop_line,
            minute_multiplier=min_mult,
            usage_multiplier=usage_mult,
            risk_level=risk,
            tactical_summary=summary,
        )
        results.append(res)

    # 5. Generate formatted report
    odds_label = "The Odds API (En Vivo)" if odds_service.is_configured else "The Odds API (Consenso)"
    report_text = build_telegram_message(
        date_str=today_str,
        slate_summary=analysis.slate_summary,
        results=results,
        gemini_active=(analysis.engine_source == "GEMINI"),
        odds_source=odds_label,
    )

    logger.info("\n--- GENERATED TELEGRAM REPORT PREVIEW ---\n" + report_text + "\n-----------------------------------------")

    # 5. Dispatch via Telegram
    telegram = TelegramService()
    if dry_run or not telegram.is_configured:
        if not telegram.is_configured:
            logger.warning(
                "Telegram credentials not configured in .env. "
                "Report printed to console and daily_runner.log. "
                "To receive Telegram messages, set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID."
            )
        else:
            logger.info("Dry-run mode active: message not dispatched to Telegram API.")
        return True

    logger.info("Step 4: Dispatching report to Telegram...")
    sent = telegram.send_message_sync(report_text)
    if sent:
        logger.info("✅ Telegram report dispatched successfully!")
    else:
        logger.error("❌ Failed to dispatch message to Telegram.")
    return sent


def main():
    parser = argparse.ArgumentParser(description="NBA Player Props Daily Automated Runner")
    parser.add_argument("--dry-run", action="store_true", help="Run simulations without sending to Telegram")
    args = parser.parse_args()

    success = run_pipeline(dry_run=args.dry_run)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
