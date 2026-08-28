"""
Task 3.1 - Requirement Extraction (LLM-based)
Linked requirement: TN-EXT-01

Adapted from Shaheer's section_3_extraction.py: same core approach (parallel
Claude calls per chunk, retry with backoff, dedup by clause+description
hash) but wired into the real pipeline - reads actual TenderChunk rows
instead of an in-memory list, writes actual Requirement rows instead of
returning a JSON blob, and publishes real progress (including
requirements_extracted ticking up per chunk, live) instead of just
printing to a console.

Needs ANTHROPIC_API_KEY in .env. Optionally set ANTHROPIC_BASE_URL to route
through an Anthropic-compatible gateway (e.g. AgentRouter); leave it empty
to call api.anthropic.com directly.

Two small changes from the source copy of this module, both about being able to
debug a failed run: `import asyncio` moved to module scope (it was re-imported
inside the retry loop), and the swallowed exception is now logged. Previously a
chunk that failed all three attempts only incremented `failed_chunks`, so a
wrong model name, an expired key and a malformed response were indistinguishable
from each other and from the outside looked like "extraction just found nothing".
"""
import asyncio
import hashlib
import json
import logging
import re
from decimal import Decimal, InvalidOperation
from typing import Optional

from anthropic import AsyncAnthropic
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.enums import EvaluationImpact, TenderStatus
from app.models.requirement import Requirement
from app.models.tender import Tender
from app.models.tender_chunk import TenderChunk
from app.services.progress import publish_progress

logger = logging.getLogger(__name__)

settings = get_settings()
_client: Optional[AsyncAnthropic] = None

# Kept as a named constant rather than inline so the model in use is findable
# without reading the request body construction.
EXTRACTION_MODEL = "claude-sonnet-5"
MAX_EXTRACTION_RETRIES = 3


def _get_client() -> AsyncAnthropic:
    global _client
    if _client is None:
        if not settings.ANTHROPIC_API_KEY:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. Add it to your .env file before running tender extraction."
            )
        kwargs: dict = {"api_key": settings.ANTHROPIC_API_KEY}
        if settings.ANTHROPIC_BASE_URL:
            kwargs["base_url"] = settings.ANTHROPIC_BASE_URL.rstrip("/")
        _client = AsyncAnthropic(**kwargs)
    return _client


class ExtractedRequirement(BaseModel):
    page: str
    section_name: str
    responsibility: str
    reference_number: str
    clause_requirement_description: str
    mandatory: str
    evaluation_impact: str
    marks: str = "N/A"
    dpl: str
    prime: str
    the_t: str
    joint_responsibility: str
    evidence_document_required: str
    remarks: str


class ChunkExtractionResult(BaseModel):
    requirements: list[ExtractedRequirement]


class TenderMetadata(BaseModel):
    """Top-level facts about the tender itself (not individual requirements),
    pulled in one pass over the opening pages. Every field defaults to "N/A"
    so a document that omits one still validates."""
    reference_id: str = "N/A"
    issuing_authority: str = "N/A"
    sector: str = "N/A"
    location: str = "N/A"
    tender_value: str = "N/A"
    submission_deadline: str = "N/A"


_SCHEMA_STRING = json.dumps(ChunkExtractionResult.model_json_schema())
_SYSTEM_PROMPT = (
    f"Extract requirements matching this exact schema: {_SCHEMA_STRING}. "
    "Fields section_name, reference_number, clause_requirement_description, and "
    "evidence_document_required are strictly mandatory. If any data is missing, insert "
    "'N/A' or 'Unnumbered'. Do not wrap output in markdown."
)

_FENCE_OPEN_RE = re.compile(r"^```(?:json)?\s*\n?")
_FENCE_CLOSE_RE = re.compile(r"\n?```\s*$")


def _strip_markdown_fence(raw: str) -> str:
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = _FENCE_OPEN_RE.sub("", cleaned)
        cleaned = _FENCE_CLOSE_RE.sub("", cleaned)
    return cleaned.strip()


def _parse_page_number(page: str) -> Optional[int]:
    """page comes back as free text like '12' or '12-14' - takes the first
    number found, since page_number is a single int column."""
    match = re.search(r"\d+", page or "")
    return int(match.group()) if match else None


def _parse_bool(value: str) -> Optional[bool]:
    v = (value or "").strip().lower()
    if v in ("yes", "true", "mandatory"):
        return True
    if v in ("no", "false", "optional"):
        return False
    return None


def _parse_evaluation_impact(value: str) -> Optional[EvaluationImpact]:
    """Map the LLM's free-text evaluation impact onto the EvaluationImpact
    enum. Tolerates casing and separators ("Pass/Fail", "pass-fail",
    "Technical Evaluation") and returns None when nothing matches, so the
    column stays null rather than storing a guess."""
    v = (value or "").strip().lower().replace("/", "_").replace("-", "_").replace(" ", "_")
    if not v or v in ("n_a", "na", "none", "unnumbered"):
        return None
    for impact in EvaluationImpact:
        if impact.value == v:
            return impact
    if "pass" in v and "fail" in v:
        return EvaluationImpact.PASS_FAIL
    if "technical" in v:
        return EvaluationImpact.TECHNICAL
    if "financial" in v:
        return EvaluationImpact.FINANCIAL
    if "compli" in v:  # compliance / compliant
        return EvaluationImpact.COMPLIANCE
    return None


def _parse_marks(value: str) -> Optional[Decimal]:
    """Pull the first number out of the LLM's marks text ("5", "10 marks",
    "7.5%"); return None for "N/A"/blank so marks stays null rather than 0,
    keeping "no marks stated" distinct from "worth zero"."""
    match = re.search(r"\d+(?:\.\d+)?", value or "")
    if not match:
        return None
    try:
        return Decimal(match.group())
    except InvalidOperation:
        return None


async def extract_chunk(chunk: TenderChunk, index: int, total: int) -> dict:
    client = _get_client()
    attempt = 0
    page_range = f"{chunk.page_start}-{chunk.page_end}"

    while attempt < MAX_EXTRACTION_RETRIES:
        try:
            response = await client.messages.create(
                model=EXTRACTION_MODEL,
                max_tokens=8192,
                system=_SYSTEM_PROMPT,
                messages=[
                    {"role": "user", "content": f"Pages {page_range}, Section: {chunk.section}\n\n{chunk.content}"}
                ],
            )
            ai_json_response = "".join(
                block.text for block in response.content if hasattr(block, "text")
            ).strip()
            ai_json_response = _strip_markdown_fence(ai_json_response)
            parsed = ChunkExtractionResult.model_validate_json(ai_json_response)
            return {"status": "success", "data": parsed.requirements}
        except Exception as exc:
            attempt += 1
            logger.warning(
                "Extraction attempt %s/%s failed for chunk %s (%s of %s): %s",
                attempt,
                MAX_EXTRACTION_RETRIES,
                chunk.chunk_index,
                index,
                total,
                exc,
            )
            if attempt < MAX_EXTRACTION_RETRIES:
                await asyncio.sleep(3 * attempt)

    logger.error(
        "Giving up on chunk %s after %s attempts; it will be counted as a failed chunk.",
        chunk.chunk_index,
        MAX_EXTRACTION_RETRIES,
    )
    return {"status": "failed", "data": [], "chunk_index": chunk.chunk_index}


def _hash_requirement(req: ExtractedRequirement) -> str:
    unique_string = f"{req.reference_number}_{req.clause_requirement_description}".lower().strip()
    return hashlib.md5(unique_string.encode()).hexdigest()


async def run_extraction(db: Session, tender: Tender) -> dict:
    """Runs extraction against every TenderChunk for this tender, persists
    deduplicated Requirement rows, and publishes live progress as each
    chunk completes - requirements_extracted genuinely ticks up per chunk,
    not just at the end."""
    chunks = (
        db.query(TenderChunk)
        .filter(TenderChunk.tender_id == tender.id)
        .order_by(TenderChunk.chunk_index)
        .all()
    )
    total = len(chunks)
    seen_hashes: set[str] = set()
    created_count = 0
    failed_chunks = 0

    tender.status = TenderStatus.EXTRACTING
    db.commit()
    publish_progress(
        str(tender.id), TenderStatus.EXTRACTING,
        percent=35, message=f"Starting extraction across {total} chunks",
        extracted_requirements_count=0,
    )

    if total == 0:
        # Nothing to divide by below, and an empty tender is a caller bug the
        # chunking guard should already have caught.
        publish_progress(
            str(tender.id), TenderStatus.EXTRACTING,
            percent=60, message="No chunks to extract from.",
            extracted_requirements_count=0,
        )
        return {"created": 0, "failed_chunks": 0}

    for i, chunk in enumerate(chunks, start=1):
        result = await extract_chunk(chunk, i, total)

        if result["status"] == "failed":
            failed_chunks += 1
        else:
            for req in result["data"]:
                req_hash = _hash_requirement(req)
                if req_hash in seen_hashes:
                    continue
                seen_hashes.add(req_hash)

                db.add(Requirement(
                    tender_id=tender.id,
                    page_number=_parse_page_number(req.page),
                    section_name=req.section_name,
                    clause_reference=req.reference_number,
                    description=req.clause_requirement_description,
                    is_mandatory=_parse_bool(req.mandatory),
                    evaluation_impact=_parse_evaluation_impact(req.evaluation_impact),
                    marks=_parse_marks(req.marks),
                    responsibility=req.responsibility,
                    dpl=req.dpl,
                    prime=req.prime,
                    the_t=req.the_t,
                    joint_responsibility=req.joint_responsibility,
                    evidence_required=bool(req.evidence_document_required and req.evidence_document_required.lower() not in ("n/a", "no", "none")),
                    evidence_description=req.evidence_document_required,
                    remarks=req.remarks,
                ))
                created_count += 1

        db.commit()
        percent = 35 + int((i / total) * 25)  # 35 -> 60, mirrors the overall pipeline's step weighting
        publish_progress(
            str(tender.id), TenderStatus.EXTRACTING,
            percent=percent,
            message=f"Processed chunk {i} of {total}",
            extracted_requirements_count=created_count,
        )

    tender.extracted_requirements_count = created_count
    db.commit()
    publish_progress(
        str(tender.id), TenderStatus.EXTRACTING,
        percent=60,
        message=f"Extraction complete: {created_count} unique requirements, {failed_chunks} chunk(s) failed",
        extracted_requirements_count=created_count,
    )

    return {"created": created_count, "failed_chunks": failed_chunks}


_METADATA_SYSTEM_PROMPT = (
    f"Extract top-level tender metadata matching this exact schema: "
    f"{json.dumps(TenderMetadata.model_json_schema())}. "
    "reference_id is the tender/RFP reference or notice number. "
    "issuing_authority is the organisation issuing the tender. "
    "tender_value is the estimated contract value exactly as written "
    "(keep the currency symbol/code). submission_deadline must be an ISO date "
    "(YYYY-MM-DD) or 'N/A' if no date is stated. Use 'N/A' for anything not "
    "explicitly present in the text. Do not wrap output in markdown."
)


async def extract_tender_metadata(sample_text: str) -> dict:
    """Best-effort, single-shot extraction of the tender's own metadata from
    its opening pages. Returns a dict of raw string values (reference_id,
    issuing_authority, sector, location, tender_value, submission_deadline),
    or {} on any failure. Never raises: metadata is a convenience the user can
    correct via PATCH, not a pipeline dependency, so a failure here must not
    take the run down."""
    sample_text = (sample_text or "").strip()
    if not sample_text:
        return {}
    try:
        client = _get_client()
        response = await client.messages.create(
            model=EXTRACTION_MODEL,
            max_tokens=1024,
            system=_METADATA_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": sample_text[:12000]}],
        )
        raw = "".join(block.text for block in response.content if hasattr(block, "text")).strip()
        parsed = TenderMetadata.model_validate_json(_strip_markdown_fence(raw))
        return parsed.model_dump()
    except Exception as exc:
        logger.warning("Tender metadata extraction failed (non-fatal): %s", exc)
        return {}
