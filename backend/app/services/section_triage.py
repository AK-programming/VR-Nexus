"""Stage A: decide which pages of a tender are worth extracting from.

Why
---
Measured against two analyst-authored trackers, 43.5% of the rows this pipeline
produced for one 125-page RFP came from post-award contract clauses (general and
special conditions, arbitration, force majeure, the client's own payment
obligations) and another 5.1% from table-of-contents lines. Neither analyst
tracker contains a single row from those sections: two analysts, two tenders,
the same exclusion, which makes it a deliberate scope rule rather than an
oversight.

The prompt rewrite in extraction.py teaches the model that rule, so it now
returns an empty list for those chunks. That fixes the output but not the bill:
we still pay to send every page of the contract conditions and read back
"nothing here". On that tender it is ~48% of the document, and since the
per-chunk system prompt is now the dominant input cost, the calls we avoid are
the expensive part.

This module removes those pages before extraction runs, in ONE cheap call.

Classifying by page range, not by section name
----------------------------------------------
The obvious design is to classify the sections the chunker already detects. It
does not work: `chunking.SECTION_PATTERNS` only knows World Bank / ADB
vocabulary (SPN, PDS, "Instructions to Proposers", "Section VII"), so on a
PPRA-style Pakistani RFP almost nothing matches and section labels fall through
to a heading normaliser that produced over 100 distinct names for one document,
including four spellings of a single GCC heading. Filtering on a label that
unreliable would drop real requirements.

Page numbers have no such problem. So Stage A reads a compact outline (one line
per page) and returns page SPANS, and chunks are filtered by page overlap.

Fails open, always
------------------
A tender is a legal document and a silently dropped requirement is the one
failure this pipeline must not have. So every failure path here returns "extract
everything": a classification that errors, times out, comes back malformed,
covers no pages, or would exclude an implausible share of the document is
discarded rather than trusted. The cost of failing open is a normal-priced run.
The cost of failing closed is a tracker that looks complete and is not.

Nothing is hidden either. Excluded spans are recorded on the tender and written
into the workbook's own "Excluded sections" sheet, so a reviewer can see what
was skipped and why, and disagree. That is a stronger audit position than the
old one, where the guarantee was "everything was extracted" and the cost was a
reviewer hunting 57 real rows inside 687.
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from typing import Literal, Optional

from pydantic import BaseModel, field_validator

logger = logging.getLogger(__name__)

#: How a span of pages is treated.
#:   BID_RELEVANT     extract from it
#:   POST_AWARD       real obligations, but they fall due after award: GCC/SCC,
#:                    arbitration, force majeure, payment schedules, appendices
#:   NON_SUBSTANTIVE  tables of contents, indexes, cover pages, eligible-country
#:                    lists, definitions, background narrative
SpanKind = Literal["BID_RELEVANT", "POST_AWARD", "NON_SUBSTANTIVE"]

#: Only the first kind is extracted. POST_AWARD is excluded rather than deleted
#: from the record: a bid team does need to know a 10% performance guarantee is
#: coming, but that belongs in the one row the prompt's "Post-award" mandatory
#: value already covers, not in 299 rows of contract conditions.
EXTRACTED_KINDS = frozenset({"BID_RELEVANT"})

#: Characters of each page used to build the outline. Enough for a heading and
#: the first sentence or two, which is what tells the model whether a page is
#: contract boilerplate or an eligibility list.
OUTLINE_CHARS_PER_PAGE = 180

#: If a classification would exclude more than this share of the document,
#: discard it and extract everything. On the reference tender the honest answer
#: is ~48%, and a plausible range around that is 0-75%; a model returning "90%
#: of this RFP is boilerplate" has misread it, and acting on that would quietly
#: gut the tracker.
MAX_EXCLUDED_FRACTION = 0.75

#: Below this many pages, triage is not worth a call: the saving is small, and a
#: short document is more likely to interleave relevant and boilerplate content
#: on the same page, where page-level exclusion is the wrong tool.
MIN_PAGES_FOR_TRIAGE = 20


class PageSpan(BaseModel):
    page_start: int
    page_end: int
    kind: SpanKind
    label: str = ""

    @field_validator("label")
    @classmethod
    def _trim(cls, value: str) -> str:
        return (value or "").strip()[:120]


class TriageResult(BaseModel):
    spans: list[PageSpan] = []


@dataclass
class TriageOutcome:
    """What triage decided, and whether extraction should act on it."""
    spans: list[PageSpan]
    excluded_pages: set[int]
    applied: bool
    reason: str
    #: Token cost of the triage call itself, so the pipeline can record it as
    #: usage like any other LLM call rather than it being spend nobody sees.
    #: Zero on every path that did not make a call.
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0

    def excludes(self, page_start: Optional[int], page_end: Optional[int]) -> bool:
        """True when every page this chunk covers was excluded.

        Deliberately "every", not "any": a chunk straddling the boundary between
        an evaluation-criteria section and the contract conditions that follow it
        still gets extracted. Paying for one chunk twice is cheaper than losing
        the requirement at the seam.
        """
        if not self.applied or page_start is None or page_end is None:
            return False
        lo, hi = (page_start, page_end) if page_start <= page_end else (page_end, page_start)
        pages = set(range(lo, hi + 1))
        return bool(pages) and pages.issubset(self.excluded_pages)

    def as_json(self) -> dict:
        """Persisted on the tender, and read back by the workbook writer."""
        return {
            "applied": self.applied,
            "reason": self.reason,
            "spans": [s.model_dump() for s in self.spans],
        }


def _outline(pages) -> str:
    """One line per page: its number and opening text, whitespace collapsed.

    A full-text pass would cost as much as the extraction this is meant to
    avoid. The opening of a page is enough signal, because procurement
    documents put their headings there, and the model also sees the whole
    document's shape at once - which is what lets it recognise "pages 30 to 60
    are all contract conditions" rather than judging each page alone.
    """
    lines = []
    for page in pages:
        text = re.sub(r"\s+", " ", (page.text or "")).strip()
        lines.append(f"p{page.number}: {text[:OUTLINE_CHARS_PER_PAGE]}")
    return "\n".join(lines)


_SYSTEM_PROMPT = (
    "You are triaging a procurement tender so that a bid team's requirement "
    "extraction only reads the parts that matter. You are given one line per "
    "page: the page number and how that page opens.\n"
    "\n"
    "Return contiguous page spans covering the document, each classified:\n"
    "  BID_RELEVANT     the bidder must do, submit, sign, prove or decide "
    "something here before the deadline, or it carries evaluation marks or a "
    "pass/fail gate. Procurement notices, instructions to bidders, bid/proposal "
    "data sheets, eligibility criteria, evaluation and qualification criteria, "
    "terms of reference and scope of work, required services, proposal forms, "
    "annexures the bidder fills in, checklists, scoring matrices.\n"
    "  POST_AWARD       binding, but only after the contract is awarded: "
    "general and special conditions of contract, contract agreement and its "
    "appendices, payment schedules, arbitration and dispute resolution, force "
    "majeure, termination, liabilities, indemnities, insurance, governing law, "
    "obligations of the procuring entity.\n"
    "  NON_SUBSTANTIVE table of contents, section indexes, cover and signature "
    "pages, abbreviations and definitions, eligible-country lists, general "
    "policy statements, blank pages, background narrative about the project "
    "that asks the bidder for nothing.\n"
    "\n"
    "Rules:\n"
    "- Prefer FEW, LARGE spans. A tender's contract conditions run for dozens "
    "of consecutive pages; return that as one span, not forty.\n"
    "- Cover every page from 1 to the last. Spans must not overlap and must be "
    "in ascending order.\n"
    "- label: a short name for the span, taken from the document's own heading "
    "where there is one, e.g. \"General Conditions of Contract\".\n"
    "- When a span genuinely mixes both, classify it BID_RELEVANT. Reading a "
    "few extra pages is cheap; missing a submission requirement is not.\n"
    "\n"
    "Return ONLY a single JSON object of the form "
    "{\"spans\": [{\"page_start\": 1, \"page_end\": 12, \"kind\": "
    "\"BID_RELEVANT\", \"label\": \"...\"}]}. No markdown."
)


def _validate(result: TriageResult, page_count: int) -> TriageOutcome:
    """Turn a model response into a decision, refusing to act on a bad one."""
    spans = [
        s for s in result.spans
        if 1 <= s.page_start <= s.page_end <= page_count
    ]
    if not spans:
        return TriageOutcome([], set(), False, "Triage returned no usable spans; extracted everything.")

    spans.sort(key=lambda s: s.page_start)
    excluded: set[int] = set()
    for span in spans:
        if span.kind not in EXTRACTED_KINDS:
            excluded.update(range(span.page_start, span.page_end + 1))

    fraction = len(excluded) / page_count if page_count else 0.0
    if fraction > MAX_EXCLUDED_FRACTION:
        return TriageOutcome(
            spans, set(), False,
            f"Triage wanted to exclude {fraction:.0%} of the document, above the "
            f"{MAX_EXCLUDED_FRACTION:.0%} ceiling; extracted everything instead.",
        )
    if not excluded:
        return TriageOutcome(spans, set(), False, "Triage found nothing to exclude.")

    return TriageOutcome(
        spans, excluded, True,
        f"Excluded {len(excluded)} of {page_count} pages ({fraction:.0%}) as post-award "
        f"or non-substantive.",
    )


async def triage_pages(pages, model: dict[str, str]) -> TriageOutcome:
    """Classify a tender's pages. Never raises."""
    page_count = len(pages)
    if page_count < MIN_PAGES_FOR_TRIAGE:
        return TriageOutcome(
            [], set(), False,
            f"Document is {page_count} pages, below the {MIN_PAGES_FOR_TRIAGE}-page triage "
            "threshold; extracted everything.",
        )

    from app.services.extraction import _coerce_json, _get_client

    started = time.monotonic()
    try:
        client = _get_client(model["provider"])
        response = await client.chat.completions.create(
            model=model["model"],
            max_tokens=4096,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f"The tender has {page_count} pages.\n\n{_outline(pages)}",
                },
            ],
        )
        latency_ms = int((time.monotonic() - started) * 1000)
        raw = (response.choices[0].message.content or "").strip()
        parsed = TriageResult.model_validate_json(_coerce_json(raw))
        usage = response.usage

        outcome = _validate(parsed, page_count)
        outcome.input_tokens = getattr(usage, "prompt_tokens", 0) or 0
        outcome.output_tokens = getattr(usage, "completion_tokens", 0) or 0
        outcome.latency_ms = latency_ms
        logger.info(
            "Section triage: %s (%s in / %s out tokens, %sms)",
            outcome.reason, outcome.input_tokens, outcome.output_tokens, latency_ms,
        )
        return outcome
    except Exception as exc:
        # The most common way this fired in practice was not the model itself
        # but _coerce_json's parsing of it: the triage prompt is answered with
        # one JSON object, and a response that starts clean but trails a
        # sentence after the closing brace used to fail
        # `model_validate_json` with "Invalid JSON: trailing characters" here
        # exactly as it did for a chunk's own extraction JSON (see
        # extraction.py's `_coerce_json`) - same shared parser, same bug,
        # different caller. That parser now always takes the widest {...}
        # span rather than only doing so when the text didn't already start
        # with "{", so this branch should be rare going forward. Naming the
        # actual exception here (rather than a generic "failed") is what
        # would have made that diagnosable without a database read the first
        # time it happened - see extraction.py's `_summarise_errors` for the
        # same reasoning applied to a chunk's own extraction failures.
        detail = f"{type(exc).__name__}: {exc}"[:200]
        logger.exception("Section triage failed; extracting the whole document.")
        return TriageOutcome(
            [], set(), False, f"Triage call failed ({detail}); extracted everything.",
            latency_ms=int((time.monotonic() - started) * 1000),
        )


def load_outcome(stored: Optional[dict]) -> TriageOutcome:
    """Rebuild an outcome from the JSON persisted on the tender.

    Tolerant by design: a tender analysed before triage existed, or one whose
    stored blob is malformed, reads back as "not applied", which is the same
    thing as never having run.
    """
    if not isinstance(stored, dict) or not stored.get("applied"):
        spans = []
        if isinstance(stored, dict):
            for raw in stored.get("spans") or []:
                try:
                    spans.append(PageSpan.model_validate(raw))
                except Exception:
                    continue
        reason = (stored or {}).get("reason", "") if isinstance(stored, dict) else ""
        return TriageOutcome(spans, set(), False, reason)

    spans = []
    for raw in stored.get("spans") or []:
        try:
            spans.append(PageSpan.model_validate(raw))
        except Exception:
            continue
    excluded: set[int] = set()
    for span in spans:
        if span.kind not in EXTRACTED_KINDS:
            excluded.update(range(span.page_start, span.page_end + 1))
    return TriageOutcome(spans, excluded, True, stored.get("reason", ""))
