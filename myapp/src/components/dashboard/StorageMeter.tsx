/**
 * How much of the workspace's storage is gone.
 *
 * The donut is a fixed 128px rather than a `ResponsiveContainer`, so there is no
 * measurement step and nothing to collapse if a parent's height is indefinite. A
 * gauge does not benefit from being fluid — past a certain size it is just a bigger
 * ring, and below it the centre figure stops fitting.
 *
 * The whole chart is aria-hidden. Every number it encodes is written out beside it,
 * and a ring that announced "13" with no unit would be noise rather than a second
 * route to the same fact.
 *
 * There is no colour key. Two swatches reading "Used" and "Free" would repeat what
 * the centre of the ring and the two lines beside it already say, and this panel is
 * the narrowest on the page — the first place where a fourth element stops fitting.
 */

import { Cell, Pie, PieChart } from 'recharts'
import { ROUTES } from '@/constants/routes'
import { formatGigabytes } from '@/lib/formatting'
import type { StorageUsage } from '@/models/dashboard'
import { Panel } from '@/components/dashboard/Panel'
import { PanelLink } from '@/components/dashboard/PanelLink'

/* --color-brand-500, --color-hairline, --color-surface. Literals because Recharts
   writes these straight into SVG attributes; see AnalysisOverview for the reasoning. */
const USED_FILL = '#e8151b'
const FREE_FILL = '#e6e8ec'
const SURFACE = '#ffffff'

export function StorageMeter({
  storage,
  className,
}: {
  storage: StorageUsage
  className?: string
}) {
  /* A zero total would divide by zero and render a ring that means nothing, so it
     reads as full — an unprovisioned workspace has no room in it either. */
  const usedPercent =
    storage.totalGb > 0 ? Math.round((storage.usedGb / storage.totalGb) * 100) : 100
  const freeGb = Math.max(storage.totalGb - storage.usedGb, 0)

  const slices = [
    { name: 'Used', value: storage.usedGb },
    { name: 'Free', value: freeGb },
  ]

  return (
    <Panel
      title="Storage"
      action={<PanelLink to={ROUTES.settings}>Manage</PanelLink>}
      className={className}
    >
      <div className="flex flex-1 flex-col items-center justify-center gap-6 sm:flex-row sm:gap-7">
        <div aria-hidden="true" className="relative size-32 shrink-0">
          <PieChart width={128} height={128}>
            <Pie
              data={slices}
              dataKey="value"
              cx="50%"
              cy="50%"
              innerRadius={46}
              outerRadius={62}
              startAngle={90}
              endAngle={-270}
              stroke={SURFACE}
              strokeWidth={2}
              /* No sweep-in. The ring is a static fact about an account, not a
                 trend worth animating, and it is one of two charts on the page. */
              isAnimationActive={false}
            >
              <Cell fill={USED_FILL} />
              <Cell fill={FREE_FILL} />
            </Pie>
          </PieChart>

          <div className="absolute inset-0 flex flex-col items-center justify-center">
            <span className="font-display text-xl font-semibold tracking-tight text-neutral-900 tabular-nums">
              {usedPercent}%
            </span>
            <span className="text-[0.625rem] font-semibold tracking-[0.12em] text-neutral-500 uppercase">
              Used
            </span>
          </div>
        </div>

        <div className="min-w-0 text-center sm:flex-1 sm:text-left">
          <p className="font-display text-2xl font-semibold tracking-tight text-neutral-900 tabular-nums">
            {formatGigabytes(storage.usedGb)}
          </p>
          <p className="mt-0.5 text-sm text-neutral-500">
            used of {formatGigabytes(storage.totalGb)}
          </p>
          <p className="mt-3 text-xs text-neutral-500">
            {formatGigabytes(freeGb)} still free
          </p>
        </div>
      </div>
    </Panel>
  )
}
