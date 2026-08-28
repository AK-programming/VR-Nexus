/**
 * Analyses completed over time, as an area chart with a range switch.
 *
 * Recharts, per the brief. Three notes on how it is wired:
 *
 * 1. Colours are literal hex, not `var(--color-brand-500)`. Recharts writes SVG
 *    presentation attributes, and `var()` inside one resolves in most engines but
 *    not reliably in all of them — a chart that renders black in one browser is not
 *    worth the tidiness. The literals below are the values of the theme tokens they
 *    name, and they are named so a future change is a search that finds them.
 *
 * 2. `ResponsiveContainer` measures its parent, so the parent has a definite height
 *    (`h-72 lg:h-80`). Given a parent that sizes to its content, it collapses to zero.
 *    The height grows with the breakpoint because this panel now spans the full page:
 *    a month of daily points across 1100px at 256px tall is a sparkline, and the
 *    day-to-day differences the chart exists to show flatten out of readability.
 *
 * 3. The chart is `role="img"` with a written summary. A screen reader cannot read an
 *    SVG path, and 31 unlabelled `<text>` nodes are worse than one sentence that says
 *    what the shape does.
 */

import { useEffect, useState } from 'react'
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { formatCount, formatLongDate } from '@/lib/formatting'
import type { AnalysisPoint, AnalysisRange } from '@/models/dashboard'
import { Panel } from '@/components/dashboard/Panel'
import { BarChartIcon } from '@/components/ui/icons'

/* --color-brand-500, --color-hairline, --color-neutral-500, --color-surface. */
const BRAND = '#e8151b'
const HAIRLINE = '#e6e8ec'
const AXIS_TEXT = '#71717a'
const SURFACE = '#ffffff'

const RANGE_OPTIONS: { value: AnalysisRange; label: string }[] = [
  { value: 'this_month', label: 'This month' },
  { value: 'last_month', label: 'Last month' },
  { value: 'last_90_days', label: '90 days' },
]

/**
 * Read synchronously in the initialiser rather than in an effect: Recharts starts
 * its draw animation on first render, and an effect that lands after paint would
 * switch the animation off only once the user had already seen it.
 */
function usePrefersReducedMotion(): boolean {
  const [prefersReduced, setPrefersReduced] = useState(
    () => window.matchMedia('(prefers-reduced-motion: reduce)').matches,
  )

  useEffect(() => {
    const query = window.matchMedia('(prefers-reduced-motion: reduce)')

    function handleChange(event: MediaQueryListEvent) {
      setPrefersReduced(event.matches)
    }

    query.addEventListener('change', handleChange)
    return () => query.removeEventListener('change', handleChange)
  }, [])

  return prefersReduced
}

/* Recharts hands the tooltip the hovered point wrapped in a payload array. Only the
   two fields this tooltip reads are declared, and all of them are optional, because
   Recharts also renders the element once with no props at all. */
type ChartTooltipProps = {
  active?: boolean
  payload?: { payload: AnalysisPoint }[]
}

function ChartTooltip({ active, payload }: ChartTooltipProps) {
  const point = payload?.[0]?.payload

  if (!active || !point) {
    return null
  }

  return (
    <div className="rounded-xl border border-hairline bg-surface px-3 py-2 shadow-lg">
      <p className="text-xs font-medium text-neutral-500">{formatLongDate(point.date)}</p>
      <p className="mt-0.5 text-sm font-semibold text-neutral-900 tabular-nums">
        {formatCount(point.analyses)} {point.analyses === 1 ? 'analysis' : 'analyses'}
      </p>
    </div>
  )
}

type RangeSwitchProps = {
  value: AnalysisRange
  onChange: (range: AnalysisRange) => void
}

function RangeSwitch({ value, onChange }: RangeSwitchProps) {
  return (
    /* aria-pressed rather than role="tablist": there are no panels to switch
       between, only one chart that redraws, and Tab through three buttons is a
       contract this can actually keep. */
    <div
      role="group"
      aria-label="Chart range"
      className="flex items-center gap-1 rounded-xl border border-hairline bg-surface-muted p-1"
    >
      {RANGE_OPTIONS.map((option) => {
        const isActive = option.value === value

        return (
          <button
            key={option.value}
            type="button"
            aria-pressed={isActive}
            onClick={() => onChange(option.value)}
            className={[
              'rounded-lg px-2.5 py-1 text-xs font-medium whitespace-nowrap transition-colors duration-150',
              isActive
                ? 'bg-surface text-neutral-900 shadow-sm'
                : 'text-neutral-600 hover:text-neutral-900',
            ].join(' ')}
          >
            {option.label}
          </button>
        )
      })}
    </div>
  )
}

type AnalysisOverviewProps = {
  series: Record<AnalysisRange, AnalysisPoint[]>
  className?: string
}

export function AnalysisOverview({ series, className }: AnalysisOverviewProps) {
  const [range, setRange] = useState<AnalysisRange>('this_month')
  const prefersReducedMotion = usePrefersReducedMotion()

  const points = series[range]
  const hasPoints = points.length > 0
  const total = points.reduce((sum, point) => sum + point.analyses, 0)
  const values = points.map((point) => point.analyses)
  const lowest = hasPoints ? Math.min(...values) : 0
  const highest = hasPoints ? Math.max(...values) : 0
  const firstLabel = points[0]?.label ?? ''
  const lastLabel = points[points.length - 1]?.label ?? ''

  return (
    <Panel title="Analysis Overview" description="Analyses completed, by day" className={className}>
      {/* The range switch sits with the total rather than in the panel header. Two
          reasons: it belongs beside the number it changes, and in the header it would
          fight a 17-character title for 300px on a phone — here the row just wraps.
          It also stays outside the empty branch, so a range with no data is not a
          dead end. */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
          {hasPoints ? (
            <>
              <p className="font-display text-2xl font-semibold tracking-tight text-neutral-900 tabular-nums">
                {formatCount(total)}
              </p>
              <p className="text-xs text-neutral-500">
                analyses, {firstLabel} – {lastLabel}
              </p>
            </>
          ) : (
            <p className="text-sm text-neutral-500">Nothing recorded in this range</p>
          )}
        </div>
        <RangeSwitch value={range} onChange={setRange} />
      </div>

      {hasPoints ? (
        <div
          role="img"
          aria-label={`Area chart of analyses completed from ${firstLabel} to ${lastLabel}, between ${lowest} and ${highest} per day. ${formatCount(total)} in total.`}
          className="mt-4 h-72 w-full lg:h-80"
        >
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={points} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
              <defs>
                <linearGradient id="analysisFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={BRAND} stopOpacity={0.26} />
                  <stop offset="100%" stopColor={BRAND} stopOpacity={0} />
                </linearGradient>
              </defs>

              {/* Horizontal rules only. Vertical ones would put 31 lines behind a
                  chart whose shape is the thing being read. */}
              <CartesianGrid vertical={false} stroke={HAIRLINE} />

              <XAxis
                dataKey="label"
                tickLine={false}
                axisLine={false}
                tickMargin={8}
                minTickGap={28}
                tick={{ fontSize: 11, fill: AXIS_TEXT }}
              />
              <YAxis
                width={34}
                tickLine={false}
                axisLine={false}
                allowDecimals={false}
                tick={{ fontSize: 11, fill: AXIS_TEXT }}
              />
              <Tooltip content={<ChartTooltip />} cursor={{ stroke: HAIRLINE, strokeWidth: 1 }} />

              <Area
                type="monotone"
                dataKey="analyses"
                stroke={BRAND}
                strokeWidth={2}
                fill="url(#analysisFill)"
                dot={false}
                activeDot={{ r: 4, fill: BRAND, stroke: SURFACE, strokeWidth: 2 }}
                isAnimationActive={!prefersReducedMotion}
                animationDuration={700}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      ) : (
        <div className="mt-4 flex h-72 flex-col items-center justify-center gap-3 rounded-xl bg-surface-muted px-5 text-center lg:h-80">
          <span
            aria-hidden="true"
            className="flex size-11 items-center justify-center rounded-xl bg-surface text-neutral-500"
          >
            <BarChartIcon className="size-5" />
          </span>
          <p className="text-sm font-medium text-neutral-900">No analyses in this range</p>
          <p className="max-w-xs text-xs leading-relaxed text-neutral-500">
            Pick a wider range, or upload a tender to start one.
          </p>
        </div>
      )}
    </Panel>
  )
}
