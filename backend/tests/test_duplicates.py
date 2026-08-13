"""Duplicate detection (LIB-UI-06) with the database stubbed out.

`check_duplicate` combines a hash lookup and a vector query. These tests replace
both so the decision logic — which signal wins, when the embedding is paid for —
is verified without PostgreSQL.
"""
import uuid

import pytest

from app.schemas import DuplicateMatch
from app.services import search


class FakeDocument:
    def __init__(self, original_filename="existing.pdf", title="Existing"):
        self.id = uuid.uuid4()
        self.original_filename = original_filename
        self.title = title


def test_exact_hash_match_is_a_hard_block(monkeypatch):
    existing = FakeDocument()
    monkeypatch.setattr(search, "find_by_hash", lambda *a, **k: existing)

    result = search.check_duplicate(db=None, file_hash="a" * 64, text="some text")

    assert result.is_exact
    assert result.exact_match.document_id == existing.id
    assert result.exact_match.similarity == 1.0
    assert result.has_warning


def test_exact_match_skips_the_embedding_call(monkeypatch):
    """No point paying for a vector when the hash already decided."""
    monkeypatch.setattr(search, "find_by_hash", lambda *a, **k: FakeDocument())

    called = []
    monkeypatch.setattr(
        search, "find_near_duplicates", lambda *a, **k: called.append(1) or []
    )

    search.check_duplicate(db=None, file_hash="a" * 64, text="some text")
    assert not called


def test_near_matches_are_advisory_not_a_block(monkeypatch):
    near = DuplicateMatch(
        document_id=uuid.uuid4(),
        original_filename="similar.pdf",
        title="Similar",
        similarity=0.96,
    )
    monkeypatch.setattr(search, "find_by_hash", lambda *a, **k: None)
    monkeypatch.setattr(search, "find_near_duplicates", lambda *a, **k: [near])

    result = search.check_duplicate(db=None, file_hash="b" * 64, text="text")

    assert not result.is_exact
    assert result.near_matches == [near]
    assert result.has_warning


def test_no_duplicate_produces_no_warning(monkeypatch):
    monkeypatch.setattr(search, "find_by_hash", lambda *a, **k: None)
    monkeypatch.setattr(search, "find_near_duplicates", lambda *a, **k: [])

    result = search.check_duplicate(db=None, file_hash="c" * 64, text="text")

    assert not result.has_warning
    assert result.exact_match is None


def test_a_failed_similarity_check_does_not_block_the_upload(monkeypatch):
    """The hash check already ran and is authoritative; a vector failure is not fatal."""
    monkeypatch.setattr(search, "find_by_hash", lambda *a, **k: None)

    def boom(*args, **kwargs):
        raise RuntimeError("pgvector unavailable")

    monkeypatch.setattr(search, "find_near_duplicates", boom)

    result = search.check_duplicate(db=None, file_hash="d" * 64, text="text")

    assert not result.is_exact
    assert result.near_matches == []


def test_semantic_check_is_skipped_without_text(monkeypatch):
    """An image upload yields no cheap sample, so only the hash check runs."""
    monkeypatch.setattr(search, "find_by_hash", lambda *a, **k: None)

    called = []
    monkeypatch.setattr(
        search, "find_near_duplicates", lambda *a, **k: called.append(1) or []
    )

    search.check_duplicate(db=None, file_hash="e" * 64, text="")
    assert not called


def test_empty_text_yields_no_near_duplicates():
    assert search.find_near_duplicates(db=None, text="") == []
    assert search.find_near_duplicates(db=None, text="   ") == []


def test_default_threshold_is_strict():
    """A near-duplicate warning must be rare enough to be worth reading."""
    from app.config import settings

    assert settings.DUPLICATE_SIMILARITY_THRESHOLD >= 0.90


def test_empty_query_returns_no_hits():
    assert search.search(db=None, query="") == []
    assert search.search(db=None, query="  ") == []
