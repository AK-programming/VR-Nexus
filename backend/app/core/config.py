"""
Centralized application settings, loaded from environment variables / .env.

Every other module reads config through this Settings object instead of
calling os.getenv() directly, so there is exactly one place that defines
what configuration the app needs.
"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Database ---
    DATABASE_URL: str

    # --- Redis / Celery ---
    REDIS_URL: str
    CELERY_BROKER_URL: str
    CELERY_RESULT_BACKEND: str

    # --- Auth ---
    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440
    FAILED_LOGIN_LOCKOUT_THRESHOLD: int = 5
    FAILED_LOGIN_LOCKOUT_MINUTES: int = 15

    # --- Storage ---
    STORAGE_ROOT: str = "./storage"
    TENDER_STORAGE_DIR: str = "./storage/tenders"
    LIBRARY_STORAGE_DIR: str = "./storage/library"
    OUTPUT_STORAGE_DIR: str = "./storage/outputs"

    # --- AI providers ---
    GOOGLE_API_KEY: str = ""
    LLM_LIGHT_MODEL: str = "gemini-1.5-flash"
    LLM_HEAVY_MODEL: str = "gemini-1.5-pro"
    EMBEDDING_MODEL: str = "text-embedding-004"
    EMBEDDING_DIM: int = 768

    # --- App ---
    ENVIRONMENT: str = "development"
    DEBUG: bool = True


@lru_cache
def get_settings() -> Settings:
    """Settings are read once and cached; import get_settings() wherever needed."""
    return Settings()
