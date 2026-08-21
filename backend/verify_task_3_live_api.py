"""
Makes exactly ONE real call to the Anthropic API using the real
extraction.extract_chunk() function, against a small hand-written chunk
of tender-like text. Doesn't touch Postgres or Redis, doesn't need a
running server - just confirms your ANTHROPIC_API_KEY works and that the
real model actually returns marks/evaluation_impact in a shape
extraction.py can parse (Task 3.1.1/3.1.2).

This costs one real API call (a few cents at most). Run this before
uploading a real tender through the full pipeline, so if something's
wrong (bad key, model name, parsing) you find out in 5 seconds instead
of after a 500-page PDF has been chunked.

Usage (from the backend/ folder, with the venv active):
    python verify_task_3_live_api.py
"""
import asyncio
import sys

from app.models.tender_chunk import TenderChunk
from app.services import extraction

SAMPLE_TENDER_TEXT = """
Section VII - Technical Requirements

7.1 The Bidder shall submit a technical proposal describing their
    implementation methodology, staffing plan, and quality assurance
    approach. This requirement is mandatory and carries 15 marks under
    the Technical evaluation category.

7.2 The Bidder shall provide evidence of at least three (3) similar
    projects completed in the last five years, including client
    references and project outcomes. This requirement is mandatory,
    carries 10 marks under the Technical evaluation category, and
    requires a supporting case study document as evidence.
"""


async def main() -> int:
    print("=== Live Anthropic API check (Task 3.1.1 / 3.1.2) ===\n")
    print("Calling the real API with one sample chunk (this costs a real API call)...\n")

    # Not saved to the DB - extract_chunk only reads its in-memory fields.
    fake_chunk = TenderChunk(
        chunk_index=0,
        section="Technical Requirements",
        page_start=7,
        page_end=7,
        content=SAMPLE_TENDER_TEXT,
        token_count=len(SAMPLE_TENDER_TEXT.split()),
        overlap_tokens=0,
    )

    result = await extraction.extract_chunk(fake_chunk, index=1, total=1)

    if result["status"] != "success":
        print("FAIL: the real API call did not succeed after "
              f"{extraction.MAX_EXTRACTION_RETRIES} retries.")
        print("Check: is ANTHROPIC_API_KEY in your .env valid? Any network/proxy issues?")
        return 1

    reqs = result["data"]
    print(f"OK: got {len(reqs)} requirement(s) back from the real model.\n")

    for i, req in enumerate(reqs, start=1):
        marks = extraction._parse_marks(req.marks)
        impact = extraction._parse_evaluation_impact(req.evaluation_impact)
        print(f"--- Requirement {i} ---")
        print(f"  reference_number:   {req.reference_number}")
        print(f"  description:        {req.clause_requirement_description}")
        print(f"  mandatory (raw):    {req.mandatory!r}")
        print(f"  evaluation_impact:  raw={req.evaluation_impact!r} -> parsed={impact}")
        print(f"  marks:              raw={req.marks!r} -> parsed={marks}")
        print(f"  evidence_required:  {req.evidence_document_required!r}\n")

        if impact is None:
            print(f"  WARNING: evaluation_impact {req.evaluation_impact!r} didn't parse to a known "
                  "EvaluationImpact enum value (pass_fail/technical/financial/compliance).")
        if marks is None:
            print(f"  WARNING: marks {req.marks!r} didn't parse to a number.")

    print("Live API check complete. If evaluation_impact/marks parsed correctly above, "
          "3.1.1/3.1.2 are confirmed working against the real model - now safe to run a "
          "real tender through the full /api/tenders/upload pipeline.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
