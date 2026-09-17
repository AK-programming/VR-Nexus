/**
 * API Usage — the page from the client's follow-up request: "add a tab
 * named API Usage" showing totals, a by-model/by-purpose/by-user
 * breakdown, and a daily chart of Anthropic API token consumption and its
 * estimated cost.
 *
 * Every figure here is derived from backend/app/models/llm_usage_event.py —
 * one row per Anthropic API call, written by app/services/usage_tracking.py
 * from every call site (tender extraction, tender metadata, library
 * auto-tagging, the Evidence Library's grounded Ask). Costs are estimates
 * from a hand-maintained pricing table, never a billing source of truth —
 * every cost figure on this page is labelled "estimated" for that reason.
 *
 * Second follow-up request: open to every signed-in account, not
 * admin-only, scoped by role — an admin sees everyone's usage, anyone else
 * sees only their own. Reachable via ROUTES.apiUsage with no RequireAdmin
 * gate (unlike AdminUsersPage). That scoping is enforced on the backend
 * (see api/routes/usage.py: `get_current_user`, not
 * `require_role(UserRole.ADMIN)`, with every query filtered to the
 * caller's own user_id for a non-admin) — `summary.data.scope` ("all" vs.
 * "own") below just tells this page which one actually happened, so it can
 * word the header correctly and skip the "By user" table for a scope of
 * "own", where a breakdown by user would be a table of one row: the
 * viewer themselves.
 *
 * Third follow-up request ("design like that", pointing at a reference
 * dashboard mockup): a visual pass — coloured stat-tile icon chips, a
 * date-range control, a CSV export, delta badges on the stat tiles, avatar/
 * icon chips in the tables, and a footer disclaimer bar. Two things from
 * the reference were deliberately NOT copied as-is because they cannot be
 * done honestly with what this page actually has:
 *
 *   - The reference's "↑0%" delta badges are real here, not decoration.
 *     They compare the selected range's totals against an equal-length
 *     PRIOR period, fetched as a second summary call (`comparison` below).
 *     A range of "All time" has no equal-length prior period to compare
 *     against, so the badges simply do not render for it — an invented
 *     percentage would be worse than none. See `computeDelta`.
 *   - The reference's "Learn more" footer link had nowhere real to point
 *     (no cost-methodology page exists), so it is left as plain text.
 *
 * Both endpoints (summary, timeseries) already accept `start`/`end` query
 * params (see usage.py) that this page never used before this pass — the
 * date-range control now drives both from one shared range, which also
 * fixes the previous inconsistency where the stat tiles were always
 * all-time and the chart was always the last 30 days regardless of what
 * the tiles showed.
 */

import { useEffect, useMemo, useState } from 'react'
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { formatPurpose } from '@/models'
import type {
  UsageByModel,
  UsageByPurpose,
  UsageByUser,
  UsageDailyPoint,
  UsageSummary,
  UsageTotals,
} from '@/models'
import { usageService } from '@/services/usageService'
import type { UsageDateRange } from '@/services/usageService'
import { useAsyncData } from '@/hooks/useAsyncData'
import { usePrefersReducedMotion } from '@/hooks/usePrefersReducedMotion'
import { useClickOutside } from '@/hooks/useClickOutside'
import {
  formatCostUsd,
  formatCount,
  formatDurationMs,
  formatInitials,
  formatLongDate,
  formatShortDate,
  formatSignedPercent,
  formatTimeOfDay,
} from '@/lib/formatting'
import { Panel } from '@/components/dashboard/Panel'
import { ActionButton, IconAction } from '@/components/ui/ActionButton'
import { DataTable, TableEmptyState, type Column } from '@/components/ui/DataTable'
import { ErrorBlock, LoadingRows } from '@/components/feedback/DataState'
import {
  ArrowDownIcon,
  ArrowUpIcon,
  BarChartIcon,
  CalculatorIcon,
  CalendarIcon,
  ChatIcon,
  CheckIcon,
  ChevronDownIcon,
  ClipboardCheckIcon,
  ClockIcon,
  DatabaseIcon,
  DollarSignIcon,
  DownloadIcon,
  FileTextIcon,
  InfoIcon,
  RefreshIcon,
  TagIcon,
  UsersIcon,
} from '@/components/ui/icons'

/* --color-brand-500, --color-hairline, --color-neutral-500, --color-surface —
   literal hex rather than var(...), same reasoning as AnalysisOverview.tsx:
   Recharts writes these as raw SVG presentation attributes, and var()
   resolution inside one is not reliable across every engine. */
const BRAND = '#e8151b'
const HAIRLINE = '#e6e8ec'
const AXIS_TEXT = '#71717a'
const SURFACE = '#ffffff'

/** A point plus derived fields none of the three chart metrics, or the
 *  chart's own x-axis, can read directly off UsageDailyPoint on its own:
 *
 *   - "tokens" (input + output).
 *   - "xKey" — the single field the chart's x-axis plots against
 *     regardless of which granularity this response is in (a call's own
 *     `time` when present, that day's `date` otherwise; see
 *     UsageDailyPoint's doc comment).
 *   - "callsCumulative" — running total of `calls` up to and including
 *     this point. Only meaningful, and only used, in per-call mode: a
 *     per-call point's own `calls` is always exactly 1 (it IS one call),
 *     so plotting that raw value draws a flat line at y=1 no matter how
 *     many calls happened — not a "wave", and not what "call 1, call 2,
 *     call 3" as points on a rising line actually means. The running
 *     total is what turns "point N" into "N calls so far", which is the
 *     one metric of the three where each point's OWN value can never
 *     vary and a cumulative count is the only way to give the Calls
 *     series a shape at all. Tokens/Cost stay non-cumulative — each
 *     call's own tokens or cost genuinely differs call to call, so
 *     their line is already real per-call variation, not a flat
 *     constant needing this same fix. */
type ChartPoint = UsageDailyPoint & { tokens: number; xKey: string; callsCumulative: number }

type UsageMetric = 'calls' | 'tokens' | 'cost'

const METRIC_OPTIONS: { value: UsageMetric; label: string }[] = [
  { value: 'calls', label: 'Calls' },
  { value: 'tokens', label: 'Tokens' },
  { value: 'cost', label: 'Cost' },
]

const METRIC_CONFIG: Record<
  UsageMetric,
  {
    dataKey: keyof ChartPoint
    unit: string
    /** Exact value, for the total figure and the tooltip. */
    format: (value: number) => string
    /** Abbreviated, for the Y-axis so "2,951 tokens" doesn't force a wide gutter. */
    formatTick: (value: number) => string
  }
> = {
  calls: {
    dataKey: 'calls',
    unit: 'calls',
    format: (value) => formatCount(value),
    formatTick: (value) => formatCount(Math.round(value)),
  },
  tokens: {
    dataKey: 'tokens',
    unit: 'tokens',
    format: (value) => formatCount(value),
    formatTick: (value) => (value >= 1000 ? `${(value / 1000).toFixed(value >= 10000 ? 0 : 1)}K` : formatCount(value)),
  },
  cost: {
    dataKey: 'cost_usd',
    unit: 'estimated cost',
    format: (value) => formatCostUsd(value),
    formatTick: (value) => (value > 0 && value < 0.01 ? '<$0.01' : `$${value.toFixed(2)}`),
  },
}

/* ---------------------------------------------------------------------- */
/* Date range                                                              */
/* ---------------------------------------------------------------------- */

type UsageRangeKey = 'last_7' | 'last_30' | 'last_90' | 'all'

const RANGE_OPTIONS: { value: UsageRangeKey; label: string; days: number | null }[] = [
  { value: 'last_7', label: 'Last 7 days', days: 7 },
  { value: 'last_30', label: 'Last 30 days', days: 30 },
  { value: 'last_90', label: 'Last 90 days', days: 90 },
  { value: 'all', label: 'All time', days: null },
]

function isoDate(d: Date): string {
  return d.toISOString().slice(0, 10)
}

/** The selected preset's own inclusive UTC `[start, end]` — undefined for
 *  "All time", which just omits both params and lets the endpoints use
 *  their own defaults (see usage.py's docstrings). */
function rangeToDates(key: UsageRangeKey): UsageDateRange | undefined {
  const option = RANGE_OPTIONS.find((o) => o.value === key)
  if (!option || option.days === null) {
    return undefined
  }
  const end = new Date()
  const start = new Date(end)
  start.setUTCDate(start.getUTCDate() - (option.days - 1))
  return { start: isoDate(start), end: isoDate(end) }
}

/** The equal-length period immediately BEFORE the selected range, for the
 *  "vs previous period" delta badges. Undefined for "All time" — there is
 *  no bounded prior period to compare an unbounded range against, and no
 *  invented one is shown (see `computeDelta` / `DeltaBadge`). */
function previousRangeToDates(key: UsageRangeKey, current: UsageDateRange | undefined): UsageDateRange | undefined {
  const option = RANGE_OPTIONS.find((o) => o.value === key)
  if (!option || option.days === null || !current?.start) {
    return undefined
  }
  const previousEnd = new Date(`${current.start}T00:00:00Z`)
  previousEnd.setUTCDate(previousEnd.getUTCDate() - 1)
  const previousStart = new Date(previousEnd)
  previousStart.setUTCDate(previousStart.getUTCDate() - (option.days - 1))
  return { start: isoDate(previousStart), end: isoDate(previousEnd) }
}

/** Percentage change of `current` over `previous`. Null — never a fake
 *  number — when there is nothing honest to divide by: no prior-period
 *  data at all, or a prior total of exactly zero (an "up 4,000,000%" badge
 *  off a zero baseline is technically arithmetic but reads as nonsense). */
function computeDelta(current: number, previous: number | null | undefined): number | null {
  if (previous === null || previous === undefined || previous === 0) {
    return null
  }
  return ((current - previous) / previous) * 100
}

function DeltaBadge({ delta, positiveIsGood = true }: { delta: number | null; positiveIsGood?: boolean }) {
  if (delta === null || !Number.isFinite(delta)) {
    return null
  }
  const rounded = Math.round(delta)
  if (rounded === 0) {
    return (
      <span className="inline-flex items-center rounded-full bg-neutral-100 px-1.5 py-0.5 text-[0.6875rem] font-semibold text-neutral-500">
        No change
      </span>
    )
  }
  const isIncrease = rounded > 0
  const good = isIncrease === positiveIsGood
  const Icon = isIncrease ? ArrowUpIcon : ArrowDownIcon
  return (
    <span
      className={[
        'inline-flex items-center gap-0.5 rounded-full px-1.5 py-0.5 text-[0.6875rem] font-semibold tabular-nums',
        good ? 'bg-emerald-50 text-emerald-700' : 'bg-rose-50 text-rose-700',
      ].join(' ')}
    >
      <Icon className="size-3" aria-hidden="true" />
      {formatSignedPercent(delta)}
    </span>
  )
}

/* Same `aria-pressed` role="group" pattern as MetricSwitch/RangeSwitch
   elsewhere, but as a listbox: a date range is a single mutually-exclusive
   choice presented as a menu (like the reference), not a row of buttons —
   four labels ("Last 7 days" …) are too wide to sit as pills next to
   Export without wrapping on a phone. Selection is marked with a bold
   check, per the dataviz reference's own filter-control spec. */
function RangeMenu({
  value,
  onChange,
}: {
  value: UsageRangeKey
  onChange: (key: UsageRangeKey) => void
}) {
  const [open, setOpen] = useState(false)
  const containerRef = useClickOutside<HTMLDivElement>(() => setOpen(false))
  const activeLabel = RANGE_OPTIONS.find((option) => option.value === value)?.label ?? ''

  return (
    <div ref={containerRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((wasOpen) => !wasOpen)}
        aria-haspopup="listbox"
        aria-expanded={open}
        className="flex h-9 items-center gap-2 rounded-xl border border-hairline bg-surface px-3 text-sm font-medium text-neutral-900 shadow-sm transition-colors duration-150 hover:bg-surface-muted"
      >
        <CalendarIcon className="size-4 text-neutral-500" aria-hidden="true" />
        {activeLabel}
        <ChevronDownIcon
          className={['size-3.5 text-neutral-500 transition-transform duration-150', open ? 'rotate-180' : ''].join(' ')}
          aria-hidden="true"
        />
      </button>
      {open ? (
        <div
          role="listbox"
          aria-label="Date range"
          className="absolute right-0 top-11 z-20 w-44 overflow-hidden rounded-xl border border-hairline bg-surface py-1 shadow-panel"
        >
          {RANGE_OPTIONS.map((option) => {
            const isActive = option.value === value
            return (
              <button
                key={option.value}
                type="button"
                role="option"
                aria-selected={isActive}
                onClick={() => {
                  onChange(option.value)
                  setOpen(false)
                }}
                className={[
                  'flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-sm transition-colors duration-150',
                  isActive ? 'font-medium text-neutral-900' : 'text-neutral-600 hover:bg-surface-muted hover:text-neutral-900',
                ].join(' ')}
              >
                {option.label}
                {isActive ? <CheckIcon className="size-4 text-brand-600" aria-hidden="true" /> : null}
              </button>
            )
          })}
        </div>
      ) : null}
    </div>
  )
}

/* ---------------------------------------------------------------------- */
/* Stat tiles                                                              */
/* ---------------------------------------------------------------------- */

const STAT_TONE_CLASSES = {
  brand: 'bg-brand-50 text-brand-700',
  violet: 'bg-violet-50 text-violet-700',
  emerald: 'bg-emerald-50 text-emerald-700',
  sky: 'bg-sky-50 text-sky-700',
} as const

function StatTile({
  label,
  value,
  hint,
  icon: Icon,
  tone,
  delta,
  positiveIsGood = true,
}: {
  label: string
  value: string
  hint?: string
  icon: typeof CalculatorIcon
  tone: keyof typeof STAT_TONE_CLASSES
  /** Null (not shown) until the comparison period has loaded, or forever
   *  for "All time" — see `computeDelta`'s own doc. */
  delta?: number | null
  positiveIsGood?: boolean
}) {
  return (
    <div className="rounded-2xl border border-hairline bg-surface p-4 shadow-sm">
      <div className="flex items-center justify-between gap-2">
        <span
          aria-hidden="true"
          className={['flex size-9 shrink-0 items-center justify-center rounded-xl', STAT_TONE_CLASSES[tone]].join(' ')}
        >
          <Icon className="size-4.5" />
        </span>
        <DeltaBadge delta={delta ?? null} positiveIsGood={positiveIsGood} />
      </div>
      <p className="mt-3 text-xs font-medium text-neutral-500">{label}</p>
      <p className="mt-0.5 font-display text-2xl font-semibold tabular-nums text-neutral-900">{value}</p>
      {hint ? <p className="mt-0.5 text-xs text-neutral-500">{hint}</p> : null}
    </div>
  )
}

/* ---------------------------------------------------------------------- */
/* Chart                                                                   */
/* ---------------------------------------------------------------------- */

type ChartTooltipProps = {
  active?: boolean
  payload?: { payload: ChartPoint }[]
  metric: UsageMetric
  /** Same meaning as ApiUsagePage's own `isEventMode` — passed through so
   *  this tooltip's primary line can agree with what the Area is actually
   *  plotting (the running total for Calls, not that one call's own "1";
   *  see ChartPoint's `callsCumulative` doc comment). */
  isEventMode: boolean
}

/* Values lead, the day follows — the reader hovers wanting a number, not a
   reminder of what "day" means. The selected metric renders first and large
   (a short stroke of the series colour keys it, per the dataviz reference,
   rather than a filled swatch); the other two stay as plain secondary
   context underneath so nothing the original combined tooltip showed is
   lost when the reader is looking at a different metric than usual. */
function ChartTooltip({ active, payload, metric, isEventMode }: ChartTooltipProps) {
  const point = payload?.[0]?.payload
  if (!active || !point) {
    return null
  }

  const config = METRIC_CONFIG[metric]
  const secondary = (['calls', 'tokens', 'cost'] as const).filter((option) => option !== metric)
  /* Agrees with `seriesValue` in ApiUsagePage: the running total for a
     per-call Calls series (what the line is actually plotting at this
     point), that point's own value otherwise. See ChartPoint's
     `callsCumulative` doc comment for why Calls alone needs this. */
  const primaryValue = metric === 'calls' && isEventMode ? point.callsCumulative : (point[config.dataKey] as number)

  return (
    <div className="min-w-[9.5rem] rounded-xl border border-hairline bg-surface px-3 py-2 shadow-lg">
      <p className="text-xs font-medium text-neutral-500">
        {formatLongDate(point.date)}
        {point.time ? `, ${formatTimeOfDay(point.time)}` : ''}
      </p>
      <p className="mt-1 flex items-center gap-1.5 text-sm font-semibold text-neutral-900 tabular-nums">
        <span aria-hidden="true" className="inline-block h-0.5 w-2.5 rounded-full" style={{ backgroundColor: BRAND }} />
        {config.format(primaryValue)} {metric === 'calls' ? (primaryValue === 1 ? 'call' : 'calls') : config.unit}
      </p>
      <dl className="mt-1 space-y-0.5 border-t border-hairline pt-1">
        {secondary.map((option) => (
          <div key={option} className="flex items-center justify-between gap-3 text-xs text-neutral-500 tabular-nums">
            <dt>{METRIC_CONFIG[option].unit === 'calls' ? 'Calls' : METRIC_CONFIG[option].unit === 'tokens' ? 'Tokens' : 'Est. cost'}</dt>
            <dd>{METRIC_CONFIG[option].format(point[METRIC_CONFIG[option].dataKey] as number)}</dd>
          </div>
        ))}
      </dl>
    </div>
  )
}

type MetricSwitchProps = {
  value: UsageMetric
  onChange: (metric: UsageMetric) => void
}

/* Same `aria-pressed` group as AnalysisOverview's RangeSwitch, not a
   role="tablist": there is only one chart redrawing against a different
   field, not separate panels to switch between. */
function MetricSwitch({ value, onChange }: MetricSwitchProps) {
  return (
    <div
      role="group"
      aria-label="Chart metric"
      className="flex items-center gap-1 rounded-xl border border-brand-200 bg-surface-muted p-1"
    >
      {METRIC_OPTIONS.map((option) => {
        const isActive = option.value === value
        return (
          <button
            key={option.value}
            type="button"
            aria-pressed={isActive}
            onClick={() => onChange(option.value)}
            className={[
              'rounded-lg px-2.5 py-1 text-xs font-semibold whitespace-nowrap transition-colors duration-150',
              /* Brand-tinted pill for the active metric, not a plain white/black
                 one — matches the reference chart's highlighted tab and reuses
                 the same self-contained bg-{color}-50/text-{color}-700 pairing
                 the rest of the page already uses for chips (see PURPOSE_ICONS'
                 icon chip below), so it needs no separate dark-mode override. */
              isActive ? 'bg-brand-50 text-brand-700' : 'text-neutral-600 hover:text-neutral-900',
            ].join(' ')}
          >
            {option.label}
          </button>
        )
      })}
    </div>
  )
}

/* ---------------------------------------------------------------------- */
/* Table row decorations — an icon/avatar chip beside the primary column   */
/* ---------------------------------------------------------------------- */

const PURPOSE_ICONS: Record<string, typeof CalculatorIcon> = {
  tender_extraction: FileTextIcon,
  tender_metadata: ClipboardCheckIcon,
  library_tagging: TagIcon,
  library_ask: ChatIcon,
}

/** A handful of tone pairs to rotate a user's avatar chip through — purely
 *  decorative (a row's own name is what identifies it, per the DataTable's
 *  no-color-only-identity rule), so a stable hash of the id/name is enough;
 *  no legend is owed because color carries no meaning here. */
const AVATAR_TONES = [
  'bg-rose-100 text-rose-700',
  'bg-violet-100 text-violet-700',
  'bg-sky-100 text-sky-700',
  'bg-emerald-100 text-emerald-700',
  'bg-amber-100 text-amber-700',
]

function avatarTone(seed: string): string {
  let hash = 0
  for (let index = 0; index < seed.length; index += 1) {
    hash = (hash * 31 + seed.charCodeAt(index)) >>> 0
  }
  return AVATAR_TONES[hash % AVATAR_TONES.length]
}

/* ---------------------------------------------------------------------- */
/* CSV export — everything currently on screen, for the selected range     */
/* ---------------------------------------------------------------------- */

function csvCell(value: string | number): string {
  const text = String(value)
  return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text
}

function buildUsageCsv(args: {
  rangeLabel: string
  totals: UsageTotals | undefined
  points: UsageDailyPoint[]
  byModel: UsageByModel[]
  byPurpose: UsageByPurpose[]
  byUser: UsageByUser[]
}): string {
  const { rangeLabel, totals, points, byModel, byPurpose, byUser } = args
  const lines: string[] = []

  lines.push(csvCell(`VR-Nexus API Usage — ${rangeLabel}`))
  lines.push(`Generated,${new Date().toISOString()}`)
  lines.push('')

  lines.push('Totals')
  lines.push('Calls,Input tokens,Output tokens,Total tokens,Estimated cost (USD),Avg call time (ms)')
  lines.push(
    [
      totals?.total_calls ?? 0,
      totals?.total_input_tokens ?? 0,
      totals?.total_output_tokens ?? 0,
      totals?.total_tokens ?? 0,
      (totals?.total_cost_usd ?? 0).toFixed(6),
      Math.round(totals?.avg_latency_ms ?? 0),
    ].join(','),
  )
  lines.push('')

  lines.push('Daily')
  lines.push('Date,Calls,Input tokens,Output tokens,Estimated cost (USD)')
  for (const point of points) {
    lines.push([point.date, point.calls, point.input_tokens, point.output_tokens, point.cost_usd.toFixed(6)].join(','))
  }
  lines.push('')

  lines.push('By model')
  lines.push('Model,Calls,Tokens,Avg call time (ms),Estimated cost (USD)')
  for (const row of byModel) {
    lines.push(
      [csvCell(row.model), row.calls, row.input_tokens + row.output_tokens, Math.round(row.avg_latency_ms), row.cost_usd.toFixed(6)].join(','),
    )
  }
  lines.push('')

  lines.push('By purpose')
  lines.push('Purpose,Calls,Tokens,Avg call time (ms),Estimated cost (USD)')
  for (const row of byPurpose) {
    lines.push(
      [csvCell(formatPurpose(row.purpose)), row.calls, row.input_tokens + row.output_tokens, Math.round(row.avg_latency_ms), row.cost_usd.toFixed(6)].join(
        ',',
      ),
    )
  }

  if (byUser.length > 0) {
    lines.push('')
    lines.push('By user')
    lines.push('User,Calls,Tokens,Avg call time (ms),Estimated cost (USD)')
    for (const row of byUser) {
      lines.push(
        [csvCell(row.user_name), row.calls, row.input_tokens + row.output_tokens, Math.round(row.avg_latency_ms), row.cost_usd.toFixed(6)].join(','),
      )
    }
  }

  return lines.join('\n')
}

function downloadCsv(filename: string, content: string) {
  const blob = new Blob([content], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}

/* ---------------------------------------------------------------------- */

export function ApiUsagePage() {
  const [range, setRange] = useState<UsageRangeKey>('last_30')
  const [metric, setMetric] = useState<UsageMetric>('calls')
  /* Admin only — "chart one team member instead of everyone combined" (see
   * the User select rendered next to the Usage trend panel below). null
   * means "all users", the pre-existing behaviour; a non-admin never sets
   * this since the select only renders once `scope === 'all'` further down.
   * Kept as an id, not the row, so it survives a range change even when
   * that user drops out of the new range's `byUser` list (handled by the
   * effect below rather than resetting mid-render). */
  const [selectedUserId, setSelectedUserId] = useState<string | null>(null)
  const prefersReducedMotion = usePrefersReducedMotion()

  const rangeLabel = RANGE_OPTIONS.find((option) => option.value === range)?.label ?? ''
  const dateParams = useMemo(() => rangeToDates(range), [range])
  const comparisonParams = useMemo(() => previousRangeToDates(range, dateParams), [range, dateParams])

  const summary = useAsyncData((signal) => usageService.getSummary(dateParams, signal), [range])
  const timeseries = useAsyncData(
    (signal) => usageService.getTimeseries(dateParams, selectedUserId ?? undefined, signal),
    [range, selectedUserId],
  )
  /* The equal-length prior period, fetched purely to power the delta
     badges — null (not an error) whenever "All time" is selected, since
     there is nothing to compare it against. See `previousRangeToDates`. */
  const comparison = useAsyncData<UsageSummary | null>(
    (signal) => (comparisonParams ? usageService.getSummary(comparisonParams, signal) : Promise.resolve(null)),
    [range],
  )

  const points = timeseries.data?.points ?? []
  /* Per-call mode: every point in this response carries its own `time`
     (see UsageDailyPoint's doc comment) — the backend only returns it that
     way when every call in the requested range landed on one calendar day
     and there weren't too many of them, so checking the first point is
     enough to know what the whole array is. */
  const isEventMode = points.length > 0 && points[0].time !== undefined
  const chartPoints: ChartPoint[] = useMemo(() => {
    let runningCalls = 0
    return points.map((point) => {
      runningCalls += point.calls
      return {
        ...point,
        tokens: point.input_tokens + point.output_tokens,
        xKey: point.time ?? point.date,
        callsCumulative: runningCalls,
      }
    })
  }, [points])
  /* The value the chart actually plots for the current metric — see
     ChartPoint's `callsCumulative` doc comment for why Calls needs its own
     case in per-call mode rather than reading METRIC_CONFIG.calls.dataKey
     off the point like Tokens/Cost do. Shared by the Area series, the
     min/max/total figures below, and ChartTooltip (passed `isEventMode` so
     its own primary line agrees with what the line is actually plotting). */
  function seriesValue(point: ChartPoint): number {
    if (metric === 'calls' && isEventMode) {
      return point.callsCumulative
    }
    return point[METRIC_CONFIG[metric].dataKey] as number
  }
  const hasPoints = chartPoints.length > 0
  const firstLabel = isEventMode
    ? formatTimeOfDay(points[0]?.time ?? '')
    : points[0]?.date
      ? formatShortDate(points[0].date)
      : ''
  const lastLabel = isEventMode
    ? formatTimeOfDay(points[points.length - 1]?.time ?? '')
    : points[points.length - 1]?.date
      ? formatShortDate(points[points.length - 1].date)
      : ''

  const metricConfig = METRIC_CONFIG[metric]
  /* The real total: each point's OWN value, summed — 1+1+1 calls, not
     1+2+3. Deliberately NOT `seriesValue` (which would double-count a
     cumulative Calls series), so the big total figure above the chart
     always reads as an actual total regardless of which line shape the
     chart itself is drawing. */
  const metricValues = chartPoints.map((point) => point[metricConfig.dataKey] as number)
  const metricTotal = metricValues.reduce((sum, value) => sum + value, 0)
  /* The line's own low/high, for the chart's aria-label — `seriesValue`,
     not `metricValues`, so a cumulative Calls series describes itself as
     "between 1 and 3", the range the line actually draws through, rather
     than "between 1 and 1" (every point's own raw value). */
  const chartSeriesValues = chartPoints.map(seriesValue)
  const metricLow = hasPoints ? Math.min(...chartSeriesValues) : 0
  const metricHigh = hasPoints ? Math.max(...chartSeriesValues) : 0

  const totals = summary.data?.totals
  const previousTotals = comparison.data?.totals
  const byModel = useMemo(() => summary.data?.by_model ?? [], [summary.data])
  const byPurpose = useMemo(() => summary.data?.by_purpose ?? [], [summary.data])
  const byUser = useMemo(() => summary.data?.by_user ?? [], [summary.data])
  /* The user-trend select's options: `byUser` minus the rare "Unattributed"
     row (see UsageByUser's own doc comment) — /api/usage/timeseries filters
     by a real user_id, and there is no such thing as one for a NULL-user_id
     call, so that row has nothing a select option could actually chart. */
  const attributedUsers = useMemo(
    () => byUser.filter((row): row is typeof row & { user_id: string } => row.user_id !== null),
    [byUser],
  )
  /* Only ever non-null once the first summary load resolves, and only
     "all" for an admin — see this file's header comment. Used to word the
     header and to decide whether the "By user" table renders at all,
     rather than rendering it and letting it show an empty/one-row table
     for a non-admin. */
  const scope = summary.data?.scope ?? null

  /* Drops a selected user back to "All users" if they fall out of the
     current range's by-user list — switching to a range with none of
     their calls, say — rather than leaving the select showing a name with
     no matching <option> (and the chart silently empty). Skipped while
     summary is still loading so this never fires on the very first render,
     before `byUser` has had a chance to include them. */
  useEffect(() => {
    if (summary.status === 'loading' || !selectedUserId) {
      return
    }
    if (!byUser.some((row) => row.user_id === selectedUserId)) {
      setSelectedUserId(null)
    }
  }, [byUser, selectedUserId, summary.status])

  const selectedUserName = byUser.find((row) => row.user_id === selectedUserId)?.user_name ?? null

  function refreshAll() {
    summary.refetch()
    timeseries.refetch()
    comparison.refetch()
  }

  function exportCsv() {
    const csv = buildUsageCsv({ rangeLabel, totals, points, byModel, byPurpose, byUser })
    const stamp = new Date().toISOString().slice(0, 10)
    downloadCsv(`vr-nexus-api-usage-${range}-${stamp}.csv`, csv)
  }

  const modelColumns: Column<(typeof byModel)[number]>[] = [
    {
      id: 'model',
      header: 'Model',
      sortValue: (row) => row.model,
      /* max-w caps this column so a long model id (claude-sonnet-4-5-…) truncates
         with an ellipsis instead of forcing the whole row wider than the panel —
         see the block comment above the two-panel grid for why that matters here
         specifically: this table sits at half the page's width, not full width. */
      className: 'max-w-[9rem] @sm:max-w-[12rem] @lg:max-w-[16rem]',
      cell: (row) => (
        <span className="flex min-w-0 items-center gap-2">
          <span
            aria-hidden="true"
            className="flex size-6 shrink-0 items-center justify-center rounded-md bg-ink-900 text-[0.5625rem] font-bold text-white"
          >
            AI
          </span>
          <span className="min-w-0 flex-1 truncate font-mono text-xs text-neutral-800" title={row.model}>
            {row.model}
          </span>
        </span>
      ),
    },
    { id: 'calls', header: 'Calls', numeric: true, align: 'center', sortValue: (row) => row.calls, cell: (row) => formatCount(row.calls) },
    {
      id: 'tokens', header: 'Tokens', numeric: true, align: 'center',
      sortValue: (row) => row.input_tokens + row.output_tokens,
      cell: (row) => formatCount(row.input_tokens + row.output_tokens),
      className: 'hidden @sm:table-cell',
    },
    {
      id: 'avg_latency', header: 'Avg time', numeric: true, align: 'center',
      sortValue: (row) => row.avg_latency_ms,
      cell: (row) => formatDurationMs(row.avg_latency_ms),
      className: 'hidden @lg:table-cell',
    },
    {
      id: 'cost', header: 'Est. cost', numeric: true, align: 'center',
      sortValue: (row) => row.cost_usd,
      cell: (row) => formatCostUsd(row.cost_usd),
    },
  ]

  const purposeColumns: Column<(typeof byPurpose)[number]>[] = [
    {
      id: 'purpose',
      header: 'Purpose',
      sortValue: (row) => row.purpose,
      /* Same reasoning as modelColumns' 'model' column: cap the width and
         truncate to one line rather than letting "Library Ask" wrap onto a
         second line, which was quietly making every row in this table taller
         than the numeric columns beside it. */
      className: 'max-w-[8rem] @sm:max-w-[11rem] @lg:max-w-[14rem]',
      cell: (row) => {
        const Icon = PURPOSE_ICONS[row.purpose] ?? CalculatorIcon
        const label = formatPurpose(row.purpose)
        return (
          <span className="flex min-w-0 items-center gap-2">
            <span aria-hidden="true" className="flex size-6 shrink-0 items-center justify-center rounded-md bg-brand-50 text-brand-700">
              <Icon className="size-3.5" />
            </span>
            <span className="min-w-0 flex-1 truncate" title={label}>
              {label}
            </span>
          </span>
        )
      },
    },
    { id: 'calls', header: 'Calls', numeric: true, align: 'center', sortValue: (row) => row.calls, cell: (row) => formatCount(row.calls) },
    {
      id: 'tokens', header: 'Tokens', numeric: true, align: 'center',
      sortValue: (row) => row.input_tokens + row.output_tokens,
      cell: (row) => formatCount(row.input_tokens + row.output_tokens),
      className: 'hidden @sm:table-cell',
    },
    {
      id: 'avg_latency', header: 'Avg time', numeric: true, align: 'center',
      sortValue: (row) => row.avg_latency_ms,
      cell: (row) => formatDurationMs(row.avg_latency_ms),
      className: 'hidden @lg:table-cell',
    },
    {
      id: 'cost', header: 'Est. cost', numeric: true, align: 'center',
      sortValue: (row) => row.cost_usd,
      cell: (row) => formatCostUsd(row.cost_usd),
    },
  ]

  const userColumns: Column<(typeof byUser)[number]>[] = [
    {
      id: 'user',
      header: 'User',
      sortValue: (row) => row.user_name,
      className: 'max-w-[10rem] @sm:max-w-[14rem]',
      cell: (row) => (
        <span className="flex min-w-0 items-center gap-2">
          <span
            aria-hidden="true"
            className={[
              'flex size-6 shrink-0 items-center justify-center rounded-full text-[0.625rem] font-semibold',
              avatarTone(row.user_id ?? row.user_name),
            ].join(' ')}
          >
            {formatInitials(row.user_name)}
          </span>
          <span className="min-w-0 flex-1 truncate" title={row.user_name}>
            {row.user_name}
          </span>
        </span>
      ),
    },
    { id: 'calls', header: 'Calls', numeric: true, align: 'center', sortValue: (row) => row.calls, cell: (row) => formatCount(row.calls) },
    {
      id: 'tokens', header: 'Tokens', numeric: true, align: 'center',
      sortValue: (row) => row.input_tokens + row.output_tokens,
      cell: (row) => formatCount(row.input_tokens + row.output_tokens),
      className: 'hidden @sm:table-cell',
    },
    {
      id: 'avg_latency', header: 'Avg time', numeric: true, align: 'center',
      sortValue: (row) => row.avg_latency_ms,
      cell: (row) => formatDurationMs(row.avg_latency_ms),
      className: 'hidden @lg:table-cell',
    },
    {
      id: 'cost', header: 'Est. cost', numeric: true, align: 'center',
      sortValue: (row) => row.cost_usd,
      cell: (row) => formatCostUsd(row.cost_usd),
    },
  ]

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-4">
      <header className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="font-display text-2xl font-semibold tracking-tight text-neutral-900 sm:text-3xl">
            API Usage
          </h1>
          <p className="mt-1 text-sm text-neutral-500">
            {scope === 'own'
              ? 'Track your own Anthropic API token consumption, costs, and usage across every feature you ran.'
              : 'Track Anthropic API token consumption, costs, and usage across all features.'}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <RangeMenu value={range} onChange={setRange} />
          <ActionButton size="sm" leadingIcon={<DownloadIcon />} onClick={exportCsv} hideLabelOnMobile>
            Export
          </ActionButton>
          <IconAction
            label="Refresh"
            icon={<RefreshIcon />}
            onClick={refreshAll}
            disabled={summary.isRefreshing || timeseries.isRefreshing || comparison.isRefreshing}
          />
        </div>
      </header>

      {summary.status === 'error' && summary.data === null ? (
        <ErrorBlock
          title="Usage data could not be loaded"
          message={summary.error ?? 'The request did not complete.'}
          offline={summary.offline}
          onRetry={summary.refetch}
        />
      ) : summary.status === 'loading' && summary.data === null ? (
        <LoadingRows rows={4} label="Loading usage totals" />
      ) : (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <StatTile
            label="Total calls"
            value={formatCount(totals?.total_calls ?? 0)}
            hint="API requests made"
            icon={CalculatorIcon}
            tone="brand"
            delta={computeDelta(totals?.total_calls ?? 0, previousTotals?.total_calls)}
          />
          <StatTile
            label="Total tokens"
            value={formatCount(totals?.total_tokens ?? 0)}
            hint={`${formatCount(totals?.total_input_tokens ?? 0)} in · ${formatCount(totals?.total_output_tokens ?? 0)} out`}
            icon={DatabaseIcon}
            tone="violet"
            delta={computeDelta(totals?.total_tokens ?? 0, previousTotals?.total_tokens)}
          />
          <StatTile
            label="Estimated cost"
            value={formatCostUsd(totals?.total_cost_usd ?? 0)}
            hint={`${rangeLabel}, from a hand-maintained rate table`}
            icon={DollarSignIcon}
            tone="emerald"
            delta={computeDelta(totals?.total_cost_usd ?? 0, previousTotals?.total_cost_usd)}
          />
          <StatTile
            label="Avg. call time"
            value={formatDurationMs(totals?.avg_latency_ms ?? 0)}
            hint={`${formatDurationMs(totals?.total_latency_ms ?? 0)} total waiting on Claude`}
            icon={ClockIcon}
            tone="sky"
            delta={computeDelta(totals?.avg_latency_ms ?? 0, previousTotals?.avg_latency_ms)}
            positiveIsGood={false}
          />
        </div>
      )}

      <Panel
        title="Usage trend"
        description={
          (isEventMode
            ? 'Calls, tokens, or cost per call today'
            : 'Calls, tokens, or cost per day') +
          (selectedUserName ? ` for ${selectedUserName}` : '') +
          ' — pick a metric below'
        }
        /* Admin only — everyone else already only ever sees their own
           calls, so a "which user" picker over a chart of one person is
           just noise (see this file's header comment on `scope`). */
        action={
          scope === 'all' && attributedUsers.length > 0 ? (
            <div className="relative">
              <label htmlFor="usage-trend-user" className="sr-only">
                Chart one user's usage
              </label>
              <select
                id="usage-trend-user"
                value={selectedUserId ?? ''}
                onChange={(event) => setSelectedUserId(event.target.value || null)}
                className={[
                  'h-8 rounded-lg border border-hairline bg-field pr-7 pl-2.5 text-xs text-neutral-900',
                  'transition-colors duration-150 hover:border-neutral-300',
                  'focus:border-brand-400 focus:bg-surface focus:ring-4 focus:ring-brand-500/15 focus:outline-none',
                ].join(' ')}
              >
                <option value="">All users</option>
                {attributedUsers.map((row) => (
                  <option key={row.user_id} value={row.user_id}>
                    {row.user_name}
                  </option>
                ))}
              </select>
            </div>
          ) : undefined
        }
      >
        {timeseries.status === 'error' && timeseries.data === null ? (
          <ErrorBlock
            title="Daily usage could not be loaded"
            message={timeseries.error ?? 'The request did not complete.'}
            offline={timeseries.offline}
            onRetry={timeseries.refetch}
          />
        ) : timeseries.status === 'loading' && timeseries.data === null ? (
          <LoadingRows rows={3} label="Loading daily usage" />
        ) : !hasPoints ? (
          <div className="flex h-64 flex-col items-center justify-center gap-3 rounded-xl bg-surface-muted px-5 text-center">
            <span
              aria-hidden="true"
              className="flex size-11 items-center justify-center rounded-xl bg-surface text-neutral-500"
            >
              <BarChartIcon className="size-5" />
            </span>
            <p className="text-sm font-medium text-neutral-900">No API calls recorded yet</p>
            <p className="max-w-xs text-xs leading-relaxed text-neutral-500">
              Usage appears here once a tender is analysed or a library document is tagged.
            </p>
          </div>
        ) : (
          <>
            {/* The total + range sits with the metric switch rather than in the
                panel header, same placement AnalysisOverview uses: it belongs
                beside the number it changes, and a 3-way switch next to a
                12-character title would fight for space on a phone — here the
                row just wraps instead. */}
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
                <p className="font-display text-2xl font-semibold tracking-tight text-neutral-900 tabular-nums">
                  {metricConfig.format(metricTotal)}
                </p>
                <p className="text-xs text-neutral-500">
                  {metricConfig.unit}, {firstLabel} – {lastLabel}
                </p>
              </div>
              <MetricSwitch value={metric} onChange={setMetric} />
            </div>

            <div
              role="img"
              aria-label={`Area chart of ${metricConfig.unit} ${isEventMode ? 'per call' : 'per day'} from ${firstLabel} to ${lastLabel}, between ${metricConfig.format(metricLow)} and ${metricConfig.format(metricHigh)} ${isEventMode ? 'per call' : 'per day'}. ${metricConfig.format(metricTotal)} in total.`}
              className="mt-4 h-72 w-full"
            >
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={chartPoints} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
                  <defs>
                    <linearGradient id="usageFill" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor={BRAND} stopOpacity={0.26} />
                      <stop offset="100%" stopColor={BRAND} stopOpacity={0} />
                    </linearGradient>
                  </defs>

                  {/* Horizontal rules only — vertical ones would put a line
                      behind every day in a 90-day range, fighting the shape
                      that's the point of the chart. Dashed after all — a
                      closer look at the client's reference chart shows a
                      fine "3 3" dash, not a solid rule; the previous pass
                      here misread it as solid and the wider "4 4" dash this
                      page had before that read as too chunky next to it. */}
                  <CartesianGrid vertical={false} strokeDasharray="3 3" stroke={HAIRLINE} />

                  <XAxis
                    dataKey="xKey"
                    tickFormatter={(value: string) => (isEventMode ? formatTimeOfDay(value) : formatShortDate(value))}
                    tickLine={false}
                    axisLine={false}
                    tickMargin={8}
                    minTickGap={28}
                    tick={{ fontSize: 11, fill: AXIS_TEXT }}
                  />
                  <YAxis
                    width={44}
                    tickLine={false}
                    axisLine={false}
                    allowDecimals={metric === 'cost'}
                    tickFormatter={(value: number) => metricConfig.formatTick(value)}
                    tick={{ fontSize: 11, fill: AXIS_TEXT }}
                  />
                  <Tooltip
                    content={<ChartTooltip metric={metric} isEventMode={isEventMode} />}
                    cursor={{ stroke: HAIRLINE, strokeWidth: 1 }}
                  />

                  <Area
                    type="monotone"
                    dataKey={seriesValue}
                    stroke={BRAND}
                    strokeWidth={2}
                    fill="url(#usageFill)"
                    dot={chartPoints.length === 1 ? { r: 4, fill: BRAND, stroke: SURFACE, strokeWidth: 2 } : false}
                    activeDot={{ r: 4, fill: BRAND, stroke: SURFACE, strokeWidth: 2 }}
                    isAnimationActive={!prefersReducedMotion}
                    animationDuration={700}
                  />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </>
        )}
      </Panel>

      {/*
        Was a two-up lg:grid-cols-2 row (By model + By purpose) with By user
        full-width below. That started as a fix for an even earlier
        three-across grid that collided headers, but the half-width panel
        it produced (~464px) was too narrow for five columns without either
        overflowing or quietly hiding "Avg time" — chased through a padding
        trim and a container-query threshold change (see DataTable.tsx) that
        closed the gap to zero margin.

        The client's actual ask cuts through all of that: don't fit five
        columns into a half-width panel at all, just give every table the
        full width, stacked, the way "By user" already had it. So all three
        are plain full-width Panels in a row now — no grid, no @container
        threshold tuning needed, no column ever close to being hidden or
        cramped. Simpler layout, and it's what was asked for.
      */}
      <Panel title="By model" description="Which Anthropic model handled the calls" flush collapsible>
        {summary.status === 'loading' && summary.data === null ? (
          <LoadingRows rows={2} label="Loading" />
        ) : byModel.length === 0 ? (
          <div className="py-10">
            <TableEmptyState icon={<CalculatorIcon className="size-5" />} title="No calls yet" description="" />
          </div>
        ) : (
          <DataTable
            rows={byModel}
            columns={modelColumns}
            rowKey={(row) => row.model}
            caption="Usage broken down by model"
            initialSort={{ columnId: 'calls', direction: 'desc' }}
          />
        )}
      </Panel>

      <Panel title="By purpose" description="What each call was actually for" flush collapsible>
        {summary.status === 'loading' && summary.data === null ? (
          <LoadingRows rows={2} label="Loading" />
        ) : byPurpose.length === 0 ? (
          <div className="py-10">
            <TableEmptyState icon={<CalculatorIcon className="size-5" />} title="No calls yet" description="" />
          </div>
        ) : (
          <DataTable
            rows={byPurpose}
            columns={purposeColumns}
            rowKey={(row) => row.purpose}
            caption="Usage broken down by purpose"
            initialSort={{ columnId: 'calls', direction: 'desc' }}
          />
        )}
      </Panel>

      {/* Admin only — see this file's header comment. Not rendered at all
          for scope "own": a by-user breakdown of one person's own data is
          just that person's row again, and the backend does not even
          compute it in that case (see UsageSummaryOut's docstring), so
          there would be nothing honest to show here. Full width on its own
          row, same as the two above. */}
      {scope === 'all' ? (
        <Panel title="By user" description="Who is consuming the API key, and how much" flush collapsible>
          {byUser.length === 0 ? (
            <div className="py-10">
              <TableEmptyState icon={<UsersIcon className="size-5" />} title="No calls yet" description="" />
            </div>
          ) : (
            <DataTable
              rows={byUser}
              columns={userColumns}
              rowKey={(row) => row.user_id ?? 'unattributed'}
              caption="Usage broken down by user"
              initialSort={{ columnId: 'cost', direction: 'desc' }}
            />
          )}
        </Panel>
      ) : null}

      <div className="flex items-start gap-2 rounded-2xl border border-hairline bg-surface-muted px-4 py-3 text-xs text-neutral-600">
        <InfoIcon className="mt-0.5 size-4 shrink-0 text-neutral-400" aria-hidden="true" />
        <p>
          Costs are estimated from a hand-maintained rate table and may differ from your actual Anthropic billing.
        </p>
      </div>
    </div>
  )
}
