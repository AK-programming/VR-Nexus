"""Grounded answer generation over the evidence library — the G in RAG.

Retrieval (`services/library/search.py`) is Section 6's actual deliverable: it
returns the chunks, and Stage 3 requirement matching is the section that turns
chunks into prose. This module is the thin generation layer on top, so the
library can be demonstrated end to end without waiting for Stage 3.

The design rule here is that the model is never the source of facts. It sees
only the retrieved chunks and is told to answer from them alone; anything it
cannot support from that context it must decline. That is what separates a RAG
answer from a plausible-sounding guess, and it is why every answer carries the
sources it was built from — a reader can check the claim against the page.
"""
from __future__ import annotations

import logging
import re

from sqlalchemy.orm import Session

from app.models.enums import DocumentCategory
from app.schemas.library import AnswerOut, SearchHit
from app.services.library import llm, search

logger = logging.getLogger(__name__)

# How many chunks to put in front of the model. Enough to cover a question that
# spans two sections, small enough that the relevant passage is not buried.
DEFAULT_CONTEXT_CHUNKS = 6

# Hard cap on context size. A methodology chunk can run long, and six of them
# plus a verbose question should not silently blow the request limit.
MAX_CONTEXT_CHARS = 24000

# Chunks below this cosine similarity are dropped before the model sees them.
# Vector search always returns its top-k, even when nothing in the library is
# relevant; without a floor, an unrelated question gets handed unrelated text
# and the model is left to make sense of it.
MIN_CONTEXT_SIMILARITY = 0.25

# The exact string the model is told to emit when the context does not answer
# the question. Checked for below to set `grounded`, so it must match verbatim.
NO_ANSWER = "The library does not contain an answer to this question."

SYSTEM_PROMPT = f"""You answer questions about a consulting firm's evidence \
library: case studies, methodology documents and company documents.

You will be given numbered excerpts from that library, then a question.

Rules:
- Answer using ONLY the excerpts. They are your only source of facts.
- Cite every claim with the excerpt number in square brackets, like [1] or [2].
- If the excerpts do not answer the question, reply with exactly:
  {NO_ANSWER}
  Do not guess, and do not fall back on general knowledge.
- If the excerpts only partly answer it, give what they support and say plainly \
what is missing.
- Be concise and factual. No preamble, no restating the question.
"""


def _format_context(hits: list[SearchHit]) -> tuple[str, int]:
    """Render the retrieved chunks as numbered excerpts.

    Returns the rendered context and how many excerpts it actually contains. The
    count is returned rather than recovered from the string because chunk text
    contains blank lines of its own, so counting separators would overcount and
    leave the caller thinking the model saw excerpts it never did.

    The number is the citation handle: it is what the model writes in [n] and
    what `_cited_indexes` reads back out, so the ordering here and the ordering
    of `sources` in the response have to stay in lockstep.
    """
    blocks: list[str] = []
    used = 0

    for position, hit in enumerate(hits, start=1):
        where = " · ".join(
            part
            for part in (
                hit.title or hit.original_filename,
                hit.section_name,
                f"page {hit.page_number}" if hit.page_number else "",
            )
            if part
        )
        block = f"[{position}] {where}\n{hit.content}"

        # Truncate on a chunk boundary rather than mid-sentence: half a chunk
        # can strand a claim from the qualifier that limits it.
        if blocks and used + len(block) > MAX_CONTEXT_CHARS:
            break
        blocks.append(block)
        used += len(block)

    return "\n\n".join(blocks), len(blocks)


def _cited_indexes(answer: str, count: int) -> set[int]:
    """Which excerpt numbers the answer actually cited.

    Used to mark sources as cited rather than to filter them: a source that was
    retrieved but not cited is still worth showing, because it tells a reviewer
    what the model considered and passed over.
    """
    found = set()
    for match in re.findall(r"\[(\d+(?:\s*,\s*\d+)*)\]", answer):
        for part in match.split(","):
            index = int(part.strip())
            if 1 <= index <= count:
                found.add(index)
    return found


def answer(
    db: Session,
    question: str,
    category: DocumentCategory | None = None,
    limit: int = DEFAULT_CONTEXT_CHUNKS,
    min_similarity: float = MIN_CONTEXT_SIMILARITY,
) -> AnswerOut:
    """Retrieve, then generate a grounded answer with citations.

    Returns an AnswerOut in every case, including when the library has nothing
    relevant or the model call fails. Callers get one shape to render; the
    `grounded` flag says whether the text is backed by retrieved evidence.
    """
    question = (question or "").strip()
    if not question:
        return AnswerOut(question=question, answer=NO_ANSWER, grounded=False, sources=[])

    hits = search.search(
        db, question, category=category, limit=limit, min_similarity=min_similarity
    )

    # Nothing cleared the relevance floor. Say so directly instead of asking the
    # model to narrate an empty context back to the user.
    if not hits:
        return AnswerOut(question=question, answer=NO_ANSWER, grounded=False, sources=[])

    context, shown = _format_context(hits)
    # _format_context may drop trailing hits to stay under the size cap; only
    # the excerpts the model actually saw may be cited back.
    hits = hits[:shown]

    generated = llm.complete(
        f"Excerpts from the evidence library:\n\n{context}\n\n"
        f"Question: {question}",
        system=SYSTEM_PROMPT,
        max_tokens=1500,
    )

    # llm.complete() returns "" on any failure — no key, rate limit, network.
    # The retrieval still succeeded, so hand back the sources and let the client
    # show them; a list of relevant passages is a useful answer on its own.
    if not generated:
        logger.warning("Generation unavailable; returning retrieval-only response")
        return AnswerOut(
            question=question,
            answer=(
                "Answer generation is unavailable right now. "
                "The most relevant passages from the library are listed below."
            ),
            grounded=False,
            sources=hits,
        )

    cited = _cited_indexes(generated, len(hits))
    declined = generated.strip().rstrip(".").lower() == NO_ANSWER.rstrip(".").lower()

    for position, hit in enumerate(hits, start=1):
        hit.cited = position in cited

    return AnswerOut(
        question=question,
        answer=generated,
        # Grounded means: the model produced an answer and pointed at evidence
        # for it. An uncited answer is exactly the failure mode this endpoint
        # exists to make visible, so it is reported rather than hidden.
        grounded=bool(cited) and not declined,
        sources=hits,
    )
