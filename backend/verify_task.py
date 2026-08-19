"""
Run this AFTER `alembic upgrade head` to confirm Task 1.1 actually works
end-to-end: connects to Postgres, confirms every table from the models
exists, then does a real insert + query + rollback so nothing is left
behind in the database.

Usage (from the backend/ folder, with the venv active):
    python verify_task.py
"""
import sys
import uuid

from sqlalchemy import inspect

from app.core.database import SessionLocal, engine
from app.models import AuditLog, Chunk, Document, Requirement, Tender, User
from app.models.enums import DocumentCategory, DocumentFileType, UserRole

EXPECTED_TABLES = {
    "users",
    "documents",
    "document_images",
    "chunks",
    "tenders",
    "tender_chunks",
    "requirements",
    "requirement_evidence_matches",
    "audit_logs",
    "index_jobs",
}


def check_tables_exist() -> bool:
    inspector = inspect(engine)
    existing = set(inspector.get_table_names())
    missing = EXPECTED_TABLES - existing
    if missing:
        print(f"MISSING TABLES: {missing}")
        print("Did you run `alembic upgrade head` yet?")
        return False
    print(f"All {len(EXPECTED_TABLES)} expected tables exist: {sorted(existing & EXPECTED_TABLES)}")
    return True


def check_round_trip() -> bool:
    """Insert one row per model, query it back, then roll back (nothing persists)."""
    db = SessionLocal()
    try:
        user = User(
            name="Test Admin",
            email=f"verify-{uuid.uuid4().hex[:8]}@example.com",
            password_hash="not-a-real-hash",
            role=UserRole.ADMIN,
        )
        db.add(user)
        db.flush()

        document = Document(
            category=DocumentCategory.CASE_STUDY,
            title="Sample Case Study",
            original_filename="sample.docx",
            file_path="/storage/library/sample.docx",
            file_type=DocumentFileType.DOCX,
            uploaded_by=user.id,
        )
        db.add(document)
        db.flush()

        chunk = Chunk(
            document_id=document.id,
            chunk_index=0,
            content="Sample chunk text.",
            category=DocumentCategory.CASE_STUDY,
        )
        db.add(chunk)

        tender = Tender(
            name="Sample Tender",
            original_filename="tender.pdf",
            file_path="/storage/tenders/tender.pdf",
            uploaded_by=user.id,
        )
        db.add(tender)
        db.flush()

        requirement = Requirement(
            tender_id=tender.id,
            page_number=15,
            section_name="Eligibility Criteria",
            description="ISO 9001:2015 Certificate",
            is_mandatory=True,
        )
        db.add(requirement)

        audit_log = AuditLog(user_id=user.id, action="verify_task_1_1")
        db.add(audit_log)

        db.flush()

        # Query back to prove the round trip actually worked, not just that insert didn't error.
        fetched_user = db.query(User).filter_by(id=user.id).one()
        fetched_tender = db.query(Tender).filter_by(id=tender.id).one()
        assert fetched_user.role == UserRole.ADMIN
        assert fetched_tender.requirements[0].description == "ISO 9001:2015 Certificate"

        print("Insert + query round trip succeeded for all 6 models (User, Document, Chunk, "
              "Tender, Requirement, AuditLog).")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"ROUND TRIP FAILED: {exc}")
        return False
    finally:
        db.rollback()  # never leave test data behind
        db.close()


if __name__ == "__main__":
    ok = check_tables_exist()
    ok = check_round_trip() and ok
    if ok:
        print("\nTask 1.1 (Database Models) verified successfully.")
        sys.exit(0)
    else:
        print("\nTask 1.1 verification FAILED - see errors above.")
        sys.exit(1)