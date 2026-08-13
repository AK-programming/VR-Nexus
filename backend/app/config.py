from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: str = "postgresql+psycopg://evidence:change_me_in_env@postgres:5432/evidence_library"
    REDIS_URL: str = "redis://redis:6379/0"

    # 768 dimensions is not a free choice: WBS 1.1.3 (Maryam) already created
    # chunks.embedding as vector(768) to match Google text-embedding-004. The
    # AgentRouter key serves no embedding models, so we hit the same dimension
    # with a local ONNX model instead — bge-base-en-v1.5 is the 768-dim sibling
    # of bge-small. Changing either line requires a migration on that column.
    EMBEDDING_PROVIDER: str = "fastembed"
    EMBEDDING_MODEL: str = "BAAI/bge-base-en-v1.5"
    EMBEDDING_DIM: int = 768

    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "claude-opus-4-8"
    OPENAI_BASE_URL: str = "https://agentrouter.org/v1"
    OPENAI_USER_AGENT: str = "claude-cli/1.0.60 (external, cli)"
    LLM_ENABLED: bool = True

    CHUNK_TOKENS: int = 800
    CHUNK_OVERLAP_TOKENS: int = 100

    STORAGE_DIR: str = "/data/storage"
    MAX_UPLOAD_MB: int = 100

    DUPLICATE_SIMILARITY_THRESHOLD: float = 0.95

    CORS_ORIGINS: str = "http://127.0.0.1:8000,http://localhost:8000,http://localhost:3000"
    LOG_LEVEL: str = "INFO"

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def llm_available(self) -> bool:
        return self.LLM_ENABLED and bool(self.OPENAI_API_KEY)

    @property
    def max_upload_bytes(self) -> int:
        return self.MAX_UPLOAD_MB * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
