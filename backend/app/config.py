from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env", "backend/.env"), extra="ignore")

    DATABASE_URL: str = "postgresql://postgres:postgres@localhost:5432/nba_platform"
    REDIS_URL: str = "redis://localhost:6379/0"
    CORS_ORIGINS: List[str] = ["http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:8000"]
    DEBUG: bool = False
    ETL_BATCH_SIZE: int = 100


settings = Settings()
