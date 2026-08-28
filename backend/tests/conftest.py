"""Shared test fixtures.

Tests must run with no database, no Redis, no network and no downloaded model.
Anything that would reach outside the process is stubbed here.

Re-pathed onto the merged backend. The originals came from the flat prototype
and imported `app.config`, `app.services.embeddings` and
`app.services.parsers.base` — all three are tombstones now. Three changes:

  * Imports moved to `app.core.config` / `app.services.library.*`. Worth being
    precise about why this matters more than it looks: `app.services.chunking`
    and `app.services.library.chunking` both exist in the merged tree and both
    export `chunk_text`. The flat import path still resolves — it just resolves
    to the *tender* chunker, which is tuned to ~2000-token page-bounded windows
    and returns a different dataclass. Left unfixed, these tests would have run
    green-ish against the wrong module rather than failing loudly.

  * The environment bootstrap below is new and is required, not defensive.

  * `StubEmbeddingProvider`'s default width is `settings.EMBEDDING_DIM` rather
    than a literal 384. Nothing asserts the number — the fake vectors never
    reach a pgvector column — but a stub narrower than the real
    `chunks.embedding` invites the reader to believe the schema is 384-wide.
"""
import os
import sys
import tempfile
from pathlib import Path

import pytest

# --- Environment bootstrap -------------------------------------------------
# Order matters. Every import below this block reaches app.core.config, whose
# Settings declares five fields with no default — DATABASE_URL, REDIS_URL,
# CELERY_BROKER_URL, CELERY_RESULT_BACKEND, JWT_SECRET_KEY — and which is
# @lru_cache'd on first call. Without these lines the suite does not fail in a
# test; it fails at collection with a pydantic ValidationError, before a single
# assertion runs.
#
# The values are placeholders, not connection targets. Nothing in this suite
# opens a socket: every database-touching function is called with db=None and
# its queries monkeypatched, and the embedding provider is stubbed. A
# syntactically valid DSN is all pydantic asks for.
#
# setdefault, not assignment: a caller who has already exported real values
# (CI, or someone debugging against a scratch database) keeps them.
os.environ.setdefault(
    "DATABASE_URL", "postgresql+psycopg://test:test@localhost:5432/test_unused"
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")
os.environ.setdefault("CELERY_BROKER_URL", "redis://localhost:6379/15")
os.environ.setdefault("CELERY_RESULT_BACKEND", "redis://localhost:6379/15")
os.environ.setdefault("JWT_SECRET_KEY", "test-only-not-a-real-secret")

# Storage has to point somewhere writable. The merged Settings replaced the flat
# backend's single STORAGE_DIR with four roots; these tests only exercise the
# library one. Setting STORAGE_DIR here would do nothing at all — Settings is
# configured with extra="ignore", so it would be swallowed rather than raising,
# and every path would quietly fall back to ./storage in the repo.
_TMP_STORAGE = tempfile.mkdtemp(prefix="evidence_test_")
os.environ.setdefault("STORAGE_ROOT", _TMP_STORAGE)
os.environ.setdefault("LIBRARY_STORAGE_DIR", _TMP_STORAGE)

# LLM off, and no key, so nothing can reach a provider even if a test forgets to
# stub. Environment variables take precedence over the dotenv file in
# pydantic-settings, so these win over whatever backend/.env happens to hold —
# which is the point: the suite must behave identically on a developer machine
# with a configured .env and on a clean checkout without one.
os.environ.setdefault("OPENAI_API_KEY", "")
os.environ.setdefault("LLM_ENABLED", "false")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402
from app.services.library import embeddings  # noqa: E402
from app.services.library.parsers.base import Page, RawDoc  # noqa: E402

settings = get_settings()


class StubEmbeddingProvider(embeddings.EmbeddingProvider):
    """Deterministic fake vectors — no ONNX model, no download.

    Values are derived from the text so that identical text yields identical
    vectors, which is what duplicate-detection tests need.
    """

    def __init__(self, dimension: int = settings.EMBEDDING_DIM):
        self.dimension = dimension
        self.calls: list[list[str]] = []

    def _vector(self, text: str) -> list[float]:
        seed = sum(ord(c) for c in text) or 1
        return [((seed * (i + 1)) % 100) / 100.0 for i in range(self.dimension)]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        return [self._vector(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)


@pytest.fixture
def stub_embeddings():
    provider = StubEmbeddingProvider()
    embeddings.set_provider(provider)
    yield provider
    embeddings.set_provider(None)


@pytest.fixture(autouse=True)
def no_llm(monkeypatch):
    """LLM off by default. A test that wants the fallback path stubs it itself."""
    from app.services.library import llm

    monkeypatch.setattr(llm, "is_available", lambda: False)


@pytest.fixture
def storage_dir(tmp_path, monkeypatch):
    """Point library storage at a per-test directory.

    Patching the attribute on the Settings instance rather than the environment
    is deliberate: get_settings() is @lru_cache'd and every service module holds
    a reference to that one object (`_settings = get_settings()` at import), so
    mutating the instance is visible everywhere. Re-reading the environment
    would not be, because the cache is already warm by the time a fixture runs.
    """
    monkeypatch.setattr(settings, "LIBRARY_STORAGE_DIR", str(tmp_path))
    return tmp_path


def make_raw(text: str, filename: str = "test.pdf", pages: list[str] | None = None) -> RawDoc:
    """Build a RawDoc without touching the filesystem."""
    if pages is None:
        pages = [text]
    return RawDoc(
        filename=filename,
        pages=[Page(number=i + 1, text=p) for i, p in enumerate(pages)],
    )


CASE_STUDY_TEXT = """National Health Portal Modernisation

Client: Ministry of Health, Punjab
Sector: Healthcare

Scope
Design and delivery of a province-wide patient records portal serving 240 public
hospitals and clinics, including data migration from twelve legacy systems.

Challenge
Patient records were held in twelve incompatible legacy systems. Clinicians could
not retrieve a patient's history across facilities, and the ministry had no
reliable reporting on service delivery.

Solution
We built a unified records platform on a cloud-hosted microservice architecture,
with an offline-capable client for facilities on intermittent connectivity. A
staged migration moved 4.2 million records without interrupting service.

Results
Retrieval time for a full patient history fell from days to seconds. The ministry
now produces monthly service-delivery reporting that previously took a quarter to
compile. The platform has been live for 18 months with 99.8% uptime.
"""

METHODOLOGY_TEXT = """Implementation Methodology

Our delivery approach is organised into four sequential phases, each with defined
entry and exit criteria.

Phase 1 - Inception
We establish the project governance structure, confirm scope against the terms of
reference, and agree the communication plan with the client's focal points.

Phase 2 - Requirements Analysis
Structured workshops with each user group produce a documented requirements
baseline. Every requirement is traceable to a stated business need.

Phase 3 - Design and Build
Development proceeds in two-week iterations. Each iteration ends with a working
increment demonstrated to the client.

Phase 4 - Deployment and Handover
Deployment follows a staged rollout. Handover includes documentation, training
for administrators, and a defined support transition.
"""

COMPANY_DOC_TEXT = """CERTIFICATE OF REGISTRATION

This is to certify that DPL Technologies (Private) Limited has been registered
under the Companies Act.

Registration No: K-12345/2019
NTN: 7654321-8
Date of Issue: 15-03-2019
Issued by: Securities and Exchange Commission of Pakistan

Registered Office: 12 Business District, Karachi, Sindh, Pakistan
"""
