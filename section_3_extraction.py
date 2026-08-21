import os
import re
import json
import hashlib
import asyncio
from typing import List
from pydantic import BaseModel
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

_api_key = os.getenv("OPENAI_API_KEY")
_base_url = os.getenv("OPENAI_BASE_URL")
_model_name = os.getenv("OPENAI_MODEL")

if not _api_key:
    raise RuntimeError("OPENAI_API_KEY is not set in your .env file.")

if not _model_name:
    raise RuntimeError("OPENAI_MODEL is not set in your .env file.")

_headers = {
    "User-Agent": "claude-cli/1.0.60 (external, cli)"
}

client = OpenAI(api_key=_api_key, base_url=_base_url, default_headers=_headers) if _base_url else OpenAI(
    api_key=_api_key, default_headers=_headers)


class ExtractedRequirement(BaseModel):
    page: str
    section_name: str
    responsibility: str
    reference_number: str
    clause_requirement_description: str
    mandatory: str
    evaluation_impact: str
    evidence_document_required: str


class ChunkExtractionResult(BaseModel):
    requirements: List[ExtractedRequirement]


_SCHEMA_STRING = json.dumps(ChunkExtractionResult.model_json_schema())

_SYSTEM_PROMPT = (
    "System Role: Act as a STRICT Deliverables and Artifacts Extractor. "
    "Your ONLY job is to find concrete documents, files, forms, certificates, profiles, and plans that a vendor MUST submit.\n\n"
    "CRITICAL TARGETS:\n"
    "1. Proposal Submission Documents (e.g., Company profile, CVs, Financial statements, NTN certificates, Work plans).\n"
    "2. Mandatory Compliance Forms (e.g., Form ELI-1.1, Code of Conduct, Beneficial Ownership Disclosure, Proposal-Securing Declaration).\n"
    "3. Post-Award Project Deliverables (e.g., Workflow mapping, UAT plans, Gap analysis, UI/UX designs, Architecture blueprints).\n\n"
    "CRITICAL RULES:\n"
    "1. DO NOT extract software features (e.g., 'system shall generate timetables', 'secure login').\n"
    "2. DO NOT extract background text, Executive Summaries, Objectives, or Disclaimers.\n"
    "3. If a chunk contains NO concrete document submissions, return an EMPTY requirements array: []\n\n"
    "LENGTH CONSTRAINTS & FORMATTING:\n"
    "- Fields 'page', 'responsibility', 'reference_number', 'mandatory', 'evaluation_impact' MUST be 3 to 4 words maximum.\n"
    "- 'section_name' MUST be the exact formal Section Header from the document (Do NOT summarize, NO word limit).\n"
    "- 'clause_requirement_description' MUST be a single, short one-liner sentence.\n"
    "- 'evidence_document_required' MUST capture the EXACT Form ID or Document Name if specified (e.g., 'Form FIN-3.3', 'Beneficial Ownership Form', 'Code of Conduct'). Maximum 6 words.\n\n"
    "Data Output Format:\n"
    f"Format the output as strictly valid JSON matching this schema: {_SCHEMA_STRING}. Map fields as follows:\n"
    "- 'page': e.g., 'Page 12' (Max 3 words).\n"
    "- 'section_name': MUST be the exact Section name provided in the user prompt (e.g., 'Section III - Evaluation and Qualification Criteria').\n"
    "- 'responsibility': e.g., 'Vendor' (Max 3 words).\n"
    "- 'reference_number': MUST extract the exact section number, e.g., 'Section 14.D', 'ITP 11.2' (Max 3 words).\n"
    "- 'clause_requirement_description': One-liner explaining WHY the document is needed.\n"
    "- 'mandatory': 'Yes' or 'No'.\n"
    "- 'evaluation_impact': e.g., 'Eligibility', 'Technical Score' (Max 3 words).\n"
    "- 'evidence_document_required': Exact name of the file/form, e.g., 'Beneficial Ownership Disclosure Form', 'Form ELI-1.1' (Max 6 words).\n\n"
    "Output ONLY raw JSON. Do not include markdown code blocks."
)

_FENCE_OPEN_RE = re.compile(r"^```(?:json)?\s*\n?")
_FENCE_CLOSE_RE = re.compile(r"\n?```\s*$")


def _strip_markdown_fence(raw: str) -> str:
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = _FENCE_OPEN_RE.sub("", cleaned)
        cleaned = _FENCE_CLOSE_RE.sub("", cleaned)
    return cleaned.strip()


async def extract_chunk_async(chunk_text: str, page_range: str, section: str, semaphore: asyncio.Semaphore, index: int,
                              total: int) -> dict:
    max_retries = 2
    attempt = 0

    async with semaphore:
        print(f"-> Sending Chunk {index}/{total} to Proxy Model (Pages {page_range})...")
        while attempt < max_retries:
            try:
                response = await asyncio.to_thread(
                    client.chat.completions.create,
                    model=_model_name,
                    max_tokens=2048,
                    messages=[
                        {"role": "system", "content": _SYSTEM_PROMPT},
                        {"role": "user", "content": f"Pages {page_range}, Section: {section}\n\n{chunk_text}"}
                    ]
                )

                raw_content = response.choices[0].message.content.strip()
                cleaned_json = _strip_markdown_fence(raw_content)

                if not cleaned_json.strip().endswith("}") and not cleaned_json.strip().endswith("]"):
                    last_valid_brace = cleaned_json.rfind("}")
                    if last_valid_brace != -1:
                        cleaned_json = cleaned_json[:last_valid_brace + 1] + "]}"
                    else:
                        cleaned_json = '{"requirements": []}'

                parsed_data = ChunkExtractionResult.model_validate_json(cleaned_json)

                # Force the section name to match the structural section passed from the parser
                for req in parsed_data.requirements:
                    if section and section.strip() != "":
                        req.section_name = section.strip()

                print(f"<- Success: Chunk {index}/{total} extracted {len(parsed_data.requirements)} document items.")
                await asyncio.sleep(0.1)

                return {
                    "status": "success",
                    "data": parsed_data.requirements,
                    "needs_manual_review": False
                }

            except Exception as e:
                attempt += 1
                print(f"[!] API Error on Chunk {index}/{total} (Attempt {attempt}/{max_retries}): {e}")
                await asyncio.sleep(0.5)

        print(f"[X] Failed to process Chunk {index}/{total} after {max_retries} attempts.")
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
    print(f"STARTING STRICT DOCUMENT EXTRACTION FOR {total_chunks} CHUNKS")
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
    unique_string = f"{requirement.reference_number}_{requirement.evidence_document_required}".lower().strip()
    return hashlib.md5(unique_string.encode()).hexdigest()


def assemble_master_table(all_chunk_results: List[dict]) -> dict:
    master_table = []
    seen_hashes = set()
    chunks_needing_review = []

    valid_doc_keywords = [
        "document", "manual", "cv", "resume", "profile", "report", "plan",
        "certificate", "statement", "diagram", "matrix", "quotation", "proposal",
        "blueprint", "framework", "design", "timeline", "tutorial", "form",
        "declaration", "guarantee", "code of conduct", "ownership", "msip", "strategy"
    ]

    invalid_section_keywords = ["executive", "intro", "objective", "background", "scope", "disclaimer"]
    invalid_desc_keywords = ["system must", "system shall", "auto-generate", "software", "ui", "interface"]

    for result in all_chunk_results:
        if result.get("needs_manual_review"):
            chunks_needing_review.append(result)

            master_table.append({
                "page": result.get("page_range", "N/A")[:15],
                "section_name": result.get("section", "MANUAL REVIEW REQUIRED"),
                "responsibility": "Review Needed",
                "reference_number": "ERROR",
                "clause_requirement_description": "API failed to process this chunk. Manual review required.",
                "mandatory": "N/A",
                "evaluation_impact": "Failed Chunk",
                "evidence_document_required": "Review Raw Text"
            })
            continue

        for req in result["data"]:
            desc = req.clause_requirement_description.lower()
            evidence = req.evidence_document_required.lower()
            section = req.section_name.lower()

            if any(kw in section for kw in invalid_section_keywords):
                continue

            if any(kw in desc for kw in invalid_desc_keywords):
                continue

            is_valid_document = any(kw in desc or kw in evidence for kw in valid_doc_keywords)

            if is_valid_document:
                req_hash = generate_unique_hash(req)
                if req_hash not in seen_hashes:
                    seen_hashes.add(req_hash)
                    master_table.append(req.model_dump())

    def get_page_number(row):
        matches = re.findall(r'\d+', row.get("page", ""))
        return int(matches[0]) if matches else 999999

    master_table.sort(key=get_page_number)

    print(f"\nExtraction Complete! {len(master_table)} STRICT document requirements mapped to Excel.")
    return {
        "master_table": master_table,
        "total_unique_requirements": len(master_table),
        "manual_review_flags": len(chunks_needing_review),
        "review_data": chunks_needing_review
    }