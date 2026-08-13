"""Shared test fixtures.

Tests must run with no database, no Redis, no network and no downloaded model.
Anything that would reach outside the process is stubbed here.
"""
import os
import sys
import tempfile
from pathlib import Path

import pytest

# Point storage somewhere writable before app.config is imported, since settings
# are read once at import time.
_TMP_STORAGE = tempfile.mkdtemp(prefix="evidence_test_")
os.environ.setdefault("STORAGE_DIR", _TMP_STORAGE)
os.environ.setdefault("OPENAI_API_KEY", "")
os.environ.setdefault("LLM_ENABLED", "false")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import embeddings  # noqa: E402
from app.services.parsers.base import Page, RawDoc  # noqa: E402


class StubEmbeddingProvider(embeddings.EmbeddingProvider):
    """Deterministic fake vectors — no ONNX model, no download.

    Values are derived from the text so that identical text yields identical
    vectors, which is what duplicate-detection tests need.
    """

    def __init__(self, dimension: int = 384):
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
    from app.services import llm

    monkeypatch.setattr(llm, "is_available", lambda: False)


@pytest.fixture
def storage_dir(tmp_path, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "STORAGE_DIR", str(tmp_path))
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
