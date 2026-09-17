"""
Task 3.1 - Requirement Extraction (LLM-based)
Linked requirement: TN-EXT-01

Same core approach as the source module — parallel per-chunk LLM calls, retry
with backoff, dedup by clause+description hash — but wired into the real
pipeline: reads actual TenderChunk rows instead of an in-memory list, writes
actual Requirement rows instead of returning a JSON blob, and publishes real
progress (requirements_extracted ticking up per chunk, live).

Uses Claude through Anthropic's OpenAI-compatible endpoint by default, the
SAME client-building approach as the Evidence Library's LLM
(app/services/library/llm.py). An admin can point the "extraction" task at
OpenAI or Gemini instead from Settings (both also publish an OpenAI-compatible
endpoint - see app/services/app_settings.py's PROVIDERS); everything below
describes the Anthropic-only .env defaults this app ships with. Configure it
in .env:

    ANTHROPIC_API_KEY=<your Claude API key>
    ANTHROPIC_BASE_URL=https://api.anthropic.com/v1/
    ANTHROPIC_EXTRACTION_MODEL=claude-haiku-4-5-20251001

Deliberately NOT ANTHROPIC_MODEL (that one stays the heavier "reasoning" model
for the library's grounded Ask). Extraction is a high-volume call, one per
~2000-token chunk, so 100+ per tender, and a cheap fast model handles it at
roughly half the per-token cost. If extraction quality regresses, point
ANTHROPIC_EXTRACTION_MODEL at ANTHROPIC_MODEL's value in .env to compare.

Note that this is no longer a no-judgment call. It used to be: the prompt asked
for the tender's own wording copied into fixed fields. That was measured against
two human-authored trackers for tenders this pipeline had also processed, and it
produced roughly 12x too many rows (5.5 and 7.8 per page against the analysts'
0.5), with output tokens almost equal to input tokens because the model was
retyping the document as JSON. `_SYSTEM_PROMPT` and `ExtractedRequirement` now
ask for a filtered, rewritten bid action list instead, which IS a judgment call
- so if the cheap model ever proves unable to apply the INCLUDE test below
reliably, that, not throughput, is the reason to move extraction up a tier.

The model asks for strict JSON; `_coerce_json` tolerates a stray sentence or a
markdown fence around it before validation, and a chunk that fails all three
attempts is logged and counted rather than taking the run down.
"""
import asyncio
import hashlib
import json
import logging
import re
import time
import uuid
from collections import Counter
from decimal import Decimal
from typing import Literal, Optional

from openai import AsyncOpenAI
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.enums import EvaluationImpact, TenderStatus, UsagePurpose
from app.models.requirement import Requirement
from app.models.tender import Tender
from app.models.tender_chunk import TenderChunk
from app.services.progress import publish_progress
from app.services.section_triage import load_outcome as load_triage_outcome
from app.services.usage_tracking import record_usage

logger = logging.getLogger(__name__)

settings = get_settings()
#: One cached client per provider ("anthropic", "openai", "gemini" - see
#: app/services/app_settings.py's PROVIDERS), since an admin can now point
#: extraction at any of the three. Was a single `_client`/`_client_generation`
#: pair back when this app only ever called Anthropic; a dict keyed by
#: provider is the same idea, just one slot per provider instead of one.
_clients: dict[str, AsyncOpenAI] = {}
#: The app_settings key_generation() _clients was built from. A mismatch
#: means an admin changed SOME provider's API key since this process last
#: built its clients - see _get_client() below and app/services/app_settings.py's
#: module docstring for why this exists instead of reading settings.*_API_KEY
#: directly. One counter for every provider (not one each): simpler, and a
#: key change is rare enough that clearing every cached client on any one of
#: them changing costs nothing worth optimising away.
_client_generation: int = -1


def extraction_model(db: Optional[Session] = None) -> dict[str, str]:
    """The `{"provider", "model"}` extraction should call right now.

    Public because the pipeline's Stage A triage call (app/tasks/
    tender_pipeline.py) has to run on the same provider+model as the
    extraction it is deciding the scope of. Mirrors the public
    `extraction_model()` in app/services/library/llm.py.
    Deliberately the "extraction" task, not "reasoning": extraction is
    high-volume mechanical work (see module docstring), so it runs on a
    cheaper model than the app's reasoning calls do.

    Resolved through app_settings so an admin's Settings-screen choice
    (backend/app/services/app_settings.py's MODEL_TASKS) takes effect
    immediately, falling back to config.py's ANTHROPIC_EXTRACTION_MODEL
    (provider "anthropic") when no override is set. Callers that run many
    chunks in one pass (run_extraction) resolve this once per run rather
    than once per chunk, both so the DB isn't hit per chunk and so one run
    stays on one provider+model even if the admin changes the setting while
    it's mid-flight.
    """
    from app.services.app_settings import get_effective_model

    return get_effective_model("extraction", db)


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


def _get_client(provider: str = "anthropic") -> AsyncOpenAI:
    """Builds (or rebuilds) the shared client for one provider.

    Rebuilds every cached provider client whenever app_settings'
    key_generation() has moved on since they were built - i.e. whenever an
    admin has saved a new API key for ANY provider via Settings since this
    process last needed a client - rather than only ever building once per
    process. Without this, a key rotation would only take effect after
    every worker was restarted, which is exactly the "key expired/compromised,
    now what" situation Settings exists to avoid. A provider used for the
    first time (an admin just switched a task onto it) is simply a cache
    miss here, same as any other - no separate "first use" path needed.
    """
    global _clients, _client_generation
    from app.services.app_settings import (
        PROVIDER_LABELS,
        get_effective_api_key,
        key_generation,
        provider_base_url,
    )

    generation = key_generation()
    if generation != _client_generation:
        _clients = {}
        _client_generation = generation

    if provider not in _clients:
        api_key = get_effective_api_key(provider)
        if not api_key:
            raise RuntimeError(
                f"No {PROVIDER_LABELS.get(provider, provider)} API key is configured. "
                "Set one in Settings (admin), or in .env, before running tender extraction."
            )
        _clients[provider] = AsyncOpenAI(
            api_key=api_key,
            base_url=provider_base_url(provider),
            # A hard per-request ceiling so one slow/hung call cannot stall the
            # whole run: the SDK default is 600s, which is how a single chunk
            # can freeze extraction for ~10 minutes. Our own retry loop (below)
            # handles transient failures, so the SDK's internal retries are capped
            # low to avoid compounding backoff on top of ours.
            timeout=60.0,
            max_retries=1,
        )
    return _clients[provider]


#: What a tracker row can say about who owns the action. A closed set, mapped
#: onto whatever responsibility columns this tender's Excel template defines
#: (four department columns for a solo bid, one per partner for a consortium
#: bid) rather than being those columns itself - see the `dpl`/`prime`/`the_t`
#: note in ExtractedRequirement's docstring for why that distinction matters.
OwnerHint = Literal["BD", "Technical", "Finance-Legal", "HR", "Joint"]

#: How binding the item is. Five values, taken from what the two human-authored
#: reference trackers actually use across two real tenders: plain "Yes"/"No",
#: "No - Scoring" (scored, not a gate), "Conditional - If JV" (with the trigger
#: in `condition`), and "Post-award" (a real obligation, but after award, so it
#: must not be mistaken for a submission task).
MandatoryKind = Literal["Yes", "No", "Conditional", "Post-award", "Scoring"]


class ExtractedRequirement(BaseModel):
    """One row of a bid action tracker: a thing the bid team must DO.

    Deliberately NOT "the clause, verbatim". The earlier version of this model
    asked for the tender's own wording in every field and carried an open
    `extra_fields: dict[str, str]` for anything else the document labelled. Both
    choices were measured against two human-authored trackers for tenders we
    also ran through this pipeline, and both were wrong:

      * Verbatim wording made output tokens match input tokens almost 1:1
        (137k out for 150k in on a 125-page RFP) because the model was, in
        effect, retyping the document as JSON. It also produced declarative
        clause text where the trackers write assignable actions - "Must be
        registered with relevant tax authorities. Must have NTN and STRN and
        PST registration." against the human's "Provide NTN and STRN/PST
        registrations."
      * Open `extra_fields` was capped per requirement but not globally, and the
        workbook writer promoted every distinct key to a column. One arbitration
        clause was enough to add a permanent "Appointing Authority for
        Arbitrator" column. That tender's sheet ended up 92 columns wide, 58 of
        them filled in exactly one row out of 687.

    So the schema is closed. Anything the fixed fields do not model belongs in
    `remarks` as prose, which costs one cell instead of one column.

    `dpl`/`prime`/`the_t` are gone for the same reason: they were one specific
    consortium's partner names (DPL, PRIME, The Tulepaak) hardcoded as fields,
    and were 100% empty on every tender where DPL bid alone. `owner_hint`
    replaces them with a closed set the model can actually reason about.

    Fields still default to empty, and a value the tender does not state stays
    empty rather than being guessed or filled with "N/A".
    """

    #: Every page this obligation appears on. A list because tenders restate the
    #: same requirement (SMEDA lists its eligibility criteria twice, on pages
    #: 21-22 and again on 81), and the human trackers answer that with ONE row
    #: citing both - "18 / 78 (PDF 21 / 81)". The prompt asks for the merge
    #: within a chunk; cross-chunk merging is the dedup pass's job.
    pages: list[str] = []
    section: str = ""
    reference: str = ""
    #: The imperative. "Provide NTN and STRN/PST registrations." Capped because
    #: a tracker cell nobody can read at a glance defeats the point.
    action: str
    mandatory: MandatoryKind = "Yes"
    #: What makes a Conditional item apply ("If bidding as a JV", "If invited to
    #: present"). Empty for every other `mandatory` value.
    condition: str = ""
    evaluation_impact: str = ""
    #: The MAXIMUM marks the criterion can earn, never a sum of scoring bands.
    #: Bands ("more than 15 years = 10, 10-15 = 5, 7-10 = 1") are alternatives
    #: for one criterion, and summing them is how a 100-mark tender was reported
    #: as 222 marks available.
    marks_max: Optional[float] = None
    #: An explicit decision, not an inferred blank. Previously this was derived
    #: from "did the model fill the evidence field", which silently excluded 471
    #: of 687 requirements from evidence matching and then labelled them
    #: "Not required" in the workbook - reporting a data gap as a judgement.
    evidence_required: bool
    evidence_documents: list[str] = []
    owner_hint: OwnerHint = "BD"
    remarks: str = ""

    @field_validator("action", "reference", "section", "condition", "evaluation_impact", "remarks")
    @classmethod
    def _trim(cls, value: str) -> str:
        return (value or "").strip()

    @field_validator("pages", "evidence_documents")
    @classmethod
    def _bound_list(cls, value: list[str]) -> list[str]:
        """Keep the open-ended lists short and clean. Bounded rather than
        trusted: a malformed response should not be able to write a hundred
        page references into one cell."""
        out: list[str] = []
        for item in value or []:
            text = str(item).strip()
            if text and text not in out:
                out.append(text[:120])
            if len(out) >= 12:
                break
        return out


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
    #: The total technical marks the tender says are on offer, and the score
    #: needed to pass. Both exist to CHECK the extracted per-requirement marks
    #: rather than to display: one shipped tracker reported "Marks available:
    #: 222" for a tender whose own evaluation section says 100, because the
    #: scoring table appears twice and its experience bands were summed as
    #: though additive. A stated total makes that detectable instead of
    #: plausible - see _marks_reconciliation in app/tasks/tender_pipeline.py.
    technical_marks_total: str = "N/A"
    passing_technical_score: str = "N/A"


def _compact_schema() -> str:
    """The JSON schema with the prose stripped out.

    `model_json_schema()` emits every `title` and every field docstring as a
    `description`. That is ~800 tokens, and it is sent on EVERY chunk call (88
    of them on a 125-page tender), so it is not free: at $1/Mtok input the
    descriptions alone cost more over one tender than the whole output does.
    They are also redundant, because _SYSTEM_PROMPT below explains each field in
    prose already. Types and enum constraints are what actually steer the model,
    so those are all that is kept.
    """
    schema = ChunkExtractionResult.model_json_schema()

    def strip(node):
        if isinstance(node, dict):
            return {k: strip(v) for k, v in node.items() if k not in ("title", "description")}
        if isinstance(node, list):
            return [strip(v) for v in node]
        return node

    return json.dumps(strip(schema), separators=(",", ":"))


_SCHEMA_STRING = _compact_schema()

#: The extraction prompt.
#:
#: Rewritten against two human-authored trackers for tenders this pipeline had
#: also processed, which is the only reason the rules below are specific rather
#: than aspirational. What the comparison showed:
#:
#:   * Both analysts, independently, on a 125-page and a 528-page tender,
#:     produced ~0.5 rows per page (57 and 266 rows). This pipeline produced
#:     5.5 and 7.8 rows per page. Hence the explicit density expectation below -
#:     the model has no sense of scale unless told, and "extract every
#:     requirement and obligation" (the previous first line) invites everything.
#:   * 43.5% of what we emitted came from post-award contract clauses (GCC/SCC,
#:     arbitration, force majeure, the client's own payment obligations) and 5%
#:     from table-of-contents lines. Neither human tracker contains a single row
#:     from those sections. Hence the exclusion list, which is not a style
#:     preference but the actual scope rule both analysts applied.
#:   * The analysts write assignable actions, not clause text. Hence the
#:     imperative rule and its worked example.
#:
#: The INCLUDE test is phrased as a single question on purpose. A list of
#: things to include invites pattern-matching on vocabulary ("shall", "must");
#: one question forces the model to reason about who has to act and when.
_SYSTEM_PROMPT = (
    "You build a BID ACTION TRACKER: the list of things a bid team must DO to submit "
    "this bid. You are not summarising the document or cataloguing its clauses.\n"
    "\n"
    "INCLUDE an item only if it passes this test: does the BIDDER have to do, submit, "
    "sign, prove or decide something before the submission deadline, OR does it carry "
    "evaluation marks or a pass/fail gate?\n"
    "\n"
    "EXCLUDE always: post-award contract terms (general/special conditions, payment "
    "schedules, arbitration, disputes, force majeure, termination, liabilities, "
    "indemnities, insurance, governing law, contract appendices); obligations of the "
    "procuring entity rather than the bidder; definitions, tables of contents, section "
    "indexes, eligible-country lists, policy statements, project background; anything "
    "that only describes the work without asking the bidder to supply, sign, prove or "
    "decide something. An item can be a real contractual obligation and still be out of "
    "scope: if it does not change what the bid team does before the deadline, leave it "
    "out.\n"
    "\n"
    "DENSITY: a 100-page RFP yields 40-70 items TOTAL. More than one item per page means "
    "you are including things that fail the test. Returning {\"requirements\": []} is the "
    "correct answer for contract conditions, annex boilerplate and narrative background.\n"
    "\n"
    "WRITE each action as an imperative the team can be assigned, keeping every "
    "threshold, year, amount, count and date:\n"
    "  GOOD: \"Provide NTN and STRN/PST registrations.\"\n"
    "  BAD:  \"Must be registered with relevant tax authorities. Must have NTN and "
    "STRN and PST registration.\"\n"
    "\n"
    "ONE ITEM PER OBLIGATION. If this text states the same requirement twice, return it "
    "ONCE listing both pages. Never split one obligation into a row per sentence.\n"
    "\n"
    "BLANK FORMS AND TEMPLATES are ONE item each: \"Complete and sign Form TECH-1 "
    "(Technical Proposal Submission Form), including bidder details, validity and "
    "authorised signatory.\" Never emit one item per field, per table column or per "
    "checklist line. This covers proposal forms, annexures, checklists, CV templates, "
    "price schedules and undertakings. Name the form in the action and summarise what "
    "goes in it.\n"
    "\n"
    "NAMED KEY EXPERT ROLES get one item each (Team Leader, M&E Specialist, and so on), "
    "carrying that role's required qualification and years of experience. Put the "
    "scoring bands in remarks. Do not replace the role with its bands.\n"
    "\n"
    "SCOPE, DELIVERABLES, TIMELINE AND TRAINING sections describe what the bidder must "
    "deliver, so convert them into the planning action the bid team owes now: \"Plan the "
    "7-month engagement: 4 months deployment plus 3 months post-implementation support.\" "
    "One item per distinct deliverable group or plan, not one per descriptive sentence, "
    "and not a row for the background narrative around them.\n"
    "\n"
    "FIELDS\n"
    "pages: as written, e.g. [\"21-22\", \"81\"].\n"
    "reference: the tender's own citation, e.g. \"BDS Clause 3 / ITB 4.1\", "
    "\"Eligibility 2\", \"TECH-6 - CVs\". Build one from whatever numbering the tender "
    "uses; empty only if genuinely unnumbered.\n"
    "mandatory: \"Yes\" required submission or gate | \"Scoring\" earns marks, not a gate "
    "| \"Conditional\" applies only sometimes, trigger goes in `condition` e.g. \"If "
    "bidding as a JV\" | \"Post-award\" binding only after award, kept so the team can "
    "plan for it | \"No\".\n"
    "evaluation_impact: e.g. \"Pass/Fail\", \"Technical Score\", \"Financial / "
    "Pass-Fail\", \"Compliance\".\n"
    "marks_max: the MAXIMUM marks this criterion can earn, else null. Scoring BANDS "
    "(\">15 years = 10, 10-15 = 5, 7-10 = 1\") are alternatives for ONE criterion: put "
    "the highest in marks_max, put the bands in `remarks`. NEVER sum bands and never "
    "emit one item per band.\n"
    "evidence_required: true if the bidder must attach a document, certificate, form or "
    "CV to prove this. Decide explicitly for every item.\n"
    "evidence_documents: named as deliverables, e.g. [\"NTN certificate\"].\n"
    "owner_hint: \"BD\" forms, assembly, submission | \"Technical\" methodology, work "
    "plan, solution | \"Finance-Legal\" pricing, tax, guarantees, affidavits, "
    "registrations | \"HR\" CVs, key experts, staffing | \"Joint\".\n"
    "remarks: what the team should know that no other field carries - scoring bands, "
    "thresholds, a risk, an ambiguity, a dependency. Prose, not a label.\n"
    "\n"
    f"Match this JSON schema exactly: {_SCHEMA_STRING}\n"
    "Return ONLY a single JSON object, no markdown."
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

    Claude, through Anthropic's OpenAI-compatible endpoint, usually returns
    clean JSON but occasionally frames the object with a sentence — either
    before it ("Here is the JSON:") or, just as often, AFTER the closing
    brace (e.g. "... below this threshold for inclusion."). Strip a markdown
    fence, then always take the widest {...} span rather than only doing that
    when the text doesn't already start with "{" — a response that starts
    clean but trails a sentence used to be returned as-is and fail
    `model_validate_json` with "Invalid JSON: trailing characters", which took
    the whole chunk down instead of just costing an extra `find`/`rfind`.
    Validation downstream is still the real gate — this only improves the
    odds it succeeds first try."""
    cleaned = _strip_markdown_fence(raw)
    if cleaned.startswith("["):
        end = cleaned.rfind("]")
        return cleaned[: end + 1] if end != -1 else cleaned
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        return cleaned[start : end + 1]
    return cleaned


def _page_label(pages: list[str]) -> Optional[str]:
    """Render the page list the way the human trackers do: the pages joined with
    " / " ("21 / 81"), which reads as "this same obligation is stated in both
    places" rather than as a range."""
    cleaned = [p.strip() for p in (pages or []) if p and p.strip()]
    return " / ".join(cleaned)[:50] if cleaned else None


def _parse_page_number(pages: list[str]) -> Optional[int]:
    """The first page number found anywhere in the list, for sort order only.
    `page_number` is a single int column; `page_label` keeps the full truth."""
    for page in pages or []:
        match = re.search(r"\d+", page or "")
        if match:
            return int(match.group())
    return None


#: `mandatory` is now a closed set, so the boolean the rest of the pipeline
#: filters on is a lookup rather than prefix-guessing at free text.
#:
#: "Conditional" and "Post-award" deliberately map to None rather than False.
#: Both ARE binding, so calling them not-mandatory would be wrong, and both are
#: outside the "must be in the submission pack" set that True means. None is the
#: honest third answer, and it keeps them out of the mandatory count without
#: asserting they are optional.
_MANDATORY_BOOL: dict[str, Optional[bool]] = {
    "Yes": True,
    "No": False,
    "Scoring": False,
    "Conditional": None,
    "Post-award": None,
}


#: Requirement.mandatory_raw is a VARCHAR(100) column. `condition` below is
#: free text from the model with no length cap of its own (unlike `pages`/
#: `evidence_documents`, which _bound_list caps) - a single verbose
#: "Conditional" trigger from a real tender was long enough that
#: "Conditional - " + it broke 100 characters, and Postgres rejected the
#: whole multi-row INSERT for that batch, not just that one requirement,
#: taking every other requirement in the same commit down with it. Capped
#: here, at the one place that actually needs the DB limit, rather than on
#: `condition` itself (which also feeds `remarks`/display elsewhere and
#: shouldn't be truncated pre-emptively for a column that isn't the bound one).
_MANDATORY_RAW_MAX_LEN = 100


def _mandatory_display(kind: str, condition: str) -> str:
    """The verbatim-style string the tracker column shows, rebuilt from the
    closed enum plus its trigger - "Conditional - If bidding as a JV",
    "No - Scoring" - which is the form both human trackers use. Always
    within `_MANDATORY_RAW_MAX_LEN`, so it never breaks the INSERT."""
    if kind == "Conditional":
        display = f"Conditional - {condition}" if condition else "Conditional"
    elif kind == "Scoring":
        display = "No - Scoring"
    else:
        display = kind
    if len(display) > _MANDATORY_RAW_MAX_LEN:
        display = display[: _MANDATORY_RAW_MAX_LEN - 1].rstrip() + "…"
    return display


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


# _evidence_required, _clean_extras and _parse_marks were removed with the
# schema rewrite. Each existed to salvage a free-text field the model no longer
# returns as free text: evidence_required is now the model's own boolean,
# extra_fields is gone entirely (it was the cause of the 92-column workbook),
# and marks_max arrives as a number. Nothing calls them, and reinstating any of
# them would mean reinstating the guesswork they did.


async def extract_chunk(chunk: TenderChunk, index: int, total: int, model: dict[str, str]) -> dict:
    client = _get_client(model["provider"])
    attempt = 0
    page_range = f"{chunk.page_start}-{chunk.page_end}"

    last_error = ""
    while attempt < MAX_EXTRACTION_RETRIES:
        started = time.monotonic()
        try:
            response = await client.chat.completions.create(
                model=model["model"],
                max_tokens=8192,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": f"Pages {page_range}, Section: {chunk.section}\n\n{chunk.content}",
                    },
                ],
            )
            latency_ms = int((time.monotonic() - started) * 1000)
            raw = (response.choices[0].message.content or "").strip()
            parsed = ChunkExtractionResult.model_validate_json(_coerce_json(raw))
            # response.usage is the OpenAI-compatible shape Anthropic's endpoint
            # returns; None only in the (essentially never seen) case a
            # provider omits it, which usage_tracking below tolerates as 0/0
            # rather than raising.
            usage = response.usage
            return {
                "status": "success",
                "data": parsed.requirements,
                "input_tokens": getattr(usage, "prompt_tokens", 0) or 0,
                "output_tokens": getattr(usage, "completion_tokens", 0) or 0,
                "latency_ms": latency_ms,
            }
        except Exception as exc:
            attempt += 1
            # Kept for the return below: the underlying client/API exception
            # (invalid key, model-not-found, connection refused, rate limit)
            # used to only ever reach a log line no one but an operator with
            # shell access could read. A non-technical admin retrying a failed
            # tender from the UI had nothing to go on but "88 of 88 chunks
            # failed" - so the actual exception text now rides all the way up
            # into ExtractionFailed's message and tender.extraction_warnings.
            last_error = f"{type(exc).__name__}: {exc}"[:300]
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
    return {
        "status": "failed",
        "data": [],
        "chunk_index": chunk.chunk_index,
        # Task: failed-chunk visibility. A silently-dropped chunk used to leave
        # no trace of which pages it covered - the reviewer just saw fewer rows
        # than expected with no way to tell which part of the document they
        # were missing. Carrying page_start/page_end through lets run_extraction
        # below turn "12 chunks failed" into "pages 23-28, 36-40 may be
        # incomplete", which is what actually helps a reviewer decide whether to
        # trust the tracker or retry the run.
        "page_start": chunk.page_start,
        "page_end": chunk.page_end,
        # The last exception seen for this chunk (after all retries), see
        # `last_error` above.
        "error": last_error or "unknown error",
    }


def _summarise_errors(error_counts: "Counter[str]") -> str:
    """Turns the {error string: count} tally from a run into one line naming
    the actual cause, e.g. "APIStatusError: Error code: 401 ... (84 of 88
    chunks)". Every failure mode we've seen in practice - a bad key, a
    retired/misspelled model name, a dropped connection - fails EVERY chunk
    with the same underlying exception, so the most common string alone is
    almost always the whole answer; returns "" if nothing failed."""
    if not error_counts:
        return ""
    message, count = error_counts.most_common(1)[0]
    total_failed = sum(error_counts.values())
    suffix = f" ({count} of {total_failed} failed chunk(s))" if len(error_counts) > 1 else ""
    return f"{message}{suffix}"


def _format_page_ranges(pairs: list[tuple[int, int]]) -> str:
    """Merges a list of (page_start, page_end) spans (unsorted, possibly
    overlapping - adjacent failed chunks often share a page from the sliding
    overlap) into a compact, sorted, human-readable string like
    "8, 11-12, 23-28, 36-40". Empty input returns ""."""
    points: set[int] = set()
    for start, end in pairs:
        if start is None or end is None:
            continue
        lo, hi = (start, end) if start <= end else (end, start)
        points.update(range(lo, hi + 1))
    if not points:
        return ""

    ordered = sorted(points)
    ranges: list[str] = []
    range_start = ordered[0]
    prev = ordered[0]
    for page in ordered[1:]:
        if page == prev + 1:
            prev = page
            continue
        ranges.append(str(range_start) if range_start == prev else f"{range_start}-{prev}")
        range_start = page
        prev = page
    ranges.append(str(range_start) if range_start == prev else f"{range_start}-{prev}")
    return ", ".join(ranges)


#: Leading modal phrasing that carries no meaning for comparison. A tender that
#: restates one obligation rarely restates it word for word - SMEDA's
#: eligibility list appears on pages 21-22 and again on 81, each time with small
#: wording differences - and the old exact-MD5 hash therefore kept every copy,
#: which is how 7 real eligibility requirements became 16 rows carrying two
#: different coverage verdicts. This closes part of that gap; see
#: _normalise_for_hash for exactly which part, and what still needs embeddings.
_MODAL_PREFIX_RE = re.compile(
    r"^(?:the\s+)?(?:bidder|applicant|consultant|firm|proposer)?\s*"
    r"(?:shall|should|must|will|may|is\s+required\s+to|has\s+to|please)\s+"
    r"(?:also\s+)?(?:be\s+|have\s+|provide\s+|submit\s+)?",
    re.IGNORECASE,
)
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


def _normalise_for_hash(text: str) -> str:
    """Reduce an action to its comparable core: lowercase, modal prefix removed,
    everything non-alphanumeric collapsed.

    Measured on the real restatement pairs from a shipped run, this merges the
    ones that differ only by punctuation and trailing stops, e.g.

        "Should be on Active Tax Payer List (ATL) of the Federal Board of
         Revenue (FBR)."
        "Should be on Active Tax Payer List (ATL) of the Federal Board of
         Revenue (FBR)"

    and it merges the same obligation written twice in the imperative form the
    prompt now asks for ("Provide NTN and STRN/PST registrations." against
    "Provide NTN and STRN / PST registrations").

    It does NOT merge pairs that differ by a whole clause - "Must have at least
    5 years of verifiable relevant experience." against the same sentence plus
    "Please provide proof ... as per Applicant Information Form" - nor pairs
    differing by a connecting word ("STRN and PST" against "STRN / PST"). Those
    need embedding similarity, which is the separate near-duplicate merge pass,
    not this. Dropping stopwords here would close some of that gap and would
    also start merging genuinely different obligations, so it is left alone.
    """
    lowered = (text or "").strip().lower()
    stripped = _MODAL_PREFIX_RE.sub("", lowered)
    return _NON_ALNUM_RE.sub(" ", stripped).strip()


def _hash_requirement(req: ExtractedRequirement) -> str:
    """Identity of an obligation, for in-run dedup.

    Keyed on the normalised action ALONE, not on reference + action. The
    reference is exactly what differs between two statements of the same
    requirement (the eligibility list is unnumbered on page 21 and numbered on
    page 81), so including it defeated the dedup it was supposed to drive.
    """
    return hashlib.md5(_normalise_for_hash(req.action).encode()).hexdigest()


async def run_extraction(db: Session, tender: Tender) -> dict:
    """Runs extraction against every TenderChunk for this tender, persists
    deduplicated Requirement rows, and publishes live progress as each
    chunk completes - requirements_extracted genuinely ticks up per chunk,
    not just at the end."""
    all_chunks = (
        db.query(TenderChunk)
        .filter(TenderChunk.tender_id == tender.id)
        .order_by(TenderChunk.chunk_index)
        .all()
    )

    # Stage A triage (app/services/section_triage.py) decided which page spans
    # can contain a bid action. Chunks lying entirely inside an excluded span
    # are not sent: on one reference tender that is ~42% of the document, all of
    # it contract conditions and front matter that no analyst tracker draws a
    # row from. A chunk straddling the boundary is still sent, so nothing is
    # lost at a seam.
    #
    # The chunks themselves are all still stored, so this skips a call, not a
    # page. If triage did not run, failed, or produced an implausible answer,
    # `excludes` is False for everything and this is a no-op.
    triage = load_triage_outcome(tender.section_triage)
    chunks = [c for c in all_chunks if not triage.excludes(c.page_start, c.page_end)]
    skipped = len(all_chunks) - len(chunks)
    total = len(chunks)
    if skipped:
        logger.info(
            "Tender %s: skipping %s of %s chunk(s) in excluded page spans (%s).",
            tender.id, skipped, len(all_chunks), triage.reason,
        )
    # Resolved once, up front, so every chunk in this run uses the same
    # model even if an admin changes the Settings-screen selection while
    # this run is mid-flight - see extraction_model's docstring.
    model = extraction_model(db)
    seen_hashes: set[str] = set()
    created_count = 0
    failed_chunks = 0
    failed_page_spans: list[tuple[int, int]] = []
    # Counts identical (post-retry) error strings across chunks. Almost every
    # real-world failure mode - a bad key, a retired model name, no egress
    # from the worker - fails every chunk with the SAME underlying exception,
    # so "what did 84 of 88 chunks actually say" collapses to one line instead
    # of 84. See _summarise_errors below.
    error_counts: Counter[str] = Counter()

    tender.status = TenderStatus.EXTRACTING
    db.commit()
    start_message = f"Starting extraction across {total} chunks"
    if skipped:
        # Say so on the progress feed. A reviewer watching a 125-page tender go
        # through 46 chunks instead of 88 should be told why, rather than left
        # to wonder whether half the document was lost.
        start_message += f" ({skipped} skipped as post-award or front matter)"
    publish_progress(
        str(tender.id), TenderStatus.EXTRACTING,
        percent=35, message=start_message,
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
    # while one chunk waits on Claude, others are already in flight. Only the LLM
    # calls are parallelised; every DB write below runs back on this one coroutine,
    # so the SQLAlchemy Session stays single-threaded and dedup order is preserved.
    # Results are consumed as they finish (asyncio.as_completed) so the progress
    # bar keeps advancing instead of jumping at the end.
    sem = asyncio.Semaphore(EXTRACTION_CONCURRENCY)

    async def _run_one(idx: int, ch: TenderChunk):
        async with sem:
            return await extract_chunk(ch, idx, total, model)

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
            page_start = result.get("page_start")
            page_end = result.get("page_end")
            if page_start is not None and page_end is not None:
                failed_page_spans.append((page_start, page_end))
            error_counts[result.get("error") or "unknown error"] += 1
        else:
            record_usage(
                db,
                model=model["model"],
                purpose=UsagePurpose.TENDER_EXTRACTION,
                input_tokens=result.get("input_tokens", 0),
                output_tokens=result.get("output_tokens", 0),
                latency_ms=result.get("latency_ms", 0),
                tender_id=tender.id,
                user_id=tender.uploaded_by,
            )
            for req in result["data"]:
                req_hash = _hash_requirement(req)
                if req_hash in seen_hashes:
                    continue
                seen_hashes.add(req_hash)

                db.add(Requirement(
                    tender_id=tender.id,
                    # page_number stays an int for ordering; page_label keeps
                    # every page the obligation was stated on ("21 / 81").
                    page_number=_parse_page_number(req.pages),
                    page_label=_page_label(req.pages),
                    section_name=_clean(req.section),
                    clause_reference=_clean(req.reference),
                    description=req.action,
                    # Normalised for coverage/filtering, display form for the tracker.
                    is_mandatory=_MANDATORY_BOOL.get(req.mandatory),
                    mandatory_raw=_mandatory_display(req.mandatory, req.condition),
                    evaluation_impact=_parse_evaluation_impact(req.evaluation_impact),
                    evaluation_impact_raw=_clean(req.evaluation_impact),
                    # Already a number, and already the criterion maximum rather
                    # than a band - see ExtractedRequirement.marks_max.
                    marks=Decimal(str(req.marks_max)) if req.marks_max is not None else None,
                    responsibility=req.owner_hint,
                    # The evidence flag is the model's own decision now, so a
                    # requirement with no named document is still searched when
                    # it says one is needed.
                    evidence_required=req.evidence_required,
                    evidence_description="; ".join(req.evidence_documents) or None,
                    remarks=_clean(req.remarks),
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

    # Task: failed-chunk visibility. Which pages were behind the failed
    # chunks, not just how many failed - this is what lets a reviewer tell
    # "the tracker is thin because this document genuinely has few
    # requirements" apart from "the tracker is thin because pages 23-28 were
    # dropped". Persisted (not just published over the socket) so it survives
    # a reload and shows up wherever the run is reviewed later: the Excel
    # Summary sheet, summary.json, and the tender detail API.
    failed_page_ranges = _format_page_ranges(failed_page_spans)
    error_summary = _summarise_errors(error_counts)
    tender.extraction_warnings = (
        f"{failed_chunks} of {total} chunk(s) failed extraction after "
        f"{MAX_EXTRACTION_RETRIES} attempts each. Pages that may be incomplete: "
        f"{failed_page_ranges}."
        + (f" Error: {error_summary}" if error_summary else "")
        if failed_page_ranges
        else None
    )
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
            "clauses. Extraction model: "
            f"'{model['provider']}:{model['model']}' (see Settings to change it). "
            f"Actual error from the language model: {_summarise_errors(error_counts) or 'unavailable'}. "
            "Fix the cause above, then retry."
        )

    # Nothing extracted is a failed run, not a finished one. Which of the two
    # reasons it was decides what the operator does next, so they are worded
    # apart rather than sharing one vague sentence.
    if created_count == 0:
        if failed_chunks >= total:
            raise ExtractionFailed(
                f"No requirements could be extracted: all {total} chunk(s) failed to reach "
                f"the language model after {MAX_EXTRACTION_RETRIES} attempts each. This is "
                "almost always configuration — check that provider's API key and the "
                f"extraction model in Settings (currently '{model['provider']}:{model['model']}'; "
                "a provider retires model names over time) and the worker's network access. "
                f"Actual error from the language model: {_summarise_errors(error_counts) or 'unavailable'}. "
                "Fix the cause above, then retry."
            )
        raise ExtractionFailed(
            f"The tender was read ({total} chunk(s), {failed_chunks} failed) but no "
            "requirements were found in it. If it does contain requirements, the PDF may "
            "have no text layer — a scan that OCR could not read comes through as empty pages."
        )

    return {
        "created": created_count,
        "failed_chunks": failed_chunks,
        "failed_page_ranges": failed_page_ranges,
    }


_METADATA_SYSTEM_PROMPT = (
    f"Extract top-level tender metadata matching this exact schema: "
    f"{json.dumps(TenderMetadata.model_json_schema())}. "
    "reference_id is the tender/RFP reference or notice number. "
    "issuing_authority is the organisation issuing the tender. "
    "tender_value is the estimated contract value exactly as written "
    "(keep the currency symbol/code). submission_deadline must be an ISO date "
    "(YYYY-MM-DD) or 'N/A' if no date is stated. "
    "technical_marks_total is the TOTAL technical marks the tender says are "
    "available, as a bare number (e.g. \"100\"), taken from a statement like "
    "\"100 technical marks\" or a scoring table's own total row. "
    "passing_technical_score is the minimum technical score required to "
    "qualify, as a bare number (e.g. \"70\"). For both, use 'N/A' unless the "
    "tender states the figure - do NOT add up a scoring table yourself, since "
    "the whole purpose of these two fields is to be an independent check on "
    "marks totalled elsewhere. "
    "Use 'N/A' for anything not "
    "explicitly present in the text. Return ONLY a single JSON object. Do not wrap output in markdown."
)


async def extract_tender_metadata(
    sample_text: str,
    db: Optional[Session] = None,
    tender_id: Optional[uuid.UUID] = None,
    user_id: Optional[uuid.UUID] = None,
) -> dict:
    """Best-effort, single-shot extraction of the tender's own metadata from
    its opening pages. Returns a dict of raw string values (reference_id,
    issuing_authority, sector, location, tender_value, submission_deadline),
    or {} on any failure. Never raises: metadata is a convenience the user can
    correct via PATCH, not a pipeline dependency, so a failure here must not
    take the run down.

    `db`/`tender_id`/`user_id` are optional purely so this function still
    works standalone (a unit test, a script) with no usage tracking attached;
    the pipeline's own call site (tasks/tender_pipeline.py) always passes all
    three. Usage is recorded only when `db` is given."""
    sample_text = (sample_text or "").strip()
    if not sample_text:
        return {}
    try:
        model = extraction_model(db)
        client = _get_client(model["provider"])
        started = time.monotonic()
        response = await client.chat.completions.create(
            model=model["model"],
            max_tokens=1024,
            messages=[
                {"role": "system", "content": _METADATA_SYSTEM_PROMPT},
                {"role": "user", "content": sample_text[:12000]},
            ],
        )
        latency_ms = int((time.monotonic() - started) * 1000)
        raw = (response.choices[0].message.content or "").strip()
        parsed = TenderMetadata.model_validate_json(_coerce_json(raw))

        if db is not None:
            usage = response.usage
            record_usage(
                db,
                model=model["model"],
                purpose=UsagePurpose.TENDER_METADATA,
                input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
                output_tokens=getattr(usage, "completion_tokens", 0) or 0,
                latency_ms=latency_ms,
                tender_id=tender_id,
                user_id=user_id,
            )

        return parsed.model_dump()
    except Exception as exc:
        logger.warning("Tender metadata extraction failed (non-fatal): %s", exc)
        return {}
