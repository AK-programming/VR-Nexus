"""
Task 3.1 - Requirement Extraction (LLM-based)
Linked requirement: TN-EXT-01

Same core approach as the source module — parallel per-chunk LLM calls, retry
with backoff, dedup by clause+description hash — but wired into the real
pipeline: reads actual TenderChunk rows instead of an in-memory list, writes
actual Requirement rows instead of returning a JSON blob, and publishes real
progress (requirements_extracted ticking up per chunk, live).

Uses Claude through Anthropic's OpenAI-compatible endpoint, the SAME client and
credentials as the Evidence Library's LLM (app/services/library/llm.py) — so the
whole application runs on one Claude API key. Configure it in .env:

    ANTHROPIC_API_KEY=<your Claude API key>
    ANTHROPIC_BASE_URL=https://api.anthropic.com/v1/
    ANTHROPIC_EXTRACTION_MODEL=claude-haiku-4-5-20251001

Deliberately NOT ANTHROPIC_MODEL (that one stays the heavier "reasoning" model
for the library's grounded Ask). Extraction is a mechanical, high-volume call —
one per ~2000-token chunk, so 100+ per tender — reading text and copying it
verbatim into fixed JSON fields, with no judgment call in it. That is exactly
what a cheap, fast model does as reliably as an expensive one, so extraction
and tender-metadata pull from ANTHROPIC_EXTRACTION_MODEL instead, at roughly
half the per-token cost. If extraction quality ever regresses, point
ANTHROPIC_EXTRACTION_MODEL at ANTHROPIC_MODEL's value in .env to compare.

The model asks for strict JSON; `_coerce_json` tolerates a stray sentence or a
markdown fence around it before validation, and a chunk that fails all three
attempts is logged and counted rather than taking the run down.
"""
import asyncio
import hashlib
import json
import logging
import re
from decimal import Decimal, InvalidOperation
from typing import Optional

from openai import AsyncOpenAI
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
_client: Optional[AsyncOpenAI] = None

# The extraction model, read from settings. Deliberately ANTHROPIC_EXTRACTION_MODEL,
# not ANTHROPIC_MODEL: extraction is high-volume mechanical work (see module
# docstring), so it runs on a cheaper model than the app's reasoning calls do.
EXTRACTION_MODEL = settings.ANTHROPIC_EXTRACTION_MODEL
MAX_EXTRACTION_RETRIES = 3
EXTRACTION_CONCURRENCY = max(1, settings.EXTRACTION_CONCURRENCY)

#: How many chunks are allowed to fail before the whole extraction is declared a
#: failed run rather than a partial success.
#:
#: Every chunk gets `MAX_EXTRACTION_RETRIES` attempts before it counts as failed
#: here, so a failure at this point is not a transient blip — it means that chunk
#: could not be extracted at all. A tender is a legal document read clause by
#: clause; a run that quietly lost a third of it is not a working analysis, it is
#: a silent-loss failure with a plausible-looking tracker attached. Above this
#: fraction (default 0.30 = 30% of chunks failed) the run is failed with the
#: failed count and the model in the message, so the operator can fix the cause
#: (a rate limit, a stale model name, a network problem the worker hit partway
#: through) and retry from the error log. Below it, the number of failures rides
#: forward on `progress_message` and shows up in the tracker's Summary, so the
#: reviewer sees "3 of 159 chunk(s) failed" while they read the requirements.
MAX_ACCEPTABLE_CHUNK_FAILURE_RATE = 0.30


class TenderCancelled(Exception):
    """Raised when a user pressed Stop mid-extraction (the tender row was set
    to FAILED out from under the running worker). The pipeline catches it and
    stops cleanly rather than treating it as a crash."""


class ExtractionFailed(Exception):
    """Raised when extraction finished but produced nothing usable.

    Zero requirements is not a successful analysis. Every downstream stage is a
    no-op on an empty set, so without this the run sails through matching,
    reporting and assembly and parks at READY_FOR_REVIEW — presenting an empty
    review screen and an empty Excel tracker as a finished result, with nothing
    anywhere saying why. The commonest cause is that every chunk failed to reach
    the model (a stale ANTHROPIC_MODEL, a rejected key, no egress from the worker),
    which is a configuration problem the operator can fix and retry, and which is
    invisible unless the run is failed with it written down.
    """


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        if not settings.ANTHROPIC_API_KEY:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. Add your Claude API key to .env "
                "(with ANTHROPIC_BASE_URL pointing at Anthropic's OpenAI-compatible "
                "endpoint) before running tender extraction."
            )
        _client = AsyncOpenAI(
            api_key=settings.ANTHROPIC_API_KEY,
            base_url=settings.ANTHROPIC_BASE_URL,
            # A hard per-request ceiling so one slow/hung Claude call cannot stall
            # the whole run: the SDK default is 600s, which is how a single chunk
            # can freeze extraction for ~10 minutes. Our own retry loop (below)
            # handles transient failures, so the SDK's internal retries are capped
            # low to avoid compounding backoff on top of ours.
            timeout=60.0,
            max_retries=1,
        )
    return _client


class ExtractedRequirement(BaseModel):
    """One tracker row, in the tender's own words.

    Every field is a string and every field is optional-by-default: the tracker
    has to reproduce what the document says, so a value the tender does not state
    comes back as "" and is written as an empty cell rather than being guessed or
    filled with "N/A". `extra_fields` is the open end - anything this particular
    tender labels that the fixed columns do not model lands there as
    {column name -> value} and becomes its own column in the workbook.
    """

    page: str = ""
    section_name: str = ""
    responsibility: str = ""
    reference_number: str = ""
    clause_requirement_description: str
    mandatory: str = ""
    evaluation_impact: str = ""
    marks: str = ""
    dpl: str = ""
    prime: str = ""
    the_t: str = ""
    joint_responsibility: str = ""
    evidence_document_required: str = ""
    remarks: str = ""
    extra_fields: dict[str, str] = {}


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
    f"You build a tender compliance tracker. Extract every requirement, obligation, "
    f"eligibility criterion and evaluation item in the text, matching this exact JSON "
    f"schema: {_SCHEMA_STRING}.\n"
    "RULES:\n"
    "1. Copy the tender's OWN wording for every field. Do not paraphrase, normalise or "
    "re-label values.\n"
    "2. If the tender does not state a field, return an EMPTY STRING \"\" for it. Never "
    "invent a value and never write 'N/A', 'None' or 'Unknown'.\n"
    "3. page: the page or page range exactly as it appears, e.g. \"147\" or \"1-2\".\n"
    "4. mandatory: exactly as the tender frames it, e.g. \"Yes\", \"No\", \"No/Advisory\".\n"
    "5. evaluation_impact: exactly as stated, including compound values, e.g. "
    "\"Pass/Fail\", \"Technical Score\", \"Compliance\", \"Technical Compliance\", "
    "\"Financial / Pass-Fail\", \"Schedule Compliance\".\n"
    "6. marks: the points/marks this item carries if the tender states them, else \"\".\n"
    "7. evidence_document_required: the document or evidence the proposer must supply.\n"
    "8. extra_fields: any OTHER labelled data this tender attaches to the requirement "
    "that the fields above do not cover, as {\"Column Name\": \"value\"}. Use the "
    "tender's own label as the key. Return {} when there is nothing extra.\n"
    "Return ONLY a single JSON object. Do not wrap output in markdown."
)

_FENCE_OPEN_RE = re.compile(r"^```(?:json)?\s*\n?")
_FENCE_CLOSE_RE = re.compile(r"\n?```\s*$")


def _strip_markdown_fence(raw: str) -> str:
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = _FENCE_OPEN_RE.sub("", cleaned)
        cleaned = _FENCE_CLOSE_RE.sub("", cleaned)
    return cleaned.strip()


def _coerce_json(raw: str) -> str:
    """Return the JSON payload from a model response.

    Anthropic's messages API returned fairly clean JSON; Gemini through the
    OpenAI-compatible endpoint is usually clean too but occasionally frames the
    object with a sentence. Strip a markdown fence, then, if the text does not
    already start as JSON, take the widest {...} span. Validation downstream is
    still the real gate — this only improves the odds it succeeds first try."""
    cleaned = _strip_markdown_fence(raw)
    if cleaned.startswith("{") or cleaned.startswith("["):
        return cleaned
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        return cleaned[start : end + 1]
    return cleaned


def _parse_page_number(page: str) -> Optional[int]:
    """page comes back as free text like '12' or '12-14' - takes the first
    number found, since page_number is a single int column."""
    match = re.search(r"\d+", page or "")
    return int(match.group()) if match else None


def _parse_bool(value: str) -> Optional[bool]:
    """Normalise the mandatory flag, tolerating the compound forms real tenders use.

    WBS TN-EXT-02 calls this the "Mandatory/Advisory flag", and the sample tracker
    carries "No/Advisory" alongside plain "Yes"/"No". Prefix matching means
    "No/Advisory" reads as not-mandatory instead of collapsing to NULL; the exact
    wording is preserved separately in `mandatory_raw`."""
    v = (value or "").strip().lower()
    if not v or v in ("n/a", "na", "none", "unspecified"):
        return None
    if v.startswith("yes") or v in ("true", "mandatory", "required"):
        return True
    if v.startswith("no") or v in ("false", "optional", "advisory"):
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


# Placeholders a model reaches for when a tender simply does not state something.
# They are dropped so the tracker shows an empty cell, which is the honest answer.
_EMPTY_VALUES = {"", "n/a", "na", "-", "--", "none stated", "not stated", "not specified"}


def _clean(value: Optional[str]) -> Optional[str]:
    """Trim a verbatim field, turning placeholder noise into a genuine blank."""
    text = (value or "").strip()
    return None if text.lower() in _EMPTY_VALUES else text


def _evidence_required(value: Optional[str]) -> bool:
    """True when the tender actually asks for a document to be supplied."""
    text = (_clean(value) or "").lower()
    return bool(text) and text not in ("no", "none", "not required", "nil")


def _clean_extras(extras: Optional[dict]) -> Optional[dict]:
    """Keep the tender-specific extras as {label -> value}, dropping blanks.

    Bounded deliberately: a malformed model response should not be able to widen
    the workbook without limit, so keys are trimmed and the map is capped."""
    if not isinstance(extras, dict):
        return None
    cleaned: dict[str, str] = {}
    for key, value in extras.items():
        label = str(key).strip()[:80]
        text = _clean(str(value) if value is not None else "")
        if label and text:
            cleaned[label] = text[:2000]
        if len(cleaned) >= 25:
            break
    return cleaned or None


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
            response = await client.chat.completions.create(
                model=EXTRACTION_MODEL,
                max_tokens=8192,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": f"Pages {page_range}, Section: {chunk.section}\n\n{chunk.content}",
                    },
                ],
            )
            raw = (response.choices[0].message.content or "").strip()
            parsed = ChunkExtractionResult.model_validate_json(_coerce_json(raw))
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

    # Extraction is I/O-bound — one LLM round-trip per chunk — so the chunks run
    # CONCURRENTLY, bounded by a semaphore, rather than strictly one after another.
    # For a large tender (159 chunks here) that is the single biggest speedup:
    # while one chunk waits on Gemini, others are already in flight. Only the LLM
    # calls are parallelised; every DB write below runs back on this one coroutine,
    # so the SQLAlchemy Session stays single-threaded and dedup order is preserved.
    # Results are consumed as they finish (asyncio.as_completed) so the progress
    # bar keeps advancing instead of jumping at the end.
    sem = asyncio.Semaphore(EXTRACTION_CONCURRENCY)

    async def _run_one(idx: int, ch: TenderChunk):
        async with sem:
            return await extract_chunk(ch, idx, total)

    tasks = [asyncio.create_task(_run_one(i, chunk)) for i, chunk in enumerate(chunks, start=1)]

    completed = 0
    for coro in asyncio.as_completed(tasks):
        result = await coro
        completed += 1

        # Cooperative cancellation: a user Stop sets this tender to FAILED in the
        # API's own session. Re-read the row every few chunks and, if it flipped,
        # cancel the in-flight calls and bail — this is what makes Stop actually
        # halt a long extraction rather than only relabelling it in the UI.
        if completed % 3 == 0 or completed == total:
            db.refresh(tender)
            if tender.status == TenderStatus.FAILED:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                raise TenderCancelled()

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
                    # page_number stays an int for ordering; page_label keeps "1-2".
                    page_number=_parse_page_number(req.page),
                    page_label=_clean(req.page),
                    section_name=_clean(req.section_name),
                    clause_reference=_clean(req.reference_number),
                    description=req.clause_requirement_description,
                    # Normalised for coverage/filtering, verbatim for the tracker.
                    is_mandatory=_parse_bool(req.mandatory),
                    mandatory_raw=_clean(req.mandatory),
                    evaluation_impact=_parse_evaluation_impact(req.evaluation_impact),
                    evaluation_impact_raw=_clean(req.evaluation_impact),
                    marks=_parse_marks(req.marks),
                    responsibility=_clean(req.responsibility),
                    dpl=_clean(req.dpl),
                    prime=_clean(req.prime),
                    the_t=_clean(req.the_t),
                    joint_responsibility=_clean(req.joint_responsibility),
                    evidence_required=_evidence_required(req.evidence_document_required),
                    evidence_description=_clean(req.evidence_document_required),
                    remarks=_clean(req.remarks),
                    extra_fields=_clean_extras(req.extra_fields),
                ))
                created_count += 1

        db.commit()
        percent = 35 + int((completed / total) * 25)  # 35 -> 60, mirrors the overall pipeline's step weighting
        publish_progress(
            str(tender.id), TenderStatus.EXTRACTING,
            percent=percent,
            message=f"Processed chunk {completed} of {total}",
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

    # Persisted, not just published: the socket frame is gone on reload, and
    # "12 of 159 chunks failed" is the context that explains a thin tracker.
    tender.progress_message = (
        f"Extraction complete: {created_count} unique requirements, "
        f"{failed_chunks} chunk(s) failed"
    )[:500]
    db.commit()

    # Failure decisions, in order — the strictest first, so the failure message a
    # run gets is always the most specific truth about it.
    #
    # A run that lost a large fraction of its chunks is not a working analysis,
    # even when what came back is nonzero. This is the case that used to be the
    # worst kind of silent failure: a tender extracted with 40 requirements out
    # of 400, presented as a finished result, with no line anywhere saying which
    # 360 the reviewer is missing. Fail it here, name the count, and the operator
    # retries after fixing whatever the worker log records for the failing chunks.
    if total > 0 and failed_chunks / total > MAX_ACCEPTABLE_CHUNK_FAILURE_RATE:
        raise ExtractionFailed(
            f"Extraction stopped: {failed_chunks} of {total} chunk(s) failed to reach the "
            f"language model after {MAX_EXTRACTION_RETRIES} attempts each — over the "
            f"{int(MAX_ACCEPTABLE_CHUNK_FAILURE_RATE * 100)}% threshold, which means the "
            "tender was only partially read and the requirements list would be missing "
            "clauses. Common causes: a provider rate limit (lower EXTRACTION_CONCURRENCY), "
            f"a stale ANTHROPIC_EXTRACTION_MODEL (currently '{EXTRACTION_MODEL}'), or the "
            "worker losing network access partway through. The worker log has the "
            "per-chunk error. Fix the cause, then retry from the error log."
        )

    # Nothing extracted is a failed run, not a finished one. Which of the two
    # reasons it was decides what the operator does next, so they are worded
    # apart rather than sharing one vague sentence.
    if created_count == 0:
        if failed_chunks >= total:
            raise ExtractionFailed(
                f"No requirements could be extracted: all {total} chunk(s) failed to reach "
                f"the language model after {MAX_EXTRACTION_RETRIES} attempts each. This is "
                "almost always configuration — check ANTHROPIC_API_KEY, "
                f"ANTHROPIC_EXTRACTION_MODEL (currently '{EXTRACTION_MODEL}'; Claude retires "
                "model names) and the worker's network access, then retry. The worker log "
                "has the per-chunk error."
            )
        raise ExtractionFailed(
            f"The tender was read ({total} chunk(s), {failed_chunks} failed) but no "
            "requirements were found in it. If it does contain requirements, the PDF may "
            "have no text layer — a scan that OCR could not read comes through as empty pages."
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
    "explicitly present in the text. Return ONLY a single JSON object. Do not wrap output in markdown."
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
        response = await client.chat.completions.create(
            model=EXTRACTION_MODEL,
            max_tokens=1024,
            messages=[
                {"role": "system", "content": _METADATA_SYSTEM_PROMPT},
                {"role": "user", "content": sample_text[:12000]},
            ],
        )
        raw = (response.choices[0].message.content or "").strip()
        parsed = TenderMetadata.model_validate_json(_coerce_json(raw))
        return parsed.model_dump()
    except Exception as exc:
        logger.warning("Tender metadata extraction failed (non-fatal): %s", exc)
        return {}
