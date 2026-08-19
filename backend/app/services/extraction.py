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

Needs a real ANTHROPIC_API_KEY in .env - this calls the real Anthropic
API directly, not a third-party router.
"""
import hashlib
import json
import os
import re
from typing import Optional

from anthropic import AsyncAnthropic
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.models.enums import TenderStatus
from app.models.requirement import Requirement
from app.models.tender import Tender
from app.models.tender_chunk import TenderChunk
from app.services.progress import publish_progress

from dotenv import load_dotenv
load_dotenv()

_api_key = os.getenv("ANTHROPIC_API_KEY")
if not _api_key:
    raise RuntimeError("ANTHROPIC_API_KEY is not set. Add it to your .env file.")

_client = AsyncAnthropic(api_key=_api_key)


class ExtractedRequirement(BaseModel):
    page: str
    section_name: str
    responsibility: str
    reference_number: str
    clause_requirement_description: str
    mandatory: str
    evaluation_impact: str
    dpl: str
    prime: str
    the_t: str
    joint_responsibility: str
    evidence_document_required: str
    remarks: str


class ChunkExtractionResult(BaseModel):
    requirements: list[ExtractedRequirement]


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


async def extract_chunk(chunk: TenderChunk, index: int, total: int) -> dict:
    max_retries = 3
    attempt = 0
    page_range = f"{chunk.page_start}-{chunk.page_end}"

    while attempt < max_retries:
        try:
            response = await _client.messages.create(
                model="claude-sonnet-5",
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
            import asyncio
            await asyncio.sleep(3 * attempt)

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