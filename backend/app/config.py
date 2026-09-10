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


settings = Settings()
