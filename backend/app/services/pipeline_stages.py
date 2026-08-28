"""
Task 7.1.3 - Explicit pipeline stage tracking
Linked requirement: TRK-03

The Tender model's `status` column (Task 1.1.4) already has all 8 stages as
enum values. This file adds the two things that column alone can't give
you: an explicit ORDER (so we can compute "step 3 of 8"), and a
human-readable LABEL for each stage (so the frontend doesn't have to turn
"ASSEMBLING_FOLDER" into "Assembling Output Folder" itself).

Deliberately kept as one small ordered list, not scattered across the
codebase - if the pipeline ever grows a 9th stage, this is the one place
that needs updating.

Known duplication, flagged rather than silently "fixed": app/services/progress.py
carries its own PIPELINE_STAGES and STAGE_LABELS. The stage order is identical,
but the labels differ ("Parsing" there vs "Parsing Document" here, "Merging &
de-duplicating" vs "Merging Extracted Data"). progress.py's copy is the one that
reaches the client, because publish_progress() builds step_label from its own
dict; this module's labels are only used by callers that import stage_label()
directly. Consolidating them is a real cleanup, but it changes the strings on the
wire, so it belongs in a deliberate change with the frontend rather than in a
file copy.
"""
from app.models.enums import TenderStatus

# Order matters here - index in this list IS "current_step" in the
# progress payload. FAILED isn't in the normal flow (it can happen from
# any stage), so it's handled separately, not given a step number.
PIPELINE_STAGES: list[TenderStatus] = [
    TenderStatus.UPLOADED,
    TenderStatus.PARSING,
    TenderStatus.CHUNKING,
    TenderStatus.EXTRACTING,
    TenderStatus.MERGING,
    TenderStatus.MATCHING,
    TenderStatus.REPORTING,
    TenderStatus.ASSEMBLING_FOLDER,
    TenderStatus.READY_FOR_REVIEW,
]

TOTAL_STEPS = len(PIPELINE_STAGES)

STAGE_LABELS: dict[TenderStatus, str] = {
    TenderStatus.UPLOADED: "Uploaded",
    TenderStatus.PARSING: "Parsing Document",
    TenderStatus.CHUNKING: "Chunking Content",
    TenderStatus.EXTRACTING: "Extracting Requirements",
    TenderStatus.MERGING: "Merging Extracted Data",
    TenderStatus.MATCHING: "Matching Evidence",
    TenderStatus.REPORTING: "Generating Report",
    TenderStatus.ASSEMBLING_FOLDER: "Assembling Output Folder",
    TenderStatus.READY_FOR_REVIEW: "Ready for Review",
    TenderStatus.FINALIZED: "Finalized",
    TenderStatus.FAILED: "Failed",
}


def current_step_number(status: TenderStatus) -> int:
    """1-indexed step number for the progress payload's "current_step".
    Returns TOTAL_STEPS for FINALIZED (fully done), and the step it was on
    for FAILED isn't derivable from status alone - the caller passes 0 in
    that case since "which step failed" needs to be tracked separately."""
    if status == TenderStatus.FINALIZED:
        return TOTAL_STEPS
    try:
        return PIPELINE_STAGES.index(status) + 1
    except ValueError:
        return 0


def stage_label(status: TenderStatus) -> str:
    return STAGE_LABELS.get(status, status.value)
