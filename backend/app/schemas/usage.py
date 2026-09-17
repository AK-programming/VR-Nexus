"""
Request/response shapes for the API Usage feature: the "API Usage" page
(totals, by-model/by-purpose/by-user breakdowns, a daily chart) and the
per-tender usage badge on the Tender Review page.

Every number here is derived from llm_usage_events - see
app/models/llm_usage_event.py for what one row represents and
app/services/usage_tracking.py for how rows get written. Costs are
estimates from a hand-maintained pricing table (see
Settings.ANTHROPIC_PRICING_USD_PER_MILLION_TOKENS), not a billing source of
truth.

The API Usage page is shared by every signed-in account, not admin-only:
an admin sees everyone's usage, an ordinary user sees only their own (see
api/routes/usage.py's scoping). `UsageScope` says which one actually
happened, so the frontend renders "your usage" vs. "everyone's usage" - and
hides the by-user breakdown, which is meaningless once it has been
filtered down to one person - off what the backend actually enforced
rather than off the viewer's own guess at their role.
"""
import uuid
from datetime import date as date_
from typing import Literal, Optional

from pydantic import BaseModel

from app.models.enums import UsagePurpose

UsageScope = Literal["all", "own"]


class UsageTotals(BaseModel):
    """Headline numbers for the admin Usage page's stat-tile row."""

    total_calls: int
    total_input_tokens: int
    total_output_tokens: int
    total_tokens: int
    total_cost_usd: float
    total_latency_ms: int
    avg_latency_ms: float


class UsageByModel(BaseModel):
    model: str
    calls: int
    input_tokens: int
    output_tokens: int
    cost_usd: float
    avg_latency_ms: float


class UsageByPurpose(BaseModel):
    purpose: UsagePurpose
    calls: int
    input_tokens: int
    output_tokens: int
    cost_usd: float
    avg_latency_ms: float


class UsageByUser(BaseModel):
    """One row per attributed user. A usage event with no user_id (should be
    rare - see LlmUsageEvent's attribution comment) is rolled into a single
    row with user_id=None and user_name="Unattributed" rather than dropped,
    so the by-user total still reconciles with the grand total."""

    user_id: Optional[uuid.UUID] = None
    user_name: str
    calls: int
    input_tokens: int
    output_tokens: int
    cost_usd: float
    avg_latency_ms: float


class UsageSummaryOut(BaseModel):
    """GET /api/usage/summary - everything the Usage page needs apart from
    the daily chart (see UsageTimeseriesOut for that).

    `scope` is "all" for an admin (every user's calls) and "own" for
    everyone else (that caller's calls only) - see api/routes/usage.py.
    `by_user` is always empty when `scope` is "own": a breakdown by user
    is meaningless once the data has already been filtered down to one
    person, so the backend does not bother computing it and the frontend
    does not render that table rather than showing a one-row table of
    just the viewer themselves."""

    scope: UsageScope
    totals: UsageTotals
    by_model: list[UsageByModel]
    by_purpose: list[UsageByPurpose]
    by_user: list[UsageByUser]


class UsageDailyPoint(BaseModel):
    """One point on the Usage page's chart. Two granularities share this
    same shape rather than two schemas, because the frontend charts them
    identically - it is only `time`'s presence that tells it which mode a
    given response is in (see get_usage_timeseries's docstring):

      - Daily-aggregate mode (`time` unset): one point per calendar day in
        the range, `date` labels it, and calls/tokens/cost are that whole
        day's totals.
      - Per-call mode (`time` set): one point per individual API call,
        `date` is still that call's calendar day but `time` is its exact
        UTC timestamp (what the chart actually plots against), and
        calls/tokens/cost are that ONE call's own numbers, not a running
        total - see this module's usage.py docstring for why not
        cumulative.
    """

    date: date_
    time: Optional[str] = None
    calls: int
    input_tokens: int
    output_tokens: int
    cost_usd: float


class UsageTimeseriesOut(BaseModel):
    """GET /api/usage/timeseries - one point per calendar day (UTC), for
    the Usage page's daily chart. `scope` mirrors UsageSummaryOut's."""

    scope: UsageScope
    points: list[UsageDailyPoint]


class TenderUsageOut(BaseModel):
    """GET /api/tenders/{tender_id}/usage - what THIS tender's own
    extraction run(s) cost, for the per-tender badge on Tender Review.
    Includes tender-metadata calls (one per tender) alongside the
    per-chunk extraction calls (many per tender), since both are billed
    against the same tender."""

    tender_id: uuid.UUID
    total_calls: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cost_usd: float
    total_latency_ms: int
    avg_latency_ms: float
    by_purpose: list[UsageByPurpose]
