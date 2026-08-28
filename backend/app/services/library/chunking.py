"""Token-window chunking (LIB-IDX-05) — ~800 tokens, 100-token overlap.

Chunking happens *within* a section, never across one, so a chunk never spans
Challenge into Solution. That keeps each vector semantically coherent and lets
section/phase/page labels ride along onto every chunk.

Deliberately separate from app/services/chunking.py, which chunks tender
documents into larger page-bounded passages. Same idea, different tuning and
different output type; they are not interchangeable.
"""
import logging
from dataclasses import dataclass, field

from app.core.config import get_settings

_settings = get_settings()

logger = logging.getLogger(__name__)

_encoder = None


def _get_encoder():
    global _encoder
    if _encoder is None:
        import tiktoken

        # cl100k_base is a reasonable general-purpose tokenizer; the exact model
        # family matters little since we only need consistent token *counts*.
        _encoder = tiktoken.get_encoding("cl100k_base")
    return _encoder


def count_tokens(text: str) -> int:
    return len(_get_encoder().encode(text))


@dataclass
class Chunk:
    content: str
    token_count: int
    section_name: str = ""
    phase: str = ""
    page_number: int = 0
    image_paths: list[str] = field(default_factory=list)


def chunk_text(
    text: str,
    section_name: str = "",
    phase: str = "",
    page_number: int = 0,
    image_paths: list[str] | None = None,
    chunk_tokens: int | None = None,
    overlap_tokens: int | None = None,
) -> list[Chunk]:
    """Split text into overlapping token windows."""
    size = chunk_tokens or _settings.CHUNK_TOKENS
    overlap = overlap_tokens or _settings.CHUNK_OVERLAP_TOKENS
    images = image_paths or []

    if overlap >= size:
        raise ValueError(f"overlap ({overlap}) must be smaller than chunk size ({size})")

    text = text.strip()
    if not text:
        return []

    encoder = _get_encoder()
    tokens = encoder.encode(text)

    if len(tokens) <= size:
        return [
            Chunk(
                content=text,
                token_count=len(tokens),
                section_name=section_name,
                phase=phase,
                page_number=page_number,
                image_paths=list(images),
            )
        ]

    chunks: list[Chunk] = []
    step = size - overlap
    start = 0

    while start < len(tokens):
        window = tokens[start : start + size]
        if not window:
            break

        chunks.append(
            Chunk(
                content=encoder.decode(window).strip(),
                token_count=len(window),
                section_name=section_name,
                phase=phase,
                page_number=page_number,
                image_paths=list(images),
            )
        )

        # Last window reached the end — stop rather than emitting a tail that is
        # entirely overlap.
        if start + size >= len(tokens):
            break
        start += step

    return chunks


def chunk_sections(sections: list) -> list[Chunk]:
    """Chunk a parser's Section list, preserving each section's labels.

    Takes ``Section`` objects from app.services.library.parsers.base (duck-typed here to
    avoid a circular import).
    """
    chunks: list[Chunk] = []
    for section in sections:
        chunks.extend(
            chunk_text(
                section.content,
                section_name=getattr(section, "name", ""),
                phase=getattr(section, "phase", ""),
                page_number=getattr(section, "page_number", 0),
                image_paths=getattr(section, "image_paths", []),
            )
        )
    return chunks
