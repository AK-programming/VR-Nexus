"""
Records one LlmUsageEvent row per Anthropic API call.

Called from every site that actually talks to Claude:
  - services/extraction.py: extract_chunk() (per tender chunk) and
    extract_tender_metadata() (once per tender)
  - services/library/llm.py: complete() (both library auto-tagging and the
    Evidence Library's grounded Ask go through this one function, so the
    caller tells it which via `purpose`)

Deliberately never raises. A broken usage write must not take down the
actual extraction/tagging/Ask call it is trying to measure - the same rule
llm.py's own docstring states for the LLM call itself ("an enhancement, not
a dependency"). Every call site wraps its real work in try/except already;
this module holds itself to the same standard so a caller never has to
special-case it.
"""
import logging
import uuid
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.llm_usage_event import LlmUsageEvent
from app.models.enums import UsagePurpose

logger = logging.getLogger(__name__)

_settings = get_settings()


def estimate_cost_usd(
    model: str, input_tokens: int, output_tokens: int, db: Optional[Session] = None
) -> float:
    """Looks up `model` in the effective pricing table and prices the call.

    "Effective" means app_settings' get_effective_pricing_table() - config.py's
    static ANTHROPIC_PRICING_USD_PER_MILLION_TOKENS with any admin-set
    overrides (Settings -> Pricing -> Refresh or manual edit) merged on top.
    Pass `db` when one is already open (record_usage always has one); without
    it, the effective-table lookup opens and closes its own short-lived
    session, so a caller who only has model/token counts on hand can still
    get correctly-priced results.

    Returns 0.0 (and logs a warning, once per distinct unknown model per
    process) for a model id the pricing table does not know - this is what
    happens the day someone bumps ANTHROPIC_MODEL / ANTHROPIC_EXTRACTION_MODEL
    to a version not yet priced anywhere (config.py or the DB override), and
    it is deliberately a silent-to-the-caller $0 rather than a raised
    exception: an unpriced call still happened and still used real tokens, so
    the row is still worth recording with accurate token counts even while
    its cost column is wrong.
    """
    from app.services.app_settings import get_effective_pricing_table

    rates = get_effective_pricing_table(db).get(model)
    if rates is None:
        logger.warning(
            "No pricing entry for model '%s' in ANTHROPIC_PRICING_USD_PER_MILLION_TOKENS; "
            "recording this call's usage at $0.00. Add an entry to core/config.py.",
            model,
        )
        return 0.0

    return (input_tokens / 1_000_000) * rates["input"] + (output_tokens / 1_000_000) * rates["output"]


def record_usage(
    db: Session,
    *,
    model: str,
    purpose: UsagePurpose,
    input_tokens: int,
    output_tokens: int,
    latency_ms: int,
    tender_id=None,
    document_id=None,
    user_id=None,
) -> None:
    """Writes one LlmUsageEvent row and commits it.

    Commits on its own (not left for the caller's next commit) so a usage row
    is durable the moment the call it describes finished, independent of
    whatever the caller does next - extract_chunk()'s result, for instance,
    is consumed by run_extraction() several lines later and might itself
    raise before its own next commit.

    Every argument after `db` is keyword-only on purpose: `record_usage(db,
    model, purpose, 100, 50, ...)` reads as an easy-to-transpose token count,
    while the keyword form cannot be.
    """
    try:
        event = LlmUsageEvent(
            model=model,
            purpose=purpose,
            input_tokens=max(0, int(input_tokens)),
            output_tokens=max(0, int(output_tokens)),
            estimated_cost_usd=estimate_cost_usd(model, input_tokens, output_tokens, db=db),
            latency_ms=max(0, int(latency_ms)),
            tender_id=tender_id,
            document_id=document_id,
            user_id=user_id,
        )
        db.add(event)
        db.commit()
    except Exception:
        # Never let a usage-tracking failure surface to a caller that just
        # finished real work (an extraction chunk, a tagging call, an Ask
        # answer). Roll back so a half-written event row cannot poison the
        # caller's own next commit on this same session.
        #
        # Every field that would have gone into the row is logged here too,
        # not just model/purpose - the most common way this branch is ever
        # hit is the llm_usage_events table not existing yet (the Alembic
        # migration was never applied), which means every single call
        # since deploy has been failing here silently and the API Usage
        # page has been showing nothing despite real tokens being spent on
        # every one of them. Without the full numbers in the log, that gap
        # is unrecoverable once it's noticed; with them, `grep "Failed to
        # record LLM usage"` on this process's log at least tells you how
        # much was actually spent while the table was missing.
        logger.exception(
            "Failed to record LLM usage - continuing without it. "
            "model=%s purpose=%s input_tokens=%s output_tokens=%s latency_ms=%s "
            "tender_id=%s document_id=%s user_id=%s. If this keeps happening, "
            "check that `alembic upgrade head` has been run against this database "
            "(the llm_usage_events table may not exist yet).",
            model, purpose, input_tokens, output_tokens, latency_ms,
            tender_id, document_id, user_id,
        )
        try:
            db.rollback()
        except Exception:
            pass


def compute_tender_usage(db: Session, tender_id: uuid.UUID):
    """What one tender's own Anthropic API calls cost and how long they took:
    every per-chunk extraction call plus the one tender-metadata call, both
    recorded via record_usage() with tender_id=this tender.

    Shared by GET /api/tenders/{id}/usage (the Tender Review page's badge)
    and the pipeline's ZIP assembly (the api_usage_report.xlsx bundled into
    the download) - one query, so the badge and the downloaded report can
    never disagree about the same tender's numbers.

    Imports TenderUsageOut/UsageByPurpose locally to avoid a service/schema
    import cycle at module load time (schemas/usage.py has no reason to
    import this module, but keeping the import local here removes any risk
    of one forming later).
    """
    from app.schemas.usage import TenderUsageOut, UsageByPurpose

    rows = (
        db.query(
            LlmUsageEvent.purpose,
            func.count(LlmUsageEvent.id),
            func.coalesce(func.sum(LlmUsageEvent.input_tokens), 0),
            func.coalesce(func.sum(LlmUsageEvent.output_tokens), 0),
            func.coalesce(func.sum(LlmUsageEvent.estimated_cost_usd), 0),
            func.coalesce(func.avg(LlmUsageEvent.latency_ms), 0),
        )
        .filter(LlmUsageEvent.tender_id == tender_id)
        .group_by(LlmUsageEvent.purpose)
        .all()
    )

    by_purpose = [
        UsageByPurpose(
            purpose=purpose, calls=n, input_tokens=in_tok, output_tokens=out_tok,
            cost_usd=float(cost), avg_latency_ms=float(avg_lat),
        )
        for purpose, n, in_tok, out_tok, cost, avg_lat in rows
    ]

    total_calls = sum(p.calls for p in by_purpose)
    total_input = sum(p.input_tokens for p in by_purpose)
    total_output = sum(p.output_tokens for p in by_purpose)
    total_cost = sum(p.cost_usd for p in by_purpose)
    total_latency = (
        db.query(func.coalesce(func.sum(LlmUsageEvent.latency_ms), 0))
        .filter(LlmUsageEvent.tender_id == tender_id)
        .scalar()
    )

    return TenderUsageOut(
        tender_id=tender_id,
        total_calls=total_calls,
        input_tokens=total_input,
        output_tokens=total_output,
        total_tokens=total_input + total_output,
        cost_usd=round(total_cost, 6),
        total_latency_ms=total_latency,
        avg_latency_ms=(total_latency / total_calls) if total_calls else 0.0,
        by_purpose=by_purpose,
    )
