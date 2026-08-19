"""
Simulated tender processing pipeline - stands in for the real Parse / Chunk
/ Extract / Merge / Match / Report / Assemble pipeline (WBS Sections 2-5),
which hasn't been built yet. This lets Task 7's tracking system (TRK-01
through TRK-04) be built and genuinely tested now, instead of blocking on
that work.

IMPORTANT for whoever wires up the real pipeline later: each stage below
does three things - (1) do the real work, (2) update the Tender row,
(3) call _publish_progress(). Swap the fake work in each step for the
real Parse/Chunk/Extract/etc. logic and everything else (the WebSocket,
the REST fallback, the reconnect behavior) keeps working unchanged.

NOTE ON SYNC vs ASYNC: the rest of this project uses synchronous
SQLAlchemy (app/core/database.py uses create_engine + Session, not an
async engine). This function runs as an async FastAPI background task
(so asyncio.sleep() can pace the simulated delays without blocking other
requests), but the DB calls inside it are still the same sync Session
calls used everywhere else in the project - each one blocks the event
loop for a few milliseconds, a non-issue at this app's current scale (one
local user testing on a laptop). Worth revisiting with an async DB
session if this ever needs to handle many tenders processing concurrently
under real load.
"""
import asyncio
import random
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.ws_manager import manager
from app.models.enums import RequirementStatus, TenderStatus
from app.models.requirement import Requirement
from app.models.tender import Tender
from app.schemas.tender_progress import TenderProgressPayload
from app.services.pipeline_stages import TOTAL_STEPS, current_step_number, stage_label


async def _publish_progress(db: Session, tender: Tender, message: str | None) -> None:
    """Persists the current progress (this is what makes TRK-04
    reconnect/resume work - a client that connects later just reads
    whatever's currently in the row) and broadcasts it to any live
    WebSocket watchers."""
    requirements_extracted = (
        db.query(func.count(Requirement.id)).filter(Requirement.tender_id == tender.id).scalar() or 0
    )

    payload = TenderProgressPayload(
        tender_id=tender.id,
        status=tender.status,
        current_step=current_step_number(tender.status),
        total_steps=TOTAL_STEPS,
        step_label=stage_label(tender.status),
        percent_complete=tender.progress_percent,
        requirements_extracted=requirements_extracted,
        message=message,
    )
    await manager.broadcast(tender.id, payload.model_dump(mode="json"))


async def _advance(
    db: Session, tender: Tender, status: TenderStatus, percent: int, message: str | None = None
) -> None:
    tender.status = status
    tender.progress_percent = percent
    tender.progress_message = message
    db.commit()
    db.refresh(tender)
    await _publish_progress(db, tender, message)


async def run_simulated_pipeline(tender_id: UUID) -> None:
    """Walks a tender through all 8 stages with realistic delays. Runs in
    its own DB session since it executes as a background task outside the
    request that triggered it (the request's own session closes as soon as
    that request finishes)."""
    db = SessionLocal()
    try:
        tender = db.get(Tender, tender_id)
        if tender is None:
            return

        await _advance(db, tender, TenderStatus.PARSING, 5, "Reading uploaded PDF")
        await asyncio.sleep(1.5)

        await _advance(db, tender, TenderStatus.PARSING, 15, "Extracting page text")
        await asyncio.sleep(1.5)

        await _advance(db, tender, TenderStatus.CHUNKING, 25, "Splitting into sections")
        await asyncio.sleep(1.5)

        await _advance(db, tender, TenderStatus.EXTRACTING, 35, "Starting requirement extraction")
        await asyncio.sleep(0.5)

        # Simulate requirements being found one at a time, so
        # requirements_extracted visibly ticks up in real time - this is
        # the part of TRK-02 that's easiest to get wrong if you only ever
        # test with a single "done" jump instead of incremental updates.
        fake_requirement_count = random.randint(12, 20)
        for i in range(1, fake_requirement_count + 1):
            req = Requirement(
                tender_id=tender.id,
                description=f"Simulated requirement {i} (placeholder - real extraction is WBS Task 3.x)",
                marks=1,
                status=RequirementStatus.EXTRACTED,
            )
            db.add(req)
            percent = 35 + int((i / fake_requirement_count) * 20)  # 35 -> 55
            await _advance(
                db, tender, TenderStatus.EXTRACTING, percent,
                f"Extracting requirement {i} of {fake_requirement_count}",
            )
            await asyncio.sleep(0.3)

        await _advance(db, tender, TenderStatus.MERGING, 60, "Merging extracted data")
        await asyncio.sleep(1.5)

        await _advance(db, tender, TenderStatus.MATCHING, 75, "Matching evidence from library")
        await asyncio.sleep(1.5)

        await _advance(db, tender, TenderStatus.REPORTING, 85, "Generating summary report")
        await asyncio.sleep(1.5)

        await _advance(db, tender, TenderStatus.ASSEMBLING_FOLDER, 95, "Assembling output folder")
        await asyncio.sleep(1.5)

        await _advance(db, tender, TenderStatus.READY_FOR_REVIEW, 100, "Ready for review")

    except Exception as exc:
        tender.status = TenderStatus.FAILED
        tender.progress_message = f"Processing failed: {exc}"
        db.commit()
        await _publish_progress(db, tender, tender.progress_message)
        raise
    finally:
        db.close()
