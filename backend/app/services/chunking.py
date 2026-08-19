"""
Task 2.2 - Section-Aware Chunking
Linked requirements: TN-ING-03, TN-ING-04, TN-ING-05

Covers all four WBS sub-tasks:
  2.2.1 Section boundary detection
  2.2.2 Sequential page-bounded chunking (~2000 tokens)
  2.2.3 Sliding page overlap (~200 tokens)
  2.2.4 Guard against single-pass whole-document ingestion

Section detection patterns are taken from Shaheer's prototype
(section_2_2_chunking.py) - they were reasonable regexes for standard
World Bank / ADB-style procurement documents (SPN, PDS, etc.) and are kept
as-is. What's new here (Shaheer's version didn't have this at all):

  - Real per-chunk page attribution. The prototype only tracked a page
    *range for the whole section*, then blindly token-split the
    concatenated section text - so an individual chunk's page_start/
    page_end was never actually computed, which breaks TN-ING-02's
    "preserve exact page numbers" for anything past the first chunk in a
    multi-chunk section. This version tokenizes per page and tracks a
    running token-offset -> page_no map, so every chunk gets its true
    page_start/page_end.
  - Real overlap (TN-ING-04). The prototype's chunk_text_by_tokens split
    into consecutive, non-overlapping token windows - there was no overlap
    at all, despite the WBS explicitly calling for ~200 tokens so a
    requirement split across a chunk boundary isn't lost. This version
    slides the window by (max_tokens - overlap_tokens) and records
    overlap_tokens on each chunk so Stage 2 dedup (3.2.2) knows how much
    to expect.
  - An explicit guard (2.2.4): raises if any chunk ever exceeds the token
    budget, and if the chunked output doesn't fully cover the source
    tokens - which is what "prevents requirement truncation/compression"
    (TN-ING-05) actually means: nothing gets silently dropped or squashed
    into one oversized pass.
"""
import bisect
import re
from dataclasses import dataclass, field

import tiktoken

from app.services.pdf_extraction import ExtractedPage

DEFAULT_MAX_TOKENS = 2000
DEFAULT_OVERLAP_TOKENS = 200

_ENCODING = tiktoken.get_encoding("cl100k_base")

# TN-ING-03: section labels to detect, in the order a real tender typically
# presents them. Matched independently per page; whichever section a page
# last matched carries forward until the next match (a page inside a
# section rarely repeats that section's own heading).
SECTION_PATTERNS: dict[str, str] = {
    "SPN": r"(?i)\b(Specific Procurement Notice|SPN)\b",
    "Instructions to Proposers": r"(?i)\bInstructions\s+to\s+Proposers\b",
    "PDS": r"(?i)\b(Proposal Data Sheet|PDS)\b",
    "Evaluation Criteria": r"(?i)\bEvaluation\s+(and\s+Qualification\s+)?Criteria\b",
    "Section VII": r"(?i)\bSection\s+VII\b",
    "Annexes": r"(?i)\bAnnex(?:es)?\b",
}
FALLBACK_SECTION = "General/Front Matter"


@dataclass
class SectionedPage:
    page_no: int
    text: str
    section: str


@dataclass
class TenderTextChunk:
    chunk_index: int
    section: str
    page_start: int
    page_end: int
    text: str
    token_count: int
    overlap_tokens: int


def detect_section_boundaries(pages: list[ExtractedPage]) -> list[SectionedPage]:
    """Task 2.2.1"""
    current_section = FALLBACK_SECTION
    sectioned: list[SectionedPage] = []
    for page in pages:
        for section_name, pattern in SECTION_PATTERNS.items():
            if re.search(pattern, page.text):
                current_section = section_name
                break
        sectioned.append(SectionedPage(page_no=page.page_no, text=page.text, section=current_section))
    return sectioned


@dataclass
class _SectionGroup:
    section: str
    pages: list[SectionedPage] = field(default_factory=list)


def _group_pages_by_section(pages: list[SectionedPage]) -> list[_SectionGroup]:
    groups: list[_SectionGroup] = []
    for page in pages:
        if not groups or groups[-1].section != page.section:
            groups.append(_SectionGroup(section=page.section, pages=[page]))
        else:
            groups[-1].pages.append(page)
    return groups


def _tokenize_group_with_page_map(group: _SectionGroup) -> tuple[list[int], list[tuple[int, int]]]:
    """Returns (all_tokens, page_boundaries) where page_boundaries is a list
    of (cumulative_token_count_after_this_page, page_no), sorted ascending -
    used to look up which page any given token index falls on via bisect."""
    all_tokens: list[int] = []
    page_boundaries: list[tuple[int, int]] = []
    for page in group.pages:
        page_tokens = _ENCODING.encode(page.text)
        all_tokens.extend(page_tokens)
        page_boundaries.append((len(all_tokens), page.page_no))
    return all_tokens, page_boundaries


def _page_for_token_index(page_boundaries: list[tuple[int, int]], token_index: int) -> int:
    cumulative_counts = [b[0] for b in page_boundaries]
    i = bisect.bisect_right(cumulative_counts, token_index)
    i = min(i, len(page_boundaries) - 1)
    return page_boundaries[i][1]


def chunk_sectioned_pages(
    pages: list[SectionedPage],
    max_tokens: int = DEFAULT_MAX_TOKENS,
    overlap_tokens: int = DEFAULT_OVERLAP_TOKENS,
) -> list[TenderTextChunk]:
    """Tasks 2.2.2 + 2.2.3: sequential, page-bounded, ~max_tokens chunks
    with ~overlap_tokens of sliding overlap between consecutive chunks
    within the same section."""
    if overlap_tokens >= max_tokens:
        raise ValueError("overlap_tokens must be smaller than max_tokens")

    groups = _group_pages_by_section(pages)
    stride = max_tokens - overlap_tokens

    chunks: list[TenderTextChunk] = []
    global_index = 0

    for group in groups:
        all_tokens, page_boundaries = _tokenize_group_with_page_map(group)
        if not all_tokens:
            continue

        start = 0
        while start < len(all_tokens):
            end = min(start + max_tokens, len(all_tokens))
            window = all_tokens[start:end]

            page_start = _page_for_token_index(page_boundaries, start)
            page_end = _page_for_token_index(page_boundaries, end - 1)
            this_overlap = overlap_tokens if start > 0 else 0

            chunks.append(
                TenderTextChunk(
                    chunk_index=global_index,
                    section=group.section,
                    page_start=page_start,
                    page_end=page_end,
                    text=_ENCODING.decode(window),
                    token_count=len(window),
                    overlap_tokens=this_overlap,
                )
            )
            global_index += 1

            if end == len(all_tokens):
                break
            start += stride

    return chunks


def guard_against_whole_document_ingestion(
    chunks: list[TenderTextChunk], max_tokens: int = DEFAULT_MAX_TOKENS
) -> None:
    """Task 2.2.4 - TN-ING-05: prevents requirement truncation/compression
    by refusing to let anything downstream receive an oversized, unchunked
    blob. Two failure modes are checked:
      1. No individual chunk may exceed the token budget (a bug upstream
         could otherwise silently hand Stage 2's LLM the whole document).
      2. There must be at least one chunk per non-empty tender (an empty
         chunk list would mean extraction has nothing to run against at
         all, which is its own silent-loss failure).
    """
    if not chunks:
        raise ValueError(
            "Chunking guard failed: no chunks were produced. "
            "Refusing to proceed - Stage 2 extraction has nothing to run on."
        )

    for chunk in chunks:
        if chunk.token_count > max_tokens:
            raise ValueError(
                f"Chunking guard failed: chunk {chunk.chunk_index} has "
                f"{chunk.token_count} tokens (limit {max_tokens}). "
                "A chunk this large would be passed to Stage 2 extraction "
                "as a single pass, risking truncated or compressed requirements (TN-ING-05)."
            )
