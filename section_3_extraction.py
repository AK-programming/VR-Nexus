import os
import re
import json
import hashlib
import asyncio
from typing import List
from pydantic import BaseModel
from anthropic import AsyncAnthropic
from dotenv import load_dotenv

load_dotenv()

_api_key = os.getenv("ANTHROPIC_API_KEY")
if not _api_key:
    # Fail loudly and early instead of letting every single chunk call
    # fail later with a confusing auth error.
    raise RuntimeError("ANTHROPIC_API_KEY is not set. Add it to your environment or .env file.")

client = AsyncAnthropic(api_key=_api_key)


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
    requirements: List[ExtractedRequirement]


# Computed once at import time instead of on every single chunk call.
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
    """Removes a wrapping ```json ... ``` fence if present.

    The original code did `text[7:-3]` / `text[3:-3]` whenever the response
    *started* with a fence, assuming it also *ended* with one. If the model's
    output didn't end in a fence (extra whitespace, no closing fence, etc.)
    that blindly chopped 3 real characters off the end of valid JSON and broke
    parsing -- which then burned all 3 retries on a bug that retrying can
    never fix. This only strips a fence that's actually there.
    """
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = _FENCE_OPEN_RE.sub("", cleaned)
        cleaned = _FENCE_CLOSE_RE.sub("", cleaned)
    return cleaned.strip()


async def extract_chunk_async(chunk_text: str, page_range: str, section: str, semaphore: asyncio.Semaphore, index: int,
                              total: int) -> dict:
    max_retries = 3
    attempt = 0

    async with semaphore:
        print(f"-> Sending Chunk {index}/{total} to Claude (Pages {page_range})...")
        while attempt < max_retries:
            try:
                response = await client.messages.create(
                    model="claude-sonnet-5",
                    max_tokens=8192,
                    system=_SYSTEM_PROMPT,
                    messages=[
                        {"role": "user", "content": f"Pages {page_range}, Section: {section}\n\n{chunk_text}"}
                    ]
                )

                if response.stop_reason == "max_tokens":
                    # The response was cut off mid-JSON. Surface this distinctly
                    # since it usually means the chunk has too many requirements
                    # for one response, not a transient error.
                    print(f"[!] Chunk {index}/{total} response was truncated at max_tokens; JSON may be incomplete.")

                ai_json_response = "".join(
                    block.text for block in response.content if hasattr(block, "text")
                ).strip()

                ai_json_response = _strip_markdown_fence(ai_json_response)

                parsed_data = ChunkExtractionResult.model_validate_json(ai_json_response)

                print(f"<- Success: Chunk {index}/{total} extracted {len(parsed_data.requirements)} requirements.")

                await asyncio.sleep(1)

                return {
                    "status": "success",
                    "data": parsed_data.requirements,
                    "needs_manual_review": False
                }

            except Exception as e:
                attempt += 1
                print(f"[!] API Error on Chunk {index}/{total} (Attempt {attempt}/{max_retries}): {e}")
                await asyncio.sleep(3 * attempt)  # simple backoff: 3s, 6s, 9s

        print(f"[X] Failed to process Chunk {index}/{total} after 3 attempts.")
        return {
            "status": "failed",
            "data": [],
            "needs_manual_review": True,
            "raw_failed_text": chunk_text,
            "page_range": page_range,
            "section": section
        }


async def extract_all_chunks_parallel(chunks: List[dict], max_concurrent_calls: int = 3) -> List[dict]:
    semaphore = asyncio.Semaphore(max_concurrent_calls)
    total_chunks = len(chunks)

    print(f"\n==================================================")
    print(f"STARTING PARALLEL EXTRACTION FOR {total_chunks} CHUNKS")
    print(f"==================================================\n")

    tasks = [
        extract_chunk_async(
            chunk_text=chunk["text"],
            page_range=chunk["page_range"],
            section=chunk["section"],
            semaphore=semaphore,
            index=i + 1,
            total=total_chunks
        ) for i, chunk in enumerate(chunks)
    ]
    return await asyncio.gather(*tasks)


def generate_unique_hash(requirement: ExtractedRequirement) -> str:
    clause = requirement.reference_number
    unique_string = f"{clause}_{requirement.clause_requirement_description}".lower().strip()
    return hashlib.md5(unique_string.encode()).hexdigest()


def assemble_master_table(all_chunk_results: List[dict]) -> dict:
    master_table = []
    seen_hashes = set()
    chunks_needing_review = []

    for result in all_chunk_results:
        if result["needs_manual_review"]:
            chunks_needing_review.append(result)
            continue

        for req in result["data"]:
            req_hash = generate_unique_hash(req)
            if req_hash not in seen_hashes:
                seen_hashes.add(req_hash)
                master_table.append(req.model_dump())

    print(f"\nExtraction Complete! {len(master_table)} unique requirements mapped to Excel.")
    return {
        "master_table": master_table,
        "total_unique_requirements": len(master_table),
        "manual_review_flags": len(chunks_needing_review),
        "review_data": chunks_needing_review
    }