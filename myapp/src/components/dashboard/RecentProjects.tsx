/**
 * The five most recent tenders, with where each one has got to.
 *
 * Deliberately not a `<table>`. Four columns of tabular data is exactly what a
 * table is for, and at 375px it is exactly what a table cannot do — the choice is
 * a horizontal scrollbar, a squeeze, or a second copy of the whole list in the DOM
 * behind a `hidden md:table`. Instead every row is one flex line that stacks below
 * `sm`, and the column headings are dropped because each value already says what
 * it is: "Uploaded 15 May 2025", a status chip, and a percentage.
 *
 * The progress bar is aria-hidden. The figure beside it is the same number in text,
 * and a progressbar role here would have a screen reader announce it twice.
 */

import { Link } from 'react-router-dom'
import { ROUTES } from '@/constants/routes'
import { formatShortDate } from '@/lib/formatting'
import type { Project } from '@/models/dashboard'
import { Panel } from '@/components/dashboard/Panel'
import { PanelLink } from '@/components/dashboard/PanelLink'
import { StatusPill } from '@/components/dashboard/StatusPill'
import { FolderIcon } from '@/components/ui/icons'

function ProjectRow({ project }: { project: Project }) {
  return (
    <li>
      <Link
        /* One destination for now. When the detail route exists this becomes
           `${ROUTES.tenderAnalysis}/${project.id}` and nothing else here changes. */
        to={ROUTES.tenderAnalysis}
        className="flex flex-col gap-3 px-5 py-4 transition-colors duration-150 hover:bg-surface-muted sm:flex-row sm:items-center sm:gap-5"
      >
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold text-neutral-900">{project.name}</p>
          <p className="mt-1 text-xs text-neutral-500">
            Uploaded {formatShortDate(project.uploadedAt)}
          </p>
        </div>

        <div className="flex items-center gap-4 sm:shrink-0">
          <StatusPill status={project.status} />

          {/* Fluid below sm so the bar uses the width the stacked layout frees up;
              a fixed 8rem from sm so five bars share one baseline to compare on. */}
          <div className="flex min-w-0 flex-1 items-center gap-2.5 sm:w-32 sm:flex-none">
            <span
              aria-hidden="true"
              className="h-1.5 min-w-0 flex-1 overflow-hidden rounded-full bg-neutral-200"
            >
              <span
                className="block h-full rounded-full bg-brand-500"
                style={{ width: `${project.progress}%` }}
              />
            </span>
            <span className="w-9 shrink-0 text-right text-xs font-semibold text-neutral-700 tabular-nums">
              {project.progress}%
            </span>
          </div>
        </div>
      </Link>
    </li>
  )
}

export function RecentProjects({
  projects,
  className,
}: {
  projects: Project[]
  className?: string
}) {
  return (
    <Panel
      title="Recent Projects"
      description="Tenders you have uploaded, newest first"
      action={<PanelLink to={ROUTES.tenderAnalysis}>View all</PanelLink>}
      flush
      className={className}
    >
      {projects.length === 0 ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-3 px-5 py-12 text-center">
          <span
            aria-hidden="true"
            className="flex size-11 items-center justify-center rounded-xl bg-surface-muted text-neutral-500"
          >
            <FolderIcon className="size-5" />
          </span>
          <p className="text-sm font-medium text-neutral-900">No projects yet</p>
          <p className="max-w-xs text-xs leading-relaxed text-neutral-500">
            Upload a tender document and VR-Nexus will start an analysis for it.
          </p>
          <PanelLink to={ROUTES.documents}>Upload a document</PanelLink>
        </div>
      ) : (
        <ul className="divide-y divide-hairline">
          {projects.map((project) => (
            <ProjectRow key={project.id} project={project} />
          ))}
        </ul>
      )}
    </Panel>
  )
}
