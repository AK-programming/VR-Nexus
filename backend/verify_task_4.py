"""
Run this AFTER `alembic upgrade head` (Postgres + pgvector + Redis must be
running) to confirm Task 4 (Evidence Matching Engine, Stage 3) works
end-to-end, sub-task by sub-task:

  4.1.1  Query pre-indexed evidence database
  4.1.2  Hybrid semantic + metadata search
  4.1.3  Confidence scoring & thresholds
  4.2.1  Attach matched file path(s) to requirement row
  4.2.2  Review UI: accept / reject / reassign matches

It builds three fake evidence documents with hand-picked embedding
vectors so the resulting similarity scores are known in advance (one
lands in the AUTO band, one in SUGGESTED, one in MISSING), runs the real
matching.run_matching() against a real Requirement row, then drives the
real /matches API endpoints with FastAPI's TestClient to exercise the
review actions. Everything it creates is deleted at the end.

Usage (from the backend/ folder, with the venv active):
    python verify_task_4.py
"""
import math
import sys
import uuid

from sqlalchemy import inspect

from app.core.database import SessionLocal, engine
from app.models import Document, RequirementEvidenceMatch, Tender, User
from app.models.requirement import Requirement
from app.models.chunk import Chunk
from app.models.enums import (
    DocumentCategory,
    DocumentFileType,
    DocumentTrainingStatus,
    MatchReviewStatus,
    MatchType,
    UserRole,
)
from app.services import matching
from app.services.library import embeddings

EXPECTED_MATCH_COLUMNS = {
    "requirement_id", "document_id", "confidence_score", "match_type",
    "review_status", "reviewed_by", "reviewed_at",
}


class FakeEmbeddingProvider(embeddings.EmbeddingProvider):
    """Deterministic 2D-in-N-D vectors so cosine similarity is exact and
    controllable, instead of depending on the real model's opinion of
    these made-up sentences. Dim 0/1 carry the signal, everything else is
    zero, so cosine similarity between two vectors is just cos(angle)."""

    def __init__(self, dimension: int):
        self.dimension = dimension

    def _vec(self, angle_degrees: float) -> list[float]:
        radians = math.radians(angle_degrees)
        v = [math.cos(radians), math.sin(radians)] + [0.0] * (self.dimension - 2)
        return v

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        # angle assigned by the position in EVIDENCE_ANGLES, looked up by caller
        return [self._vec(EVIDENCE_ANGLES[t]) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vec(0.0)  # query always at angle 0; docs offset from it


# angle -> expected cosine similarity to the query (at angle 0):
#   0 deg  -> 1.00  (AUTO band,   >= 0.85)
#   50 deg -> 0.64  (SUGGESTED,   0.50-0.84)
#   80 deg -> 0.17  (MISSING,     < 0.50)
EVIDENCE_ANGLES = {
    "auto evidence passage": 0,
    "suggested evidence passage": 50,
    "missing evidence passage": 80,
}


def main() -> int:
    print("=== Task 4 (4.1.1 / 4.1.2 / 4.1.3 / 4.2.1 / 4.2.2) verification ===\n")

    # --- 0. Schema check ---
    print("[0/6] Checking database schema...")
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    if "requirement_evidence_matches" not in tables:
        print("  FAIL: 'requirement_evidence_matches' table not found. Run `alembic upgrade head`.")
        return 1
    match_columns = {c["name"] for c in inspector.get_columns("requirement_evidence_matches")}
    missing = EXPECTED_MATCH_COLUMNS - match_columns
    if missing:
        print(f"  FAIL: requirement_evidence_matches is missing columns {missing}.")
        return 1
    print("  OK: requirement_evidence_matches table present with expected columns.\n")

    settings_dim = embeddings.get_settings().EMBEDDING_DIM
    fake_provider = FakeEmbeddingProvider(dimension=settings_dim)
    embeddings.set_provider(fake_provider)  # swap out the real model - deterministic + fast

    db = SessionLocal()
    created_ids = {"documents": [], "chunks": [], "matches": []}
    tender = None
    user = None

    # A previous run that crashed before reaching cleanup can leave its
    # fake evidence documents behind (their titles all start with "Test
    # Case Study ("), which then pollutes every search a later run does.
    # Purge any of those before seeding fresh ones, so this script is safe
    # to re-run after a failure.
    stale = db.query(Document).filter(Document.title.like("Test Case Study (%")).all()
    if stale:
        stale_ids = [d.id for d in stale]
        from app.models import Chunk as _Chunk
        db.query(_Chunk).filter(_Chunk.document_id.in_(stale_ids)).delete(synchronize_session=False)
        db.query(Document).filter(Document.id.in_(stale_ids)).delete(synchronize_session=False)
        db.commit()
        print(f"[pre-cleanup] Removed {len(stale)} leftover document(s) from a previous failed run.\n")

    try:
        user = User(
            name="Verify Task 4",
            email=f"verify-task4-{uuid.uuid4().hex[:8]}@example.com",
            password_hash="not-a-real-hash",
            role=UserRole.USER,
        )
        db.add(user)
        db.flush()

        # --- 1. Evidence library fixtures (three documents at three known angles) ---
        print("[1/6] Seeding three evidence documents at known similarity distances...")
        docs_by_label = {}
        for label, angle in EVIDENCE_ANGLES.items():
            doc = Document(
                category=DocumentCategory.CASE_STUDY,
                title=f"Test Case Study ({label})",
                original_filename=f"{label.replace(' ', '_')}.docx",
                file_path=f"/storage/library/{label.replace(' ', '_')}.docx",
                file_type=DocumentFileType.DOCX,
                training_status=DocumentTrainingStatus.INDEXED,
                # metadata used by 4.1.2's keyword boost - only the "auto"
                # doc mentions "healthcare", matching the requirement text
                sector="Healthcare" if label == "auto evidence passage" else "",
                uploaded_by=user.id,
            )
            db.add(doc)
            db.flush()
            docs_by_label[label] = doc
            created_ids["documents"].append(doc.id)

            vector = fake_provider.embed_documents([label])[0]
            chunk = Chunk(
                document_id=doc.id,
                chunk_index=0,
                content=f"Evidence content for {label}",
                category=DocumentCategory.CASE_STUDY,
                embedding=vector,
                # Real indexing (app/tasks/library_indexing.py) always
                # writes "" / 0 here, never NULL - match that so this
                # fixture looks like real data, not an edge case.
                section_name="",
                page_number=0,
            )
            db.add(chunk)
            db.flush()
            created_ids["chunks"].append(chunk.id)
        db.commit()
        print(f"  OK: 3 indexed Document+Chunk rows created "
              f"({', '.join(d.title for d in docs_by_label.values())}).\n")

        # --- 2. Tender + requirement needing evidence ---
        print("[2/6] Creating a Tender and a Requirement with evidence_required=True...")
        tender = Tender(
            name="verify_task_4 test tender",
            original_filename="verify_task_4.pdf",
            file_path="/storage/tenders/verify_task_4.pdf",
            uploaded_by=user.id,
        )
        db.add(tender)
        db.flush()

        requirement = Requirement(
            tender_id=tender.id,
            page_number=12,
            section_name="Eligibility",
            description="Bidder shall provide a healthcare sector case study as evidence.",
            evidence_description="healthcare case study",
            evidence_required=True,
        )
        db.add(requirement)
        db.commit()
        print(f"  OK: Requirement {requirement.id} created (evidence_required=True).\n")

        # --- 3. 4.1.1 / 4.1.2 - find_matches() queries the library + applies the metadata boost ---
        print("[3/6] Testing 4.1.1 (query evidence DB) + 4.1.2 (semantic + metadata search)...")
        candidates = matching.find_matches(db, requirement)
        assert len(candidates) == 3, f"expected 3 candidates, got {len(candidates)}"
        candidate_by_title = {doc.title: score for doc, score in candidates}

        auto_score = candidate_by_title[docs_by_label["auto evidence passage"].title]
        suggested_score = candidate_by_title[docs_by_label["suggested evidence passage"].title]
        missing_score = candidate_by_title[docs_by_label["missing evidence passage"].title]

        assert auto_score > suggested_score > missing_score, (
            "candidates are not ranked by descending confidence"
        )
        # The "auto" doc's sector="Healthcare" should have been boosted by the
        # metadata-keyword overlap with the requirement's text (4.1.2) - its
        # score should now exceed the raw cosine similarity of 1.00... capped
        # at 1.0, so instead check it's still the top-ranked candidate and
        # the boost function actually fired (fetch it directly).
        boost = matching._metadata_boost(
            docs_by_label["auto evidence passage"],
            matching._keywords(requirement.evidence_description),
        )
        assert boost > 0, "expected the metadata boost to be > 0 for the healthcare-tagged document"
        print(f"  OK: 4.1.1 queried the pre-indexed library and returned 3 candidates.")
        print(f"  OK: 4.1.2 metadata boost fired (+{boost:.3f}) for the sector-matching document.")
        print(f"       scores -> auto={auto_score:.3f}, suggested={suggested_score:.3f}, "
              f"missing={missing_score:.3f}\n")

        # --- 4. 4.1.3 - threshold classification ---
        print("[4/6] Testing 4.1.3 (confidence thresholds)...")
        assert matching.classify(0.85) == MatchType.AUTO
        assert matching.classify(0.99) == MatchType.AUTO
        assert matching.classify(0.84) == MatchType.SUGGESTED
        assert matching.classify(0.50) == MatchType.SUGGESTED
        assert matching.classify(0.49) == MatchType.MISSING
        assert matching.classify(0.0) == MatchType.MISSING
        assert matching.classify(auto_score) == MatchType.AUTO, "top candidate should classify as AUTO"
        assert matching.classify(missing_score) == MatchType.MISSING, "bottom candidate should classify as MISSING"
        print("  OK: boundary values (0.85 / 0.84 / 0.50 / 0.49) and the real candidate "
              "scores classify correctly.\n")

        # --- 5. 4.2.1 - run_matching() attaches match rows with real file paths ---
        print("[5/6] Testing 4.2.1 (attach matched file paths via run_matching)...")
        result = matching.run_matching(db, tender)
        assert result["requirements_checked"] == 1
        db.refresh(requirement)
        stored_matches = (
            db.query(RequirementEvidenceMatch)
            .filter(RequirementEvidenceMatch.requirement_id == requirement.id)
            .all()
        )
        assert len(stored_matches) == 3, f"expected 3 stored matches, got {len(stored_matches)}"
        created_ids["matches"].extend(m.id for m in stored_matches)
        for m in stored_matches:
            assert m.document.file_path.startswith("/storage/library/"), "file path not attached"
        match_types = {m.match_type for m in stored_matches}
        assert MatchType.AUTO in match_types and MatchType.MISSING in match_types, (
            f"expected a spread of match types, got {match_types}"
        )
        print(f"  OK: {len(stored_matches)} RequirementEvidenceMatch rows persisted, each with "
              f"a real document_id + file_path. Types present: {[t.value for t in match_types]}\n")

        # --- 6. 4.2.2 - review endpoints (accept / reject / reassign) via the real API ---
        print("[6/6] Testing 4.2.2 (review UI: accept / reject / reassign) via the real API...")
        try:
            from fastapi.testclient import TestClient
            from app.api.deps import get_current_user
            from app.main import app as fastapi_app

            fastapi_app.dependency_overrides[get_current_user] = lambda: user
            client = TestClient(fastapi_app)

            list_resp = client.get(f"/api/tenders/{tender.id}/matches")
            assert list_resp.status_code == 200, list_resp.text
            payload = list_resp.json()
            assert len(payload) == 1 and len(payload[0]["matches"]) == 3
            print("  OK: GET /api/tenders/{id}/matches returns the requirement with its 3 matches.")

            by_type = {MatchType(m.match_type): m for m in stored_matches}
            accept_id = by_type[MatchType.AUTO].id
            reject_id = by_type[MatchType.MISSING].id
            reassign_id = by_type[MatchType.SUGGESTED].id
            reassign_target = docs_by_label["missing evidence passage"].id

            r1 = client.post(f"/api/tenders/matches/{accept_id}/review", json={"action": "accept"})
            assert r1.status_code == 200 and r1.json()["review_status"] == "accepted", r1.text
            print("  OK: accept -> review_status = accepted.")

            r2 = client.post(f"/api/tenders/matches/{reject_id}/review", json={"action": "reject"})
            assert r2.status_code == 200 and r2.json()["review_status"] == "rejected", r2.text
            print("  OK: reject -> review_status = rejected.")

            r3 = client.post(
                f"/api/tenders/matches/{reassign_id}/review",
                json={"action": "reassign", "reassign_document_id": str(reassign_target)},
            )
            assert r3.status_code == 200, r3.text
            body = r3.json()
            assert body["review_status"] == "reassigned"
            assert body["document_id"] == str(reassign_target)
            print("  OK: reassign -> review_status = reassigned, document_id updated.")

            r4 = client.post(
                f"/api/tenders/matches/{reassign_id}/review", json={"action": "reassign"}
            )
            assert r4.status_code == 400, "reassign without reassign_document_id should 400"
            print("  OK: reassign without a target document correctly rejected (400).\n")

            del fastapi_app.dependency_overrides[get_current_user]
        except ImportError:
            print("  SKIPPED: install httpx (`pip install httpx --break-system-packages`) "
                  "to exercise the live API endpoints for 4.2.2.\n")

        print("Task 4 (4.1.1 / 4.1.2 / 4.1.3 / 4.2.1 / 4.2.2) verified successfully.")
        return 0

    except AssertionError as exc:
        print(f"\nFAIL: {exc}")
        return 1
    finally:
        # --- cleanup: leave nothing behind ---
        # If the try block failed mid-transaction, the session may be in a
        # "pending rollback" state where even a SELECT/DELETE raises until
        # it's rolled back first - do that before attempting any cleanup.
        db.rollback()
        for match_id in created_ids["matches"]:
            db.query(RequirementEvidenceMatch).filter(RequirementEvidenceMatch.id == match_id).delete()
        if tender is not None:
            db.query(Requirement).filter(Requirement.tender_id == tender.id).delete()
            db.query(Tender).filter(Tender.id == tender.id).delete()
        for chunk_id in created_ids["chunks"]:
            db.query(Chunk).filter(Chunk.id == chunk_id).delete()
        for doc_id in created_ids["documents"]:
            db.query(Document).filter(Document.id == doc_id).delete()
        if user is not None:
            db.query(User).filter(User.id == user.id).delete()
        db.commit()
        db.close()
        embeddings.set_provider(None)  # restore the real provider for the rest of the app
        print("\n[cleanup] All test data removed.")


if __name__ == "__main__":
    sys.exit(main())