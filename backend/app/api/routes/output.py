"""
Task 5 - Output Assembly & Folder Creation (Stage 4)
Linked requirements: TN-OUT-04, TN-MTC-05

Two endpoints that sit after the automatic pipeline (which already runs
Stage 4 once to produce a draft package on upload, see
app/services/output_assembly.py):

  POST /api/tenders/{id}/finalize  - re-runs Stage 4 so the package on
      disk reflects whatever a sales manager did in the review UI
      (Task 4.2.2 - accept/reject/reassign), then locks the tender in as
      FINALIZED. This is WBS 8.2.4's "finalize action".
  GET  /api/tenders/{id}/download  - TN-OUT-04's downloadable .zip.
"""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.enums import TenderStatus
from app.models.tender import Tender
from app.models.user import User
from app.services.output_assembly import run_output_assembly

router = APIRouter(prefix="/api/tenders", tags=["output-assembly"])


@router.post("/{tender_id}/finalize")
def finalize_tender(
    tender_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tender = db.get(Tender, tender_id)
    if tender is None:
        raise HTTPException(status_code=404, detail="Tender not found")
    if tender.status not in (TenderStatus.READY_FOR_REVIEW, TenderStatus.FINALIZED):
        raise HTTPException(
            status_code=400,
            detail=f"Tender is still processing (status={tender.status.value}); "
                   f"finalize once it reaches ready_for_review.",
        )

    result = run_output_assembly(db, tender)  # rebuilds the package with current review decisions

    tender.status = TenderStatus.FINALIZED
    tender.finalized_at = datetime.now(timezone.utc)
    db.commit()

    return {"message": "Tender finalized", "tender_id": tender.id, **result}


@router.get("/{tender_id}/download")
def download_tender_package(
    tender_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tender = db.get(Tender, tender_id)
    if tender is None:
        raise HTTPException(status_code=404, detail="Tender not found")
    if not tender.output_zip_path:
        raise HTTPException(status_code=400, detail="Output package has not been generated yet")

    return FileResponse(
        path=tender.output_zip_path,
        filename=f"{tender.name}.zip",
        media_type="application/zip",
    )
