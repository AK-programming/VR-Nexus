"""Grounded answer generation (/api/library/ask) with retrieval and the model stubbed.

The value of RAG is that answers are constrained to retrieved evidence, so what
matters here is the failure behaviour: no relevant chunks, a model that declines,
a model that answers without citing, and generation being unavailable. Each has
to produce a usable response rather than an invented one.
"""
import uuid

from app.models import DocumentCategory
from app.schemas import SearchHit
from app.services import llm, rag


def make_hit(content="Farmers pay for solar pumps in goats.", similarity=0.8, page=2):
    return SearchHit(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        original_filename="uptrade.pdf",
        title="UpTrade Case Study",
        category=DocumentCategory.CASE_STUDY,
        section_name="Approach",
        phase="",
        page_number=page,
        content=content,
        similarity=similarity,
        image_paths=[],
    )


def test_an_empty_library_declines_instead_of_answering(monkeypatch):
    """Nothing retrieved means nothing to ground an answer in."""
    monkeypatch.setattr(rag.search, "search", lambda *a, **k: [])

    called = []
    monkeypatch.setattr(rag.llm, "complete", lambda *a, **k: called.append(1) or "x")

    result = rag.answer(db=None, question="How do farmers pay?")

    assert result.answer == rag.NO_ANSWER
    assert not result.grounded
    assert result.sources == []
    # The model must not be paid for when there is no context to give it.
    assert not called


def test_a_cited_answer_is_grounded(monkeypatch):
    monkeypatch.setattr(rag.search, "search", lambda *a, **k: [make_hit()])
    monkeypatch.setattr(
        rag.llm, "complete", lambda *a, **k: "Farmers pay in livestock [1]."
    )

    result = rag.answer(db=None, question="How do farmers pay?")

    assert result.grounded
    assert result.sources[0].cited


def test_an_uncited_answer_is_not_grounded(monkeypatch):
    """An answer with no citation is the failure this endpoint exists to expose."""
    monkeypatch.setattr(rag.search, "search", lambda *a, **k: [make_hit()])
    monkeypatch.setattr(rag.llm, "complete", lambda *a, **k: "Farmers pay in cash.")

    result = rag.answer(db=None, question="How do farmers pay?")

    assert not result.grounded
    assert not result.sources[0].cited
    # The text is still returned so a reviewer can see what was produced.
    assert result.answer == "Farmers pay in cash."


def test_a_model_refusal_is_reported_as_ungrounded(monkeypatch):
    monkeypatch.setattr(rag.search, "search", lambda *a, **k: [make_hit()])
    monkeypatch.setattr(rag.llm, "complete", lambda *a, **k: rag.NO_ANSWER)

    result = rag.answer(db=None, question="What is the share price?")

    assert not result.grounded


def test_sources_survive_a_generation_failure(monkeypatch):
    """llm.complete returns "" on any failure; retrieval still succeeded, so the
    passages are worth handing back on their own."""
    monkeypatch.setattr(rag.search, "search", lambda *a, **k: [make_hit()])
    monkeypatch.setattr(rag.llm, "complete", lambda *a, **k: "")

    result = rag.answer(db=None, question="How do farmers pay?")

    assert not result.grounded
    assert len(result.sources) == 1
    assert "unavailable" in result.answer.lower()


def test_multiple_citations_in_one_bracket_are_read(monkeypatch):
    hits = [make_hit(), make_hit(content="Second passage.", page=4)]
    monkeypatch.setattr(rag.search, "search", lambda *a, **k: hits)
    monkeypatch.setattr(rag.llm, "complete", lambda *a, **k: "Both agree [1, 2].")

    result = rag.answer(db=None, question="How do farmers pay?")

    assert result.grounded
    assert all(s.cited for s in result.sources)


def test_a_citation_out_of_range_is_ignored(monkeypatch):
    """A model that invents [7] against one excerpt must not mark anything cited."""
    monkeypatch.setattr(rag.search, "search", lambda *a, **k: [make_hit()])
    monkeypatch.setattr(rag.llm, "complete", lambda *a, **k: "Something [7].")

    result = rag.answer(db=None, question="How do farmers pay?")

    assert not result.grounded


def test_the_relevance_floor_is_passed_to_retrieval(monkeypatch):
    """Vector search always returns its top-k, so an unrelated question would
    otherwise hand the model unrelated text."""
    seen = {}

    def fake_search(db, query, category=None, limit=10, min_similarity=0.0):
        seen["min_similarity"] = min_similarity
        return []

    monkeypatch.setattr(rag.search, "search", fake_search)
    rag.answer(db=None, question="Unrelated question about astrophysics")

    assert seen["min_similarity"] == rag.MIN_CONTEXT_SIMILARITY


def test_context_is_capped_and_citations_stay_in_range(monkeypatch):
    """Excerpts dropped for size must not remain citable — the numbers the model
    sees and the sources returned have to describe the same list."""
    big = [make_hit(content="x" * 9000) for _ in range(6)]
    monkeypatch.setattr(rag.search, "search", lambda *a, **k: big)
    monkeypatch.setattr(rag.llm, "complete", lambda *a, **k: "Answer [1].")

    result = rag.answer(db=None, question="How do farmers pay?")

    assert len(result.sources) < len(big)
    assert result.grounded


def test_a_blank_question_never_reaches_the_model(monkeypatch):
    called = []
    monkeypatch.setattr(rag.llm, "complete", lambda *a, **k: called.append(1) or "x")

    result = rag.answer(db=None, question="   ")

    assert not result.grounded
    assert not called


def test_blank_lines_in_chunk_text_do_not_inflate_the_excerpt_count(monkeypatch):
    """Chunk content contains its own paragraph breaks. Counting separators in
    the rendered context would overcount, leaving sources the model never saw."""
    hits = [make_hit(content="Para one.\n\nPara two.\n\nPara three.") for _ in range(2)]
    monkeypatch.setattr(rag.search, "search", lambda *a, **k: hits)
    monkeypatch.setattr(rag.llm, "complete", lambda *a, **k: "Answer [1].")

    result = rag.answer(db=None, question="How do farmers pay?")

    assert len(result.sources) == 2


def test_one_oversized_chunk_is_still_sent(monkeypatch):
    """A single chunk larger than the cap must not produce an empty context."""
    monkeypatch.setattr(
        rag.search, "search", lambda *a, **k: [make_hit(content="x" * 40000)]
    )
    monkeypatch.setattr(rag.llm, "complete", lambda *a, **k: "Answer [1].")

    result = rag.answer(db=None, question="How do farmers pay?")

    assert len(result.sources) == 1
    assert result.grounded


def test_the_system_prompt_forbids_outside_knowledge():
    """The grounding rule lives in the prompt; if it is edited away the endpoint
    silently becomes a general-purpose chatbot."""
    assert "ONLY" in rag.SYSTEM_PROMPT
    assert rag.NO_ANSWER in rag.SYSTEM_PROMPT
    assert "Do not guess" in rag.SYSTEM_PROMPT
