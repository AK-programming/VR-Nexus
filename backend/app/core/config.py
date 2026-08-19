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
    # Originally planned as Google's text-embedding-004 (see chunks.embedding's
    # vector(768) column comment in Task 1.1.3) - switched to a local model
    # per team decision, since it needs no API key and the third-party LLM
    # router in use for other calls doesn't serve embedding models at all.
    # bge-base-en-v1.5 is 768-dim, matching the existing column with no
    # migration needed. Changing either of the next two lines requires a
    # migration on chunks.embedding's dimension.
    EMBEDDING_PROVIDER: str = "fastembed"
    EMBEDDING_MODEL: str = "BAAI/bge-base-en-v1.5"
    EMBEDDING_DIM: int = 768

    GOOGLE_API_KEY: str = ""
    LLM_LIGHT_MODEL: str = "gemini-1.5-flash"
    LLM_HEAVY_MODEL: str = "gemini-1.5-pro"

    # Section 6's LLM fallback for auto-tagging (metadata) and parsing edge
    # cases - NOT used for embeddings. Points at a third-party router by
    # default; left with no key so it's inert (llm_available is False)
    # until the team makes a deliberate decision to enable it, given real
    # tender/library documents may pass through whatever this points at.
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "claude-opus-4-8"
    OPENAI_BASE_URL: str = "https://agentrouter.org/v1"
    OPENAI_USER_AGENT: str = "claude-cli/1.0.60 (external, cli)"
    LLM_ENABLED: bool = True

    # --- Section 6: Evidence Library chunking + upload limits ---
    CHUNK_TOKENS: int = 800
    CHUNK_OVERLAP_TOKENS: int = 100
    MAX_UPLOAD_MB: int = 100
    DUPLICATE_SIMILARITY_THRESHOLD: float = 0.95
    CORS_ORIGINS: str = "http://127.0.0.1:8000,http://localhost:8000,http://localhost:3000"

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def llm_available(self) -> bool:
        return self.LLM_ENABLED and bool(self.OPENAI_API_KEY)

    @property
    def max_upload_bytes(self) -> int:
        return self.MAX_UPLOAD_MB * 1024 * 1024

    # --- App ---
    ENVIRONMENT: str = "development"
    DEBUG: bool = True


@lru_cache
def get_settings() -> Settings:
    """Settings are read once and cached; import get_settings() wherever needed."""
    return Settings()
