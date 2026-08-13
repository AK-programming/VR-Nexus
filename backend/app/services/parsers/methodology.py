"""Methodology parsing (LIB-IDX-03) — split by phase or section.

Methodology documents are sequential, and that order is the useful signal: when
Stage 3 has to answer "what is your approach to data migration", the phase label
on the retrieved chunk tells the proposal writer where in the plan it belongs.

Explicit markers (`Phase 2`, `Step 4`, `Stage III`, `Module 1`) are matched
first, then numbered outline headings, then markdown headings promoted by
`extract.py` from Word/PowerPoint styles. The chat model is asked for an ordered
phase list only when none of those appear.
"""
from __future__ import annotations

import logging
import re

from app.models import DocumentCategory
from app.services import llm
from app.services.parsers import base
from app.services.parsers.base import ParseResult, RawDoc, Section

logger = logging.getLogger(__name__)

# "Phase 2 - Design", "Stage III: Build", "Step 4.", "Module 1 – Setup"
PHASE_MARKER_RE = re.compile(
    r"^\s*(?:#{1,6}\s*)?"
    r"(?P<kind>phase|stage|step|module|task|activity|work\s*package|milestone)"
    r"\s*[-–—:]?\s*"
    r"(?P<number>\d+(?:\.\d+)?|[IVXLC]+|one|two|three|four|five|six|seven|eight|nine|ten)"
    r"\s*[-–—:.)]?\s*(?P<title>.{0,80})$",
    re.IGNORECASE,
)

# "3. Data Migration", "3.2 Cutover Plan" — a numbered heading, not a numbered
# sentence, so the title must be short and must not end like prose.
NUMBERED_HEADING_RE = re.compile(
    r"^\s*(?P<number>\d+(?:\.\d+){0,2})[.)]\s+(?P<title>[A-Z][^.!?]{2,70})\s*:?\s*$"
)

# Markdown headings, which `extract.py` writes for Word Heading styles and
# PowerPoint slide titles.
MARKDOWN_HEADING_RE = re.compile(r"^\s*#{1,6}\s+(?P<title>.{2,80}?)\s*:?\s*$")

MAX_MARKER_LENGTH = 110

# One marker is not a structure — a document that mentions "Phase 1" once in a
# paragraph should not be split on it.
MIN_PHASES = 2

LLM_SAMPLE_CHARS = 6000


def _match_marker(line: str) -> str | None:
    """Return a normalised phase label if this line starts a phase."""
    stripped = line.strip()
    if not stripped or len(stripped) > MAX_MARKER_LENGTH:
        return None

    match = PHASE_MARKER_RE.match(stripped)
    if match:
        kind = match.group("kind").strip().title()
        number = match.group("number").strip().upper()
        title = match.group("title").strip(" -–—:.")
        label = f"{kind} {number}"
        return f"{label}: {title}" if title else label

    match = NUMBERED_HEADING_RE.match(stripped)
    if match:
        return f"{match.group('number')} {match.group('title').strip()}"

    match = MARKDOWN_HEADING_RE.match(stripped)
    if match:
        return match.group("title").strip()

    return None


def _heuristic_sections(raw: RawDoc) -> list[Section]:
    text = base.clean_text(raw.text)
    if not text:
        return []

    lines = text.split("\n")

    markers: list[tuple[str, int, int]] = []  # (label, char offset, line index)
    offset = 0
    for index, line in enumerate(lines):
        label = _match_marker(line)
        if label is not None:
            markers.append((label, offset, index))
        offset += len(line) + 1

    if len(markers) < MIN_PHASES:
        return []

    sections: list[Section] = []

    preamble = "\n".join(lines[: markers[0][2]]).strip()
    if preamble:
        page = raw.pages[0].number if raw.pages else 1
        sections.append(
            Section(
                name="Introduction",
                content=preamble,
                page_number=page,
                image_paths=raw.images_for_pages(page, page),
            )
        )

    for position, (label, char_offset, line_index) in enumerate(markers):
        next_line = markers[position + 1][2] if position + 1 < len(markers) else len(lines)
        # The marker line is kept in the body: "Phase 2 - Design" is itself
        # meaningful text for retrieval, not just a delimiter.
        content = "\n".join(lines[line_index:next_line]).strip()
        if not content:
            continue

        start_page = raw.page_for_offset(char_offset)
        end_offset = (
            markers[position + 1][1] if position + 1 < len(markers) else len(text)
        )
        end_page = raw.page_for_offset(max(end_offset - 1, char_offset))

        sections.append(
            Section(
                name=label,
                content=content,
                phase=label,
                page_number=start_page,
                image_paths=raw.images_for_pages(start_page, end_page),
            )
        )

    return sections


def _llm_sections(raw: RawDoc) -> list[Section]:
    """Ask for an ordered phase list when the document has no visible markers."""
    if not llm.is_available():
        return []

    text = base.clean_text(raw.text)[:LLM_SAMPLE_CHARS]
    if not text:
        return []

    prompt = (
        "Break this methodology document into its sequential phases.\n\n"
        'Return JSON of the form: {"phases": [{"name": "...", "content": "..."}]}\n'
        "Rules:\n"
        "- Keep the phases in the order the document presents them.\n"
        "- 'name' is a short label, e.g. 'Phase 1: Inception' or 'Requirements Analysis'.\n"
        "- 'content' is the text describing that phase.\n"
        "- Return an empty array if the document has no phase structure. "
        "Do not invent phases.\n\n"
        f"Methodology text:\n{text}"
    )

    result = llm.complete_json(
        prompt,
        system="You structure methodology documents into ordered phases. Reply with JSON only.",
    )
    if not isinstance(result, dict):
        return []

    phases = result.get("phases")
    if not isinstance(phases, list) or len(phases) < MIN_PHASES:
        return []

    page = raw.pages[0].number if raw.pages else 1
    sections: list[Section] = []
    for entry in phases:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "").strip()[:120]
        content = str(entry.get("content") or "").strip()
        if not name or not content:
            continue
        sections.append(
            Section(name=name, content=content, phase=name, page_number=page)
        )

    if len(sections) < MIN_PHASES:
        return []

    # As with case studies, keep the verbatim document alongside the model's
    # phase summaries so retrieval can quote the source.
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

    return sections


def parse(raw: RawDoc, use_llm: bool = True) -> ParseResult:
    result = ParseResult(warnings=list(raw.warnings))

    sections = _heuristic_sections(raw)
    if sections:
        result.sections = sections
        phases = [s.phase for s in sections if s.phase]
        result.doc_metadata = {"phases": phases}
        return result

    if use_llm:
        sections = _llm_sections(raw)
        if sections:
            result.sections = sections
            result.used_llm = True
            result.doc_metadata = {"phases": [s.phase for s in sections if s.phase]}
            result.warnings.append("Phases derived by LLM; no phase markers were found.")
            return result

    result.sections = base.whole_document_section(raw, name="Methodology")
    result.warnings.append(
        "No phase structure could be identified; indexed as a single section."
    )
    return result


base.register(DocumentCategory.METHODOLOGY, parse)
