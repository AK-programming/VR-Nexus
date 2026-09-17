"""
Excel export customization endpoints.

Client requirement (Users admin page follow-up): let the user customize the
generated Requirements tracker before/after it's produced - which columns
show, in what order, under what label, whether empty rows are dropped, plus
their own added blank columns. Per the client's own clarifying answers:

  - reusable: GET/PUT /api/users/me/excel-template is the account's saved
    default, applied to every tender from then on.
  - per-tender: GET/PUT /api/tenders/{id}/excel-template lets one tender
    deviate from that default without changing it ("different format for
    the different [tenders] but may be the same tender").
  - gated the same way as the rest of tender analysis: every route here
    requires FeatureKey.TENDER_ANALYSIS, exactly like app/api/routes/tenders.py
    ("if the admin give the access them about the tender analysis then they
    will able do the same like admin").

Saving a per-tender override (PUT) regenerates that tender's workbook/zip
immediately via rebuild_outputs, so output_zip_path/GET .../download always
reflect the current template - the user does not need a second "apply" step.
Saving the account default does NOT touch any existing tender's output
(only tenders generated or re-saved after that point pick it up), since
retroactively rewriting every past tender's tracker the moment someone
tweaks their default would be surprising, not helpful.
"""
from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_feature
from app.core.database import get_db
from app.models.enums import FeatureKey
from app.models.tender import Tender
from app.models.user import User
from app.schemas.excel_template import ExcelTemplateIn, ExcelTemplateOut
from app.tasks.tender_pipeline import rebuild_outputs

logger = logging.getLogger(__name__)

router = APIRouter(tags=["excel-template"])


def _get_tender(db: Session, tender_id: uuid.UUID) -> Tender:
    tender = db.get(Tender, tender_id)
    if tender is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tender not found.")
    return tender


# --------------------------------------------------------------------------- #
# account default                                                             #
# --------------------------------------------------------------------------- #
@router.get("/api/users/me/excel-template", response_model=ExcelTemplateOut)
def get_my_excel_template(
    current_user: User = Depends(require_feature(FeatureKey.TENDER_ANALYSIS)),
) -> ExcelTemplateOut:
    """The signed-in user's saved default export shape, or template: null if
    they've never customized it (the platform default layout applies)."""
    if not current_user.default_excel_template:
        return ExcelTemplateOut(template=None)
    return ExcelTemplateOut(template=current_user.default_excel_template)


@router.put("/api/users/me/excel-template", response_model=ExcelTemplateOut)
def set_my_excel_template(
    body: ExcelTemplateIn,
    current_user: User = Depends(require_feature(FeatureKey.TENDER_ANALYSIS)),
    db: Session = Depends(get_db),
) -> ExcelTemplateOut:
    """Save (or, with template: null, clear) the account's reusable default.
    Applies to tenders generated/regenerated from now on - existing output
    files are left as they are."""
    current_user.default_excel_template = body.template.model_dump() if body.template else None
    db.commit()
    db.refresh(current_user)
    return ExcelTemplateOut(template=current_user.default_excel_template)


# --------------------------------------------------------------------------- #
# per-tender override                                                         #
# --------------------------------------------------------------------------- #
@router.get("/api/tenders/{tender_id}/excel-template", response_model=ExcelTemplateOut)
def get_tender_excel_template(
    tender_id: uuid.UUID,
    current_user: User = Depends(require_feature(FeatureKey.TENDER_ANALYSIS)),
    db: Session = Depends(get_db),
) -> ExcelTemplateOut:
    """This tender's own override, if it has one (template: null means it
    falls through to the user's account default, or the platform default)."""
    tender = _get_tender(db, tender_id)
    if not tender.excel_template_override:
        return ExcelTemplateOut(template=None)
    return ExcelTemplateOut(template=tender.excel_template_override)


@router.put("/api/tenders/{tender_id}/excel-template", response_model=ExcelTemplateOut)
def set_tender_excel_template(
    tender_id: uuid.UUID,
    body: ExcelTemplateIn,
    current_user: User = Depends(require_feature(FeatureKey.TENDER_ANALYSIS)),
    db: Session = Depends(get_db),
) -> ExcelTemplateOut:
    """Save (or, with template: null, clear back to the account default) this
    one tender's override, then immediately regenerate its workbook/zip so
    the download reflects it - this is the "is the format OK? ... if not,
    they will customize it" step from the client's own answer, and the
    regeneration is what actually applies the change rather than just
    recording a preference nobody sees."""
    tender = _get_tender(db, tender_id)
    tender.excel_template_override = body.template.model_dump() if body.template else None
    db.commit()
    db.refresh(tender)

    try:
        rebuild_outputs(db, tender)
    except Exception as exc:
        # The template itself is saved either way; a regeneration failure
        # (e.g. no output has ever been assembled yet for this tender) should
        # not make the save look like it failed, since the format IS saved
        # and will apply the next time the folder is (re)built.
        logger.warning(
            "Saved excel_template_override for tender %s but could not "
            "regenerate its output immediately: %s", tender.id, exc,
        )

    db.refresh(tender)
    return ExcelTemplateOut(template=tender.excel_template_override)


@router.post("/api/tenders/{tender_id}/excel-template/regenerate", response_model=ExcelTemplateOut)
def regenerate_tender_excel(
    tender_id: uuid.UUID,
    current_user: User = Depends(require_feature(FeatureKey.TENDER_ANALYSIS)),
    db: Session = Depends(get_db),
) -> ExcelTemplateOut:
    """Rebuild this tender's workbook/zip from whichever template currently
    applies (override, else account default, else platform default) without
    changing the template itself - for "I changed my account default, now
    make this specific tender pick it up" without re-saving an override."""
    tender = _get_tender(db, tender_id)
    rebuild_outputs(db, tender)
    db.refresh(tender)
    return ExcelTemplateOut(template=tender.excel_template_override)
