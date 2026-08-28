"""Chunker boundary behaviour (LIB-IDX-05).

Note the import: `app.services.library.chunking`, not `app.services.chunking`.
Both exist and both export `chunk_text`. The tender one uses ~2000-token
page-bounded windows and returns a different dataclass, so importing it here
would produce misleading results rather than an error.
"""
import pytest

from app.services.library import chunking


def test_short_text_is_one_chunk():
    chunks = chunking.chunk_text("A short sentence.", chunk_tokens=800, overlap_tokens=100)
    assert len(chunks) == 1
    assert chunks[0].token_count == chunking.count_tokens("A short sentence.")


def test_empty_text_produces_no_chunks():
    assert chunking.chunk_text("") == []
    assert chunking.chunk_text("   \n  ") == []


def test_overlap_must_be_smaller_than_chunk_size():
    with pytest.raises(ValueError, match="must be smaller"):
        chunking.chunk_text("word " * 500, chunk_tokens=100, overlap_tokens=100)

    with pytest.raises(ValueError):
        chunking.chunk_text("word " * 500, chunk_tokens=100, overlap_tokens=150)


def test_windows_respect_the_size_limit():
    text = " ".join(f"token{i}" for i in range(2000))
    chunks = chunking.chunk_text(text, chunk_tokens=100, overlap_tokens=20)

    assert len(chunks) > 1
    assert all(c.token_count <= 100 for c in chunks)


def test_consecutive_chunks_overlap():
    text = " ".join(f"w{i}" for i in range(600))
    chunks = chunking.chunk_text(text, chunk_tokens=100, overlap_tokens=30)

    assert len(chunks) >= 3

    # The overlap should make the tail of one chunk reappear at the head of the
    # next. Comparing decoded text rather than token ids keeps this readable.
    first_tail_words = chunks[0].content.split()[-10:]
    second_words = chunks[1].content.split()
    assert any(word in second_words for word in first_tail_words)


def test_no_trailing_chunk_that_is_pure_overlap():
    """A tail window made only of already-seen tokens adds nothing but cost."""
    text = " ".join(f"w{i}" for i in range(230))
    chunks = chunking.chunk_text(text, chunk_tokens=100, overlap_tokens=50)

    total_tokens = chunking.count_tokens(text)
    step = 100 - 50
    # Ceiling of the windows genuinely needed to cover the text.
    max_expected = (total_tokens + step - 1) // step
    assert len(chunks) <= max_expected


def test_exact_boundary_length_stays_one_chunk():
    """Text of exactly chunk_tokens length must not spill into a second window."""
    encoder = chunking._get_encoder()
    text = encoder.decode(encoder.encode(" ".join(f"w{i}" for i in range(400)))[:100])

    chunks = chunking.chunk_text(text, chunk_tokens=100, overlap_tokens=20)
    assert len(chunks) == 1


def test_defaults_match_the_requirement():
    """LIB-IDX-05 specifies ~800 tokens with 100-token overlap."""
    from app.core.config import get_settings

    settings = get_settings()

    assert settings.CHUNK_TOKENS == 800
    assert settings.CHUNK_OVERLAP_TOKENS == 100


def test_labels_ride_onto_every_chunk():
    text = " ".join(f"w{i}" for i in range(500))
    chunks = chunking.chunk_text(
        text,
        section_name="Challenge",
        phase="Phase 2",
        page_number=4,
        image_paths=["images/doc/p4_0.png"],
        chunk_tokens=100,
        overlap_tokens=20,
    )

    assert len(chunks) > 1
    for chunk in chunks:
        assert chunk.section_name == "Challenge"
        assert chunk.phase == "Phase 2"
        assert chunk.page_number == 4
        assert chunk.image_paths == ["images/doc/p4_0.png"]


def test_chunk_sections_never_spans_two_sections():
    """A chunk must not run Challenge into Solution — that would blur the vector."""
    from app.services.library.parsers.base import Section

    sections = [
        Section(name="Challenge", content="alpha " * 300, page_number=1),
        Section(name="Solution", content="beta " * 300, page_number=2),
    ]
    chunks = chunking.chunk_sections(sections)

    for chunk in chunks:
        if chunk.section_name == "Challenge":
            assert "beta" not in chunk.content
        else:
            assert "alpha" not in chunk.content


def test_chunk_sections_skips_empty_sections():
    from app.services.library.parsers.base import Section

    sections = [
        Section(name="Client", content="ACME Corp"),
        Section(name="Sector", content=""),
        Section(name="Scope", content="Delivery of a portal."),
    ]
    chunks = chunking.chunk_sections(sections)

    assert [c.section_name for c in chunks] == ["Client", "Scope"]
