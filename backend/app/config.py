from pathlib import Path
from typing import List
from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

# Ensure backend/.env overrides stale machine-level environment variables
for env_file in [
    Path(__file__).resolve().parent.parent / ".env",
    Path(__file__).resolve().parent.parent.parent / ".env",
]:
    if env_file.exists():
        load_dotenv(dotenv_path=env_file, override=True)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env", "backend/.env"), extra="ignore")

    DATABASE_URL: str = "postgresql://postgres:postgres@localhost:5432/nba_platform"
    REDIS_URL: str = "redis://localhost:6379/0"
    CORS_ORIGINS: List[str] = [
        "http://localhost:38920",
        "http://127.0.0.1:38920",
        "http://localhost:38921",
        "http://127.0.0.1:38921",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://localhost:8001",
        "http://127.0.0.1:8001",
    ]
    DEBUG: bool = False
    ETL_BATCH_SIZE: int = 100

    # AI & Notifications
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-3.6-flash"
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_CHAT_ID: str = ""
    THE_ODDS_API_KEY: str = ""
    PROPS_SIMULATION_RUNS: int = 10000

    # Second odds feed: SportsGameOdds (free Amateur tier; disabled until owner sets key)
    SPORTSGAMEODDS_API_KEY: str = ""
    SPORTSGAMEODDS_BASE_URL: str = "https://api.sportsgameodds.com/v2"
    SPORTSGAMEODDS_MIN_REMAINING_OBJECTS: int = 100

    # Official NBA Injury Report PDF automated download (disabled until owner clears NBA terms)
    INJURY_PDF_ENABLED: bool = False

    # Model learning loop (app.services.model_evaluation / model_promotion). The defaults mirror the module
    # constants in model_evaluation; LEARNING_AUTOPROMOTE is the kill switch (off = evaluate and report only).
    LEARNING_MIN_GAMES: int = 150
    LEARNING_MIN_DAYS_LIVE: int = 14
    LEARNING_COOLDOWN_DAYS: int = 30
    LEARNING_AUTOPROMOTE: bool = True
    LEARNING_PROPOSAL_DAYS: int = 7
    LEARNING_MAX_CHALLENGERS: int = 3
    # Look budget: at most one decision-grade look per challenger every LOOK_INTERVAL_DAYS and MAX_LOOKS per pairing;
    # a challenger whose budget is spent without a promotion leaves once older than MAX_AGE_DAYS (with >= 300 games).
    LEARNING_LOOK_INTERVAL_DAYS: int = 7
    LEARNING_MAX_LOOKS: int = 12
    LEARNING_MAX_AGE_DAYS: int = 150

    # Candidate lab multiple-testing control (app.analytics.multiple_testing).
    # When True, a candidate must also pass the SPA multiple-testing gate (selection_pvalue_spa < 0.2)
    # on the selection window to be eligible for registration as a challenger. Default False (report only).
    LAB_MULTITEST_GATE: bool = False


settings = Settings()
