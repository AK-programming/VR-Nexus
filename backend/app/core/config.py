"""
Centralized application settings, loaded from environment variables / .env.

Every other module reads config through this Settings object instead of
calling os.getenv() directly, so there is exactly one place that defines
what configuration the app needs.

Copied from VR-Nexus-maryam/backend/app/core/config.py with two changes:

  - CORS_ORIGINS now includes the Vite dev server on 5173, which is what
    serves the React app in ../myapp during development.
  - No OPENAI_USER_AGENT field: the upstream default sent
    "claude-cli/1.0.60 (external, cli)" as a User-Agent override so a
    third-party reseller's allowlist would accept the call; that header's only
    function was to present this service as Anthropic's own first-party CLI,
    which it is not. app/services/library/llm.py sends no User-Agent override,
    and ANTHROPIC_BASE_URL below points straight at Anthropic's own API.
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

    # One provider for the whole app: Anthropic Claude, through its
    # OpenAI-compatible endpoint. It powers tender requirement extraction
    # (Stage 2), the Evidence Library assistant's grounded Ask, and library
    # auto-tagging, all off the SAME ANTHROPIC_API_KEY. Embeddings are separate
    # and local (see above); this key is not used for them. With
    # ANTHROPIC_API_KEY empty the library assistant's generated answers are
    # disabled (llm_available is False) and tender extraction cannot run.
    # See ANTHROPIC_EXTRACTION_MODEL below for the cheaper model used on the
    # high-volume, mechanical calls (extraction + tagging) versus this one.
    ANTHROPIC_API_KEY: str = ""
    ANTHROPIC_MODEL: str = "claude-sonnet-4-5-20250929"
    ANTHROPIC_BASE_URL: str = "https://api.anthropic.com/v1/"
    ANTHROPIC_USER_AGENT: str = ""
    LLM_ENABLED: bool = True
    # Cost tiering: ANTHROPIC_MODEL is the "reasoning" model, used only where the
    # call has to weigh evidence and write prose (the Evidence Library's grounded
    # Ask). Tender requirement extraction and library auto-tagging are the opposite
    # kind of call - mechanical, verbatim "copy this text into these JSON fields"
    # work, run 100+ times per tender - so they use this cheaper model instead.
    # Same ANTHROPIC_API_KEY and ANTHROPIC_BASE_URL, just a different model id.
    ANTHROPIC_EXTRACTION_MODEL: str = "claude-haiku-4-5-20251001"
    # How many tender chunks to extract concurrently. Extraction is one LLM
    # round-trip per chunk; running a few at once is the main speedup for a
    # large tender. Keep it modest on a lower Anthropic usage tier, which
    # rate-limits requests-per-minute and will 429 (then retry) if this is
    # too high.
    EXTRACTION_CONCURRENCY: int = 4

    # --- Section 6: Evidence Library chunking + upload limits ---
    CHUNK_TOKENS: int = 800
    CHUNK_OVERLAP_TOKENS: int = 100
    MAX_UPLOAD_MB: int = 100
    DUPLICATE_SIMILARITY_THRESHOLD: float = 0.95
    # 5173 is the Vite dev server for ../myapp; 3000 is Section 8's Next.js.
    CORS_ORIGINS: str = (
        "http://localhost:5173,http://127.0.0.1:5173,"
        "http://localhost:3000,http://127.0.0.1:8000,http://localhost:8000"
    )

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def llm_available(self) -> bool:
        return self.LLM_ENABLED and bool(self.ANTHROPIC_API_KEY)

    @property
    def max_upload_bytes(self) -> int:
        return self.MAX_UPLOAD_MB * 1024 * 1024

    # --- Outbound email (support reports + account emails) ---
    # Two things share this one SMTP account: when a tender fails, "Contact
    # technical support" emails the full error to SUPPORT_EMAIL
    # (services/support_email.py); separately, "Forgot password" emails a
    # reset link to whichever user requested it (services/account_email.py).
    # SMTP defaults target Gmail (STARTTLS on 587). To enable sending, set
    # SMTP_USERNAME and SMTP_PASSWORD in backend/.env — for Gmail that PASSWORD
    # must be an App Password (16 chars, no spaces), NOT the account password,
    # and the account needs 2-Step Verification on. With either credential
    # empty, smtp_configured is False and both features report "not
    # configured" instead of sending (the failure-report UI falls back to a
    # plain mailto: link to SUPPORT_EMAIL; forgot-password just surfaces the
    # error - there's no equivalent manual fallback for a password reset).
    SUPPORT_EMAIL: str = "engrak2155@gmail.com"
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    # Envelope From. Defaults to SMTP_USERNAME (see smtp_from). Gmail rewrites a
    # mismatched From to the authenticated account anyway, so this mostly matters
    # for a self-hosted relay.
    SMTP_FROM: str = ""
    SMTP_USE_TLS: bool = True

    # Where the frontend actually runs, so a password-reset email can link
    # straight to /reset-password?token=... instead of a bare token the user
    # would have to paste in somewhere. Change this to the deployed origin in
    # production - a localhost link in a real email helps no one.
    PASSWORD_RESET_URL_BASE: str = "http://localhost:5173"

    @property
    def smtp_from(self) -> str:
        return self.SMTP_FROM or self.SMTP_USERNAME

    @property
    def smtp_configured(self) -> bool:
        return bool(self.SMTP_USERNAME and self.SMTP_PASSWORD)

    @property
    def support_email_configured(self) -> bool:
        return self.smtp_configured and bool(self.SUPPORT_EMAIL)

    # --- App ---
    ENVIRONMENT: str = "development"
    DEBUG: bool = True


@lru_cache
def get_settings() -> Settings:
    """Settings are read once and cached; import get_settings() wherever needed."""
    return Settings()
