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

    # --- Additional providers (client follow-up: "able to change the api to
    # gemini or openai etc") ---
    # Both OpenAI and Google Gemini publish an OpenAI-compatible endpoint, so
    # this app's existing `openai` client library talks to either of them
    # just by pointing at a different base_url with a different key - no new
    # SDK needed. Empty by default: with no key set for a provider, nothing
    # can select it (see app/services/app_settings.py's PROVIDERS / provider
    # key routes), and every existing deployment keeps running on Anthropic
    # only, exactly as before this feature existed.
    OPENAI_API_KEY: str = ""
    OPENAI_BASE_URL: str = "https://api.openai.com/v1/"
    GEMINI_API_KEY: str = ""
    # Google's OpenAI-compatible surface for the Gemini API.
    GEMINI_BASE_URL: str = "https://generativelanguage.googleapis.com/v1beta/openai/"

    # --- API Usage tracking (approximate cost, not a billing source of truth) ---
    # Anthropic has no pricing-lookup API, so this is a hand-maintained table of
    # published per-token rates, USD per MILLION tokens, keyed by the exact model
    # id string that shows up in an API response's `model` field. Every model this
    # app is actually configured to call (ANTHROPIC_MODEL,
    # ANTHROPIC_EXTRACTION_MODEL - see above) needs an entry here or its usage
    # rows cost $0 and a warning is logged (see core/pricing.py). Update this
    # table by hand whenever Anthropic changes prices or either model id above
    # changes to a version not yet listed.
    #
    # These numbers do NOT account for prompt caching: this app's LLM calls
    # (services/extraction.py, services/library/llm.py) do not set any caching
    # controls today, so every call is billed as a full, uncached prompt and this
    # table's estimate should match actual billing. If caching is ever added,
    # this becomes an overestimate for whichever calls use it.
    #
    # Despite the name (kept as-is so no deployment's .env has to change),
    # this now holds every model the app can be pointed at across all three
    # providers, not just Anthropic - model id strings from OpenAI ("gpt-..."),
    # Gemini ("gemini-...") and Anthropic ("claude-...") don't collide in
    # practice, so one flat table keyed by model id still works. The OpenAI
    # and Gemini rows below are seeded from each provider's public pricing
    # page at the time this was written and, same as the Anthropic rows,
    # need hand-checking against the provider's current docs before relying
    # on them - update/replace them the same way you would an Anthropic price
    # change, right here or from the Settings screen.
    ANTHROPIC_PRICING_USD_PER_MILLION_TOKENS: dict[str, dict[str, float]] = {
        "claude-sonnet-4-5-20250929": {"input": 3.00, "output": 15.00},
        "claude-haiku-4-5-20251001": {"input": 1.00, "output": 5.00},
        # Older ids, kept for a deployment mid-rollover between model versions
        # (config.py changed, a worker still mid-flight on the old id, or a
        # historical row whose model string predates a bump) rather than only
        # covering the two ids active right now.
        "claude-sonnet-4-20250514": {"input": 3.00, "output": 15.00},
        "claude-haiku-4-20250514": {"input": 1.00, "output": 5.00},
        "claude-3-5-haiku-20241022": {"input": 0.80, "output": 4.00},
        # OpenAI - verify against https://openai.com/api/pricing/ before relying on these.
        "gpt-4o": {"input": 2.50, "output": 10.00},
        "gpt-4o-mini": {"input": 0.15, "output": 0.60},
        # Gemini - verify against https://ai.google.dev/gemini-api/docs/pricing before relying on these.
        "gemini-flash-latest": {"input": 0.30, "output": 2.50},
        "gemini-pro-latest": {"input": 2.00, "output": 12.00},
    }

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
        # True if ANY provider has a .env-sourced key - a Settings-only key
        # (no .env key at all) still counts as available at the
        # app_settings.py level (see is_available() in services/library/llm.py,
        # which checks the DB override too); this property is just the .env
        # floor, same as before this app supported more than one provider.
        return self.LLM_ENABLED and bool(
            self.ANTHROPIC_API_KEY or self.OPENAI_API_KEY or self.GEMINI_API_KEY
        )

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
