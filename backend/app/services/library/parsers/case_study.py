"""Case study parsing (LIB-IDX-02).

Resolves the six canonical sections — Client, Sector, Scope, Challenge,
Solution, Results — plus their common synonyms. Headings in real case studies
are rarely the canonical word: "Background" means Challenge, "Approach" means
Solution, "Impact" means Results.

If fewer than three of the six resolve, the document is probably prose without
headings, and the chat model is asked for a section map instead. Falling back to
one undifferentiated blob is the last resort, not the second.

Images extracted by `extract.py` are attached to the section covering their page
by **path only** (LIB-IDX-02); no pixel data enters chunk content.
"""
from __future__ import annotations

import logging
import re

from app.models.enums import DocumentCategory
from app.services.library import llm
from app.services.library.parsers import base
from app.services.library.parsers.base import ParseResult, RawDoc, Section

logger = logging.getLogger(__name__)

CANONICAL_SECTIONS = ("Client", "Sector", "Scope", "Challenge", "Solution", "Results")

# Ordered longest-phrase-first within each entry so "project scope" is matched
# before a bare "scope".
SECTION_SYNONYMS: dict[str, tuple[str, ...]] = {
    "Client": ("client", "customer", "client name", "prepared for", "submitted to", "beneficiary"),
    "Sector": ("sector", "industry", "domain", "vertical"),
    "Scope": (
        "scope of work", "project scope", "scope", "services provided",
        "assignment", "project brief", "objectives", "project overview",
    ),
    "Challenge": (
        "challenge", "challenges", "the challenge", "problem statement", "problem",
        "background", "context", "situation", "need", "pain points",
    ),
    "Solution": (
        "solution", "the solution", "our solution", "approach", "our approach",
        "methodology", "what we did", "implementation", "delivery",
    ),
    "Results": (
        "results", "the results", "outcome", "outcomes", "impact", "benefits",
        "achievements", "key results", "value delivered", "conclusion",
    ),
}

# A heading is a short line, optionally prefixed by markdown, a bullet or an
# outline number, and optionally suffixed with a colon.
_HEADING_RE = re.compile(
    r"^\s*(?:#{1,6}\s*)?(?:[-*•]\s*)?(?:\d+(?:\.\d+)*[.)]?\s*)?"
    r"(?P<label>[A-Za-z][A-Za-z &/’’-]{2,60})\s*:?\s*(?P<inline>.*)$"
)

# Above this length a line is body text that happens to start with a keyword,
# not a heading.
MAX_HEADING_LENGTH = 90

# A label section like "Client: ACME Corp" carries its value inline; anything
# longer than this is prose and stays as section body.
MAX_INLINE_VALUE = 200

LABEL_SECTIONS = ("Client", "Sector")

MIN_SECTIONS_FOR_HEURISTIC = 3

LLM_SAMPLE_CHARS = 6000

# Reverse lookup: synonym -> canonical name, longest synonyms first so a more
# specific phrase wins.
_SYNONYM_LOOKUP: dict[str, str] = {}
for _canonical, _synonyms in SECTION_SYNONYMS.items():
    for _synonym in _synonyms:
        _SYNONYM_LOOKUP.setdefault(_synonym, _canonical)
_SORTED_SYNONYMS = sorted(_SYNONYM_LOOKUP, key=len, reverse=True)


def _match_heading(line: str) -> tuple[str, str] | None:
    """Return (canonical name, inline value) if this line is a section heading."""
    stripped = line.strip()
    if not stripped or len(stripped) > MAX_HEADING_LENGTH:
        return None

    match = _HEADING_RE.match(stripped)
    if not match:
        return None

    label = match.group("label").strip().lower().rstrip(":").strip()
    inline = match.group("inline").strip()

    canonical = _SYNONYM_LOOKUP.get(label)
    if canonical is None:
        # Allow a small amount of decoration, e.g. "The Challenge We Faced".
        for synonym in _SORTED_SYNONYMS:
            if label.startswith(synonym) and len(label) - len(synonym) <= 12:
                canonical = _SYNONYM_LOOKUP[synonym]
                break

    if canonical is None:
        return None

    # A heading followed by a long sentence on the same line is prose.
    if inline and len(inline) > MAX_INLINE_VALUE:
        return None

    return canonical, inline


def _heuristic_sections(raw: RawDoc) -> tuple[list[Section], dict]:
    text = base.clean_text(raw.text)
    if not text:
        return [], {}

    lines = text.split("\n")

    # (canonical, inline value, char offset of the line, index into `lines`)
    markers: list[tuple[str, str, int, int]] = []
    offset = 0
    for index, line in enumerate(lines):
        matched = _match_heading(line)
        if matched is not None:
            markers.append((matched[0], matched[1], offset, index))
        offset += len(line) + 1

    if not markers:
        return [], {}

    ordered: list[tuple[str, str]] = []  # (canonical, content)
    seen: dict[str, int] = {}

    def add(name: str, content: str) -> None:
        content = content.strip()
        if not content:
            return
        if name in seen:
            # Duplicate heading (a two-part "Results" say) — append rather than
            # discard, so no text is lost.
            position = seen[name]
            ordered[position] = (name, f"{ordered[position][1]}\n\n{content}")
        else:
            seen[name] = len(ordered)
            ordered.append((name, content))

    offsets: dict[str, int] = {}

    # Anything before the first heading is the title and lead paragraph.
    preamble = "\n".join(lines[: markers[0][3]]).strip()

    for position, (name, inline, char_offset, line_index) in enumerate(markers):
        next_line = markers[position + 1][3] if position + 1 < len(markers) else len(lines)
        body = "\n".join(lines[line_index + 1 : next_line]).strip()

        if name in LABEL_SECTIONS and inline:
            # "Client: ACME Corp" — the value is the whole section, and the text
            # that follows belongs to whatever comes next, not to Client.
            content = inline
        elif inline and body:
            content = f"{inline}\n{body}"
        else:
            content = inline or body

        if content:
            offsets.setdefault(name, char_offset)
            add(name, content)

    if len({name for name, _ in ordered}) < MIN_SECTIONS_FOR_HEURISTIC:
        return [], {}

    sections: list[Section] = []
    if preamble:
        page = raw.pages[0].number if raw.pages else 1
        sections.append(
            Section(
                name="Overview",
                content=preamble,
                page_number=page,
                image_paths=raw.images_for_pages(page, page),
            )
        )

    for name, content in ordered:
        page = raw.page_for_offset(offsets.get(name, 0))
        sections.append(
            Section(
                name=name,
                content=content,
                page_number=page,
                image_paths=raw.images_for_pages(page, page),
            )
        )

    doc_metadata = {}
    for key in LABEL_SECTIONS:
        position = seen.get(key)
        if position is not None:
            value = ordered[position][1].strip()
            if value and len(value) <= MAX_INLINE_VALUE:
                doc_metadata[key.lower()] = value

    return sections, doc_metadata


def _llm_sections(raw: RawDoc) -> tuple[list[Section], dict]:
    """Ask the chat model to map unstructured prose onto the six sections."""
    if not llm.is_available():
        return [], {}

    text = base.clean_text(raw.text)[:LLM_SAMPLE_CHARS]
    if not text:
        return [], {}

    prompt = (
        "Split this case study into the six standard sections.\n\n"
        "Return a JSON object with exactly these keys: "
        "client, sector, scope, challenge, solution, results\n"
        "Rules:\n"
        "- 'client' and 'sector' are short values (a name, an industry).\n"
        "- The other four are passages copied or closely summarised from the text.\n"
        "- Use \"\" for a section the document does not cover. Do not invent content.\n\n"
        f"Case study text:\n{text}"
    )

    result = llm.complete_json(
        prompt,
        system=(
            "You structure business case studies into labelled sections. "
            "Reply with JSON only."
        ),
    )
    if not isinstance(result, dict):
        return [], {}

    page = raw.pages[0].number if raw.pages else 1
    sections: list[Section] = []
    doc_metadata: dict = {}

    for name in CANONICAL_SECTIONS:
        value = result.get(name.lower())
        if not isinstance(value, str):
            continue
        value = value.strip()
        if not value:
            continue
        if name in LABEL_SECTIONS:
            doc_metadata[name.lower()] = value[:MAX_INLINE_VALUE]
        sections.append(
            Section(
                name=name,
                content=value,
                page_number=page,
                image_paths=raw.images_for_pages(page, page) if name == "Scope" else [],
            )
        )

    if len(sections) < MIN_SECTIONS_FOR_HEURISTIC:
        return [], {}

    # The model returns a *summary* of each section, so the verbatim text is kept
    # alongside it. Retrieval should be able to quote the document, not only the
    # model's paraphrase of it.
    full = base.clean_text(raw.text)
    if full:
        sections.append(
            Section(
                name="Full Text",
                content=full,
                page_number=page,
                image_paths=raw.image_paths,
            )
        )

    return sections, doc_metadata


def parse(raw: RawDoc, use_llm: bool = True) -> ParseResult:
    sections, doc_metadata = _heuristic_sections(raw)
    result = ParseResult(warnings=list(raw.warnings))

    if sections:
        result.sections = sections
        result.doc_metadata = doc_metadata
        missing = [n for n in CANONICAL_SECTIONS if n not in {s.name for s in sections}]
        if missing:
            result.warnings.append(
                "Sections not found by heading match: " + ", ".join(missing)
            )
        return result

    if use_llm:
        sections, doc_metadata = _llm_sections(raw)
        if sections:
            result.sections = sections
            result.doc_metadata = doc_metadata
            result.used_llm = True
            result.warnings.append("Sections derived by LLM; no usable headings were found.")
            return result

    # Indexed as one unit rather than dropped — an unstructured case study is
    # still searchable, just without section labels.
    result.sections = base.whole_document_section(raw, name="Document")
    result.warnings.append(
        "No case study sections could be identified; indexed as a single section."
    )
    return result


base.register(DocumentCategory.CASE_STUDY, parse)
