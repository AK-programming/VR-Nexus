"""
The "API Usage" page's backend: totals, a by-model breakdown, a by-purpose
breakdown, a by-user breakdown, and a daily timeseries for the chart -
everything sourced from app/models/llm_usage_event.py's one-row-per-call
table (see that model's docstring for why it is one row per call rather
than a running aggregate).

Client follow-up request: this used to be admin-only. It now works for
every signed-in account, but what a caller sees is scoped by their own
role, not by a query parameter a client could tamper with:

  - An ADMIN gets every user's usage - the original "totals across the
    whole team" view, by-user breakdown included.
  - Anyone else gets ONLY their own usage: every query below is filtered
    to LlmUsageEvent.user_id == current_user.id before anything is
    aggregated, and the by-user breakdown is left empty rather than
    computed for a data set of one person (see UsageSummaryOut's
    docstring). This is enforced here, in the query itself - the frontend
    hiding the by-user table for a non-admin is a presentation choice on
    top of this, not the actual access control.

Both routes only require get_current_user (any authenticated account) -
the same dependency library.py's own routes use - rather than
require_role(UserRole.ADMIN), since an ordinary user is now allowed to
read this endpoint, just scoped to themselves.

The per-tender equivalent (GET /api/tenders/{tender_id}/usage) lives in
api/routes/tenders.py instead, next to that router's other per-tender
routes (report, requirements, matches). That one is not scoped by user at
all - any tender-analysis user can already read any tender's other data
(see tenders.py's _get_tender docstring: this is a shared workspace, not a
multi-tenant product), so a tender's usage follows the same rule.
"""
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.enums import UserRole
from app.models.llm_usage_event import LlmUsageEvent
from app.models.user import User
from app.schemas.usage import (
    UsageByModel,
    UsageByPurpose,
    UsageByUser,
    UsageDailyPoint,
    UsageSummaryOut,
    UsageTimeseriesOut,
    UsageTotals,
)

router = APIRouter(prefix="/api/usage", tags=["usage"])

# get_usage_timeseries's threshold for switching from one point per call to
# one point per day: above this many calls in a single day, per-call points
# would just be a wall of noise (and a bigger response than the chart needs)
# rather than a readable wave - the daily bar the multi-day view already
# uses is the more honest picture at that volume.
_PER_CALL_POINT_CAP = 200


def _date_range_filter(query, start: Optional[date], end: Optional[date]):
    """Shared start/end filter for both routes below. `end` is inclusive -
    a caller asking for "today" expects today's calls included, not
    excluded by a bare `< end` on a timestamp column."""
    if start is not None:
        query = query.filter(LlmUsageEvent.created_at >= datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc))
    if end is not None:
        query = query.filter(
            LlmUsageEvent.created_at < datetime.combine(end + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)
        )
    return query


@router.get("/summary", response_model=UsageSummaryOut)
def get_usage_summary(
    start: Optional[date] = Query(None, description="Inclusive UTC start date filter"),
    end: Optional[date] = Query(None, description="Inclusive UTC end date filter"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UsageSummaryOut:
    """Totals, plus breakdowns by model, by purpose, and (admin only) by
    user. With no start/end given this covers every call ever recorded for
    whatever scope applies, per the "keep every call forever" retention
    decision."""
    is_admin = current_user.role == UserRole.ADMIN
    scope = "all" if is_admin else "own"

    base = _date_range_filter(db.query(LlmUsageEvent), start, end)
    if not is_admin:
        base = base.filter(LlmUsageEvent.user_id == current_user.id)

    totals_row = base.with_entities(
        func.count(LlmUsageEvent.id),
        func.coalesce(func.sum(LlmUsageEvent.input_tokens), 0),
        func.coalesce(func.sum(LlmUsageEvent.output_tokens), 0),
        func.coalesce(func.sum(LlmUsageEvent.estimated_cost_usd), 0),
        func.coalesce(func.sum(LlmUsageEvent.latency_ms), 0),
    ).one()
    calls, input_tokens, output_tokens, cost, latency_sum = totals_row
    totals = UsageTotals(
        total_calls=calls,
        total_input_tokens=input_tokens,
        total_output_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens,
        total_cost_usd=float(cost),
        total_latency_ms=latency_sum,
        avg_latency_ms=(latency_sum / calls) if calls else 0.0,
    )

    by_model_rows = base.with_entities(
        LlmUsageEvent.model,
        func.count(LlmUsageEvent.id),
        func.coalesce(func.sum(LlmUsageEvent.input_tokens), 0),
        func.coalesce(func.sum(LlmUsageEvent.output_tokens), 0),
        func.coalesce(func.sum(LlmUsageEvent.estimated_cost_usd), 0),
        func.coalesce(func.avg(LlmUsageEvent.latency_ms), 0),
    ).group_by(LlmUsageEvent.model).order_by(func.count(LlmUsageEvent.id).desc()).all()
    by_model = [
        UsageByModel(
            model=model, calls=n, input_tokens=in_tok, output_tokens=out_tok,
            cost_usd=float(cost), avg_latency_ms=float(avg_lat),
        )
        for model, n, in_tok, out_tok, cost, avg_lat in by_model_rows
    ]

    by_purpose_rows = base.with_entities(
        LlmUsageEvent.purpose,
        func.count(LlmUsageEvent.id),
        func.coalesce(func.sum(LlmUsageEvent.input_tokens), 0),
        func.coalesce(func.sum(LlmUsageEvent.output_tokens), 0),
        func.coalesce(func.sum(LlmUsageEvent.estimated_cost_usd), 0),
        func.coalesce(func.avg(LlmUsageEvent.latency_ms), 0),
    ).group_by(LlmUsageEvent.purpose).order_by(func.count(LlmUsageEvent.id).desc()).all()
    by_purpose = [
        UsageByPurpose(
            purpose=purpose, calls=n, input_tokens=in_tok, output_tokens=out_tok,
            cost_usd=float(cost), avg_latency_ms=float(avg_lat),
        )
        for purpose, n, in_tok, out_tok, cost, avg_lat in by_purpose_rows
    ]

    by_user: list[UsageByUser] = []
    if is_admin:
        # Outer join so a call with no user_id (rare - see LlmUsageEvent's
        # attribution comment) still shows up, grouped as "Unattributed"
        # rather than silently missing from the by-user total. Only built
        # for an admin - see this module's own docstring for why a
        # non-admin never gets this breakdown at all.
        by_user_rows = (
            _date_range_filter(
                db.query(
                    LlmUsageEvent.user_id,
                    User.name,
                    func.count(LlmUsageEvent.id),
                    func.coalesce(func.sum(LlmUsageEvent.input_tokens), 0),
                    func.coalesce(func.sum(LlmUsageEvent.output_tokens), 0),
                    func.coalesce(func.sum(LlmUsageEvent.estimated_cost_usd), 0),
                    func.coalesce(func.avg(LlmUsageEvent.latency_ms), 0),
                ).outerjoin(User, User.id == LlmUsageEvent.user_id),
                start, end,
            )
            .group_by(LlmUsageEvent.user_id, User.name)
            .order_by(func.count(LlmUsageEvent.id).desc())
            .all()
        )
        by_user = [
            UsageByUser(
                user_id=user_id,
                user_name=name or "Unattributed",
                calls=n, input_tokens=in_tok, output_tokens=out_tok,
                cost_usd=float(cost), avg_latency_ms=float(avg_lat),
            )
            for user_id, name, n, in_tok, out_tok, cost, avg_lat in by_user_rows
        ]

    return UsageSummaryOut(scope=scope, totals=totals, by_model=by_model, by_purpose=by_purpose, by_user=by_user)


@router.get("/timeseries", response_model=UsageTimeseriesOut)
def get_usage_timeseries(
    start: Optional[date] = Query(None, description="Inclusive UTC start date filter"),
    end: Optional[date] = Query(None, description="Inclusive UTC end date filter"),
    user_id: Optional[uuid.UUID] = Query(
        None,
        description=(
            "Admin only: chart one specific user's calls instead of the team total. "
            "Silently ignored for a non-admin caller, who already only ever sees their "
            "own calls (see this module's docstring) - so a tampered query string "
            "cannot be used to read someone else's per-call timing."
        ),
    ),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UsageTimeseriesOut:
    """The Usage page's chart, in one of two granularities - see
    UsageDailyPoint's own docstring for the shape both share:

      - Per-call, when every call in range happened on the SAME calendar
        day (and there are not too many of them): one point per call, at
        its own timestamp, with that call's own numbers - not a running
        total. Client follow-up request: a single day of a handful of
        calls used to render as one flat daily bar (or, before the
        zero-fill below existed, a lone dot); plotting each call at its
        real time draws the actual shape of that day instead.
      - Daily-aggregate, otherwise (the original behaviour, still what a
        multi-day range needs - see the zero-fill note below): one point
        per calendar day (UTC), every user's calls for an admin, only the
        caller's own otherwise (see this module's docstring). Defaults to
        the last 30 days when no range is given - the summary endpoint
        defaults to all-time, but an all-time daily chart would be
        unreadable once this table has months of rows.

    Zero-filled, not sparse, in daily mode: a naive GROUP BY only emits a
    row for a day that actually had a call, so a 30-day window with
    activity on a single day used to come back as a list of ONE point -
    which the chart could only draw as a lone dot, never a line. Every
    calendar day in [start, end] gets a point, zero-valued where nothing
    happened, so the line has something to draw across the whole range.

    Client follow-up request: an admin can additionally pass `user_id` to
    chart one team member's own calls in the same style as the team total,
    instead of only ever seeing everyone combined - see `filter_user_id`
    below and the `user_id` param's own description."""
    is_admin = current_user.role == UserRole.ADMIN
    # The one id every query below actually filters on: an admin's own
    # choice (`user_id`, or None for the team total) if they supplied one,
    # otherwise always the caller's own id - which also quietly discards a
    # non-admin's `user_id` query param instead of ever honouring it.
    filter_user_id = user_id if is_admin else current_user.id

    # Both filled in together, not just the both-None case: the zero-fill
    # loop below walks a concrete [start, end], so a caller supplying only
    # one of the two (this is a public query-param pair, not just what the
    # frontend happens to send) still gets a bounded, fillable range rather
    # than a None crashing the walk.
    if end is None:
        end = datetime.now(timezone.utc).date()
    if start is None:
        start = end - timedelta(days=29)
    # The zero-fill loop below materialises one point per day in range, so
    # an inverted or multi-year span (a hand-crafted query string, not
    # anything this page's own three presets send) is clamped rather than
    # walked literally - same "unreadable" reasoning the docstring already
    # gives for why all-time has no daily chart of its own.
    if start > end:
        start = end
    if (end - start).days > 366:
        start = end - timedelta(days=366)

    event_query = db.query(
        LlmUsageEvent.created_at,
        LlmUsageEvent.input_tokens,
        LlmUsageEvent.output_tokens,
        LlmUsageEvent.estimated_cost_usd,
    )
    if filter_user_id is not None:
        event_query = event_query.filter(LlmUsageEvent.user_id == filter_user_id)
    events = (
        _date_range_filter(event_query, start, end)
        .order_by(LlmUsageEvent.created_at)
        # One more than the cap, purely so the len() check below can tell
        # "exactly at the cap" from "over it" without a second COUNT query.
        .limit(_PER_CALL_POINT_CAP + 1)
        .all()
    )

    distinct_days = {created_at.date() for created_at, *_ in events}
    if events and len(distinct_days) == 1 and len(events) <= _PER_CALL_POINT_CAP:
        # created_at is already UTC (see the model's own comment: written
        # from func.now(), an aware TIMESTAMPTZ on Postgres) but comes back
        # tz-NAIVE on SQLite, which has no native tz support - .astimezone()
        # on a naive value assumes it means the SERVER's local time and
        # shifts it, which is wrong here. Stamp it as UTC first (a no-op on
        # Postgres, where it is already aware) rather than convert it.
        points = [
            UsageDailyPoint(
                date=created_at.date(),
                time=(created_at if created_at.tzinfo else created_at.replace(tzinfo=timezone.utc)).isoformat(),
                calls=1,
                input_tokens=in_tok,
                output_tokens=out_tok,
                cost_usd=float(cost),
            )
            for created_at, in_tok, out_tok, cost in events
        ]
        return UsageTimeseriesOut(scope="all" if is_admin else "own", points=points)

    day = func.date(LlmUsageEvent.created_at)
    query = db.query(
        day.label("day"),
        func.count(LlmUsageEvent.id),
        func.coalesce(func.sum(LlmUsageEvent.input_tokens), 0),
        func.coalesce(func.sum(LlmUsageEvent.output_tokens), 0),
        func.coalesce(func.sum(LlmUsageEvent.estimated_cost_usd), 0),
    )
    if filter_user_id is not None:
        query = query.filter(LlmUsageEvent.user_id == filter_user_id)

    rows = (
        _date_range_filter(query, start, end)
        .group_by("day")
        .order_by("day")
        .all()
    )
    # `day` comes back as a `date` on Postgres but as a `str` on SQLite (the
    # func.date() cast isn't parsed back into a Python date by that
    # dialect) - normalise so the dict below keys consistently regardless
    # of which database this is running against.
    by_day = {
        (d if isinstance(d, date) else date.fromisoformat(d)): (n, in_tok, out_tok, cost)
        for d, n, in_tok, out_tok, cost in rows
    }

    points = []
    cursor = start
    while cursor <= end:
        n, in_tok, out_tok, cost = by_day.get(cursor, (0, 0, 0, 0))
        points.append(
            UsageDailyPoint(date=cursor, calls=n, input_tokens=in_tok, output_tokens=out_tok, cost_usd=float(cost))
        )
        cursor += timedelta(days=1)

    return UsageTimeseriesOut(scope="all" if is_admin else "own", points=points)
