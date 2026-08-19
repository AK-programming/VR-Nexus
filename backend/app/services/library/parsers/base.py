"""Shared parser types and the category registry.

`extract.py` turns any supported file into one `RawDoc`. Each category parser
then turns that `RawDoc` into `Section` objects. Splitting it this way means the
file-format problem is solved once, and the three category parsers (LIB-IDX-02,
-03, -04) only ever deal with text and page numbers.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from app.models.enums import DocumentCategory


@dataclass
class Page:
    """One page (PDF), paragraph block (DOCX) or slide (PPTX)."""

    number: int
    text: str = ""
    # Paths are storage-relative, e.g. "images/<doc_id>/p1_0.png". Kept relative
    # so the library survives a change of STORAGE_DIR.
    image_paths: list[str] = field(default_factory=list)
    ocr_applied: bool = False


@dataclass
class RawDoc:
    """Format-agnostic extraction result."""

    filename: str
    pages: list[Page] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def page_count(self) -> int:
        return len(self.pages)

    @property
    def text(self) -> str:
        """Full document text, pages joined in order."""
        return "\n\n".join(p.text for p in self.pages if p.text.strip())

    @property
    def image_paths(self) -> list[str]:
        paths: list[str] = []
        for page in self.pages:
            paths.extend(page.image_paths)
        return paths

    def page_for_offset(self, offset: int) -> int:
        """Map a character offset in `text` back to a page number.

        Section parsers work on the joined text but chunks need a page label, so
        the offset where a section started is translated back here.
        """
        running = 0
        last = self.pages[0].number if self.pages else 0
        for page in self.pages:
            if not page.text.strip():
                continue
            running += len(page.text) + 2  # the "\n\n" join
            last = page.number
            if offset < running:
                return page.number
        return last

    def images_for_pages(self, first: int, last: int) -> list[str]:
        paths: list[str] = []
        for page in self.pages:
            if first <= page.number <= last:
                paths.extend(page.image_paths)
        return paths


@dataclass
class Section:
    """A logical unit of a document, ready for chunking.

    Field names match what `chunking.chunk_sections()` reads via getattr, so a
    section's labels ride onto every chunk cut from it.
    """

    name: str = ""
    content: str = ""
    phase: str = ""
    page_number: int = 0
    image_paths: list[str] = field(default_factory=list)


@dataclass
class ParseResult:
    sections: list[Section] = field(default_factory=list)
    # Facts the parser learned that belong on the document row rather than on a
    # chunk — e.g. a case study's Client line, a certificate's doc type.
    doc_metadata: dict = field(default_factory=dict)
    used_llm: bool = False
    warnings: list[str] = field(default_factory=list)

    @property
    def section_names(self) -> list[str]:
        return [s.name for s in self.sections if s.name]


# Populated by each category module at import time via `register`.
_REGISTRY: dict[DocumentCategory, Callable[[RawDoc, bool], ParseResult]] = {}


def register(category: DocumentCategory, parser: Callable[[RawDoc, bool], ParseResult]) -> None:
    _REGISTRY[category] = parser


def get_parser(category: DocumentCategory) -> Callable[[RawDoc, bool], ParseResult]:
    """Look up the parser for a category.

    Importing `app.services.parsers.registry` is what populates the table; a
    KeyError here means that import was skipped.
    """
    try:
        return _REGISTRY[category]
    except KeyError:  # pragma: no cover - defensive
        raise KeyError(
            f"No parser registered for category {category!r}. "
            "Import app.services.parsers.registry to load the built-in parsers."
        ) from None


def parse(category: DocumentCategory, raw: RawDoc, use_llm: bool = True) -> ParseResult:
    return get_parser(category)(raw, use_llm)


# ---------------------------------------------------------------------------
# Helpers shared by the category parsers
# ---------------------------------------------------------------------------

def clean_text(text: str) -> str:
    """Normalise whitespace without destroying paragraph breaks."""
    import re

    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def whole_document_section(raw: RawDoc, name: str = "", phase: str = "") -> list[Section]:
    """Fallback used whenever no structure could be found: one section covering
    everything, so a document is always indexed rather than silently dropped."""
    text = clean_text(raw.text)
    if not text:
        return []
    first = raw.pages[0].number if raw.pages else 1
    return [
        Section(
            name=name,
            content=text,
            phase=phase,
            page_number=first,
            image_paths=raw.image_paths,
        )
    ]
