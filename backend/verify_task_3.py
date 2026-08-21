"""
Run this AFTER `alembic upgrade head` (Postgres must be running) to
confirm Task 3 (Requirement & Scoring Extraction Module, Stage 2) works
end-to-end, sub-task by sub-task:

  3.1.1  Chunk extraction prompt + strict JSON schema
  3.1.2  Field extraction (incl. marks + evaluation_impact persistence)
  3.1.3  Retry logic + manual-review flagging
  3.2.1  Append chunk outputs to running master table
  3.2.2  Merge & deduplicate overlapping requirements
  3.3.1  Running tally vs. evaluation weighting scheme
  3.3.2  100% coverage verification

The real Anthropic API is never called - `extraction._client.messages.create`
is monkeypatched with a fake that returns canned, deterministic JSON per
chunk (one requirement, one duplicate-across-chunks, one that always
raises to exercise the retry+manual-review path), so this is fast, free,
and doesn't need ANTHROPIC_API_KEY to be a real working key. It then runs
the real run_extraction() and run_scoring() against real TenderChunk /
Requirement / Tender rows. Everything it creates is deleted at the end.

Usage (from the backend/ folder, with the venv active):
    python verify_task_3.py
"""
import asyncio
import json
import sys
from unittest.mock import AsyncMock, patch

from sqlalchemy import inspect

from app.core.database import SessionLocal, engine
from app.models import Tender, TenderChunk, User
from app.models.enums import EvaluationImpact, RequirementStatus, UserRole
from app.models.requirement import Requirement
from app.services import extraction, scoring

EXPECTED_REQUIREMENT_COLUMNS = {"marks", "evaluation_impact", "needs_manual_review", "status"}
EXPECTED_TENDER_COLUMNS = {"evaluation_weighting", "total_marks_available", "total_marks_captured"}

CHUNK_A_MARKER = "CHUNK_A_MARKER"  # normal chunk -> one technical requirement
CHUNK_B_MARKER = "CHUNK_B_MARKER"  # Evaluation Criteria chunk -> weighting phrase + one financial requirement
CHUNK_C_MARKER = "CHUNK_C_MARKER"  # duplicate of chunk A's requirement (overlap dedup, 3.2.2)
CHUNK_D_MARKER = "CHUNK_D_MARKER"  # always fails -> retry + manual review (3.1.3)


def _requirement_payload(reference: str, description: str, marks, impact: str) -> str:
    return json.dumps({
        "requirements": [{
            "page": "12",
            "section_name": "Technical Requirements",
            "responsibility": "Bidder",
            "reference_number": reference,
            "clause_requirement_description": description,
            "mandatory": "Yes",
            "evaluation_impact": impact,
            "marks": str(marks),
            "dpl": "N/A",
            "prime": "N/A",
            "the_t": "N/A",
            "joint_responsibility": "N/A",
            "evidence_document_required": "N/A",
            "remarks": "",
        }]
    })


class _FakeTextBlock:
    def __init__(self, text: str):
        self.text = text


class _FakeResponse:
    def __init__(self, text: str):
        self.content = [_FakeTextBlock(text)]


async def _fake_create(**kwargs):
    content = kwargs["messages"][0]["content"]
    if CHUNK_A_MARKER in content:
        return _FakeResponse(_requirement_payload("TR-1", "Provide technical proposal narrative", 40, "technical"))
    if CHUNK_B_MARKER in content:
        return _FakeResponse(_requirement_payload("TR-2", "Financial proposal shall detail costs", 25, "financial"))
    if CHUNK_C_MARKER in content:
        # Same reference + description as chunk A -> must be deduped, and
        # its inflated marks (999) must NOT reach the tally.
        return _FakeResponse(_requirement_payload("TR-1", "Provide technical proposal narrative", 999, "technical"))
    if CHUNK_D_MARKER in content:
        raise RuntimeError("simulated model/parse failure")
    raise AssertionError(f"unexpected fake chunk content: {content[:80]!r}")


def main() -> int:
    print("=== Task 3 (3.1.1 / 3.1.2 / 3.1.3 / 3.2.1 / 3.2.2 / 3.3.1 / 3.3.2) verification ===\n")

    # --- 0. Schema check ---
    print("[0/5] Checking database schema...")
    inspector = inspect(engine)
    req_columns = {c["name"] for c in inspector.get_columns("requirements")}
    missing_req = EXPECTED_REQUIREMENT_COLUMNS - req_columns
    if missing_req:
        print(f"  FAIL: requirements table is missing columns {missing_req}. Run `alembic upgrade head`.")
        return 1
    tender_columns = {c["name"] for c in inspector.get_columns("tenders")}
    missing_tender = EXPECTED_TENDER_COLUMNS - tender_columns
    if missing_tender:
        print(f"  FAIL: tenders table is missing columns {missing_tender}. Run `alembic upgrade head`.")
        return 1
    print("  OK: requirements + tenders have all the columns Task 3 needs.\n")

    db = SessionLocal()
    user = None
    tender = None

    try:
        # --- 1. Fixtures: a user, a tender, and 4 TenderChunks ---
        print("[1/5] Seeding a Tender with 4 TenderChunks (technical, evaluation-criteria, "
              "a cross-chunk duplicate, and one designed to fail)...")
        user = User(
            name="Verify Task 3",
            email="verify-task3@example.com",
            password_hash="not-a-real-hash",
            role=UserRole.USER,
        )
        db.add(user)
        db.flush()

        tender = Tender(
            name="verify_task_3 test tender",
            original_filename="verify_task_3.pdf",
            file_path="/storage/tenders/verify_task_3.pdf",
            uploaded_by=user.id,
        )
        db.add(tender)
        db.flush()

        chunk_specs = [
            (0, "Technical Requirements", 10, 10, CHUNK_A_MARKER + " Bidders must submit a technical narrative. " * 10),
            (1, "Evaluation Criteria", 11, 11,
             CHUNK_B_MARKER + " The bid will be evaluated as follows: 60% Technical, 40% Financial. " * 10),
            (2, "Technical Requirements", 10, 11,  # overlap page range, like a real sliding-window chunk
             CHUNK_C_MARKER + " Bidders must submit a technical narrative (repeated across the page overlap). " * 10),
            (3, "Annexes", 25, 25, CHUNK_D_MARKER + " Illegible / malformed annex content. " * 10),
        ]
        for idx, section, start, end, content in chunk_specs:
            db.add(TenderChunk(
                tender_id=tender.id,
                chunk_index=idx,
                section=section,
                page_start=start,
                page_end=end,
                content=content,
                token_count=len(content.split()),
                overlap_tokens=0,
            ))
        db.commit()
        print("  OK: 4 TenderChunk rows created.\n")

        # --- 2. Run the real extraction pipeline against the fake Anthropic client ---
        print("[2/5] Running run_extraction() (3.1.1) against a mocked Claude response per chunk...")
        
        fake_create = AsyncMock(side_effect=_fake_create)
        with patch.object(extraction._client.messages, "create", new=fake_create), \
             patch("app.services.extraction.asyncio.sleep", new=AsyncMock()):
            db.refresh(tender)
            result = asyncio.run(extraction.run_extraction(db, tender))

        assert result["created"] == 2, f"expected 2 unique requirements created, got {result['created']}"
        assert result["failed_chunks"] == 1, f"expected 1 failed chunk, got {result['failed_chunks']}"
        print(f"  OK: 3.1.1 ran a real per-chunk extraction loop -> "
              f"{result['created']} unique requirement(s), {result['failed_chunks']} failed chunk(s).\n")

        # --- 3. 3.1.2 / 3.2.1 / 3.2.2 - verify what actually landed in the DB ---
        print("[3/5] Checking 3.1.2 (field persistence) + 3.2.1/3.2.2 (master table + dedup)...")
        stored = (
            db.query(Requirement)
            .filter(Requirement.tender_id == tender.id)
            .order_by(Requirement.clause_reference)
            .all()
        )
        assert len(stored) == 3, f"expected 3 total rows (2 requirements + 1 manual-review placeholder), got {len(stored)}"

        by_ref = {r.clause_reference: r for r in stored if r.clause_reference}
        assert "TR-1" in by_ref and "TR-2" in by_ref, f"expected TR-1 and TR-2, got {list(by_ref)}"
        assert len(by_ref) == 2, "chunk C's duplicate of TR-1 should have been deduped, not stored as a 3rd row"

        tr1 = by_ref["TR-1"]
        assert tr1.marks is not None and abs(float(tr1.marks) - 40.0) < 0.01, f"TR-1 marks should be 40, got {tr1.marks}"
        assert tr1.evaluation_impact == EvaluationImpact.TECHNICAL, f"TR-1 impact should be TECHNICAL, got {tr1.evaluation_impact}"

        tr2 = by_ref["TR-2"]
        assert tr2.marks is not None and abs(float(tr2.marks) - 25.0) < 0.01, f"TR-2 marks should be 25, got {tr2.marks}"
        assert tr2.evaluation_impact == EvaluationImpact.FINANCIAL, f"TR-2 impact should be FINANCIAL, got {tr2.evaluation_impact}"
        print("  OK: 3.1.2 marks + evaluation_impact persisted correctly on both requirement rows.")
        print("  OK: 3.2.1 both chunks' outputs landed in the master requirements table.")
        print("  OK: 3.2.2 chunk C's duplicate (same reference+description, inflated marks=999) was "
              "correctly deduped and never stored.\n")

        # --- 4. 3.1.3 - the failed chunk produced a manual-review placeholder, not silence ---
        print("[4/5] Checking 3.1.3 (retry logic + manual-review flagging)...")
        review_rows = [r for r in stored if r.needs_manual_review]
        assert len(review_rows) == 1, f"expected exactly 1 manual-review row, got {len(review_rows)}"
        review_row = review_rows[0]
        assert review_row.status == RequirementStatus.NEEDS_MANUAL_REVIEW
        assert review_row.section_name == "Annexes"
        assert fake_create.await_count >= 3 * 1 + 3, (
            "expected at least 3 retry attempts recorded for the failing chunk"
        )
        print(f"  OK: chunk D retried {extraction.MAX_EXTRACTION_RETRIES}x then produced a "
              f"NEEDS_MANUAL_REVIEW placeholder row (page {review_row.page_number}, "
              f"section={review_row.section_name!r}) instead of silently vanishing.\n")

        # --- 5. 3.3.1 / 3.3.2 - scoring & coverage tracking ---
        print("[5/5] Running run_scoring() (3.3.1 weighting detection + tally, 3.3.2 coverage)...")
        db.refresh(tender)
        scoring_result = scoring.run_scoring(db, tender)

        assert scoring_result["evaluation_weighting"] == {"technical": 60.0, "financial": 40.0}, (
            f"expected weighting detected from the Evaluation Criteria chunk, got "
            f"{scoring_result['evaluation_weighting']}"
        )
        assert abs(scoring_result["total_marks_captured"] - 65.0) < 0.01, (
            f"expected captured=65 (40 technical + 25 financial), got {scoring_result['total_marks_captured']}"
        )
        assert abs(scoring_result["total_marks_available"] - 100.0) < 0.01, (
            f"expected available=100 (60 + 40 from the weighting scheme), got {scoring_result['total_marks_available']}"
        )
        assert scoring_result["coverage_percent"] == 65.0, f"expected 65.0% coverage, got {scoring_result['coverage_percent']}"
        assert scoring_result["fully_reconciled"] is False, "65/100 should not be reported as fully reconciled"
        assert set(scoring_result["missing_categories"]) == {"technical", "financial"}, (
            f"both categories are short of their weighting, got {scoring_result['missing_categories']}"
        )
        assert scoring_result["manual_review_count"] == 1

        db.refresh(tender)
        assert tender.evaluation_weighting == {"technical": 60.0, "financial": 40.0}
        assert abs(float(tender.total_marks_captured) - 65.0) < 0.01
        assert abs(float(tender.total_marks_available) - 100.0) < 0.01
        print(f"  OK: 3.3.1 auto-detected weighting {scoring_result['evaluation_weighting']} from the "
              f"Evaluation Criteria chunk and tallied captured marks by category "
              f"({scoring_result['tally']}).")
        print(f"  OK: 3.3.2 reconciled to {scoring_result['coverage_percent']}% coverage "
              f"(fully_reconciled={scoring_result['fully_reconciled']}, "
              f"missing={scoring_result['missing_categories']}), written back onto the Tender row.\n")

        print("Task 3 (3.1.1 / 3.1.2 / 3.1.3 / 3.2.1 / 3.2.2 / 3.3.1 / 3.3.2) verified successfully.")
        return 0

    except AssertionError as exc:
        print(f"\nFAIL: {exc}")
        return 1
    finally:
        db.rollback()
        if tender is not None:
            db.query(Requirement).filter(Requirement.tender_id == tender.id).delete()
            db.query(TenderChunk).filter(TenderChunk.tender_id == tender.id).delete()
            db.query(Tender).filter(Tender.id == tender.id).delete()
        if user is not None:
            db.query(User).filter(User.id == user.id).delete()
        db.commit()
        db.close()
        print("[cleanup] All test data removed.")


if __name__ == "__main__":
    sys.exit(main())


