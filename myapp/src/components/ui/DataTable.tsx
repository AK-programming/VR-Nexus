/**
 * The table every listing in the product is built from.
 *
 * The dashboard's Recent Projects deliberately is *not* a table — four fields per row
 * and no header row worth keeping means a flex list wins at 375px. The document
 * library is the opposite case: six fields, a header row that genuinely labels them,
 * and a reader who scans down one column comparing values. That is what a `<table>`
 * is for, and faking it with divs costs the row/column semantics a screen reader uses
 * to announce "Sector, Logistics" instead of just "Logistics".
 *
 * How it survives a phone: every column carries its own responsive visibility in
 * `className` (`hidden md:table-cell`), so the same markup shows two columns at 375px
 * and six at 1280px. The alternative — a card list plus a `hidden lg:table` — is two
 * copies of the same data in the DOM, which drift apart the first time someone edits
 * one of them.
 *
 * What it deliberately does not do:
 *
 *  - No row click handler. A clickable `<tr>` that also contains Delete means every
 *    button inside it needs `stopPropagation`, and forgetting once deletes a document
 *    *and* navigates away. Instead the page puts a real `<Link>` in the cell it wants
 *    clickable — one tab stop, correct middle-click, no interception.
 *  - No pagination. The server pages with limit/offset and this component sorts what
 *    it was handed; a control that pages client-side over a server-paged list shows
 *    "1-10 of 10" while there are 400 more.
 *  - No sticky header. The wrapper only scrolls horizontally and the page owns
 *    vertical scroll, so `sticky top-0` here would pin the row to the viewport and
 *    slide it under the app header.
 */

import { useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { ArrowDownIcon, ArrowUpDownIcon, ArrowUpIcon, CheckIcon } from '@/components/ui/icons'

export type SortDirection = 'asc' | 'desc'

/** What a value sorts as. `null` always sinks, in both directions — see `compare`. */
type SortableValue = string | number | null

export type Column<T> = {
  /** Stable identity, and the sort key. Not the header text: copy changes, keys should not. */
  id: string
  header: string
  /** Renders the cell. Free to return a link, a pill, an icon — anything. */
  cell: (row: T) => ReactNode
  /**
   * Makes the column sortable. Returns the value to compare, not the rendered
   * output: "8.4 MB" and "412 KB" sort wrongly as strings, and the raw byte count
   * sorts correctly. Omit for columns where an order would be meaningless.
   */
  sortValue?: (row: T) => SortableValue
  /** Applied to the `th` and every `td` — width, and the responsive hiding above. */
  className?: string
  /** Right-aligns the column. For figures, so their digits line up on the decimal. */
  numeric?: boolean
}

type DataTableProps<T> = {
  rows: T[]
  columns: Column<T>[]
  /** Identity for React keys and for selection. Must be stable across renders. */
  rowKey: (row: T) => string

  /**
   * The table's accessible name. Required rather than optional: a table with no
   * caption is announced as "table, 6 columns, 22 rows" and nothing else.
   */
  caption: string

  /** Which column the table opens sorted by. Unsorted if omitted. */
  initialSort?: { columnId: string; direction: SortDirection }

  /**
   * Turns on the checkbox column. Selection state is owned by the page, because the
   * page is what acts on it — "Train 3 selected" is a page-level button, and a
   * selection that lived in here would be invisible to it.
   */
  selectedIds?: string[]
  onSelectionChange?: (ids: string[]) => void
  /** Names each row's checkbox. Without it a screen reader reads 22 unlabelled boxes. */
  selectionLabel?: (row: T) => string

  /**
   * The trailing cell. Kept out of the column model so it can never be sorted by and
   * never gets a sort button in its header.
   */
  rowActions?: (row: T) => ReactNode

  /** Tints a row — a failed document, a row mid-request. Never the only signal. */
  rowClassName?: (row: T) => string

  /** Shown in place of the body when `rows` is empty. `TableEmptyState` fits here. */
  empty?: ReactNode
}

/**
 * Ascending order, with nulls last regardless of direction.
 *
 * Sorting by page count ascending should not open with every document that has not
 * been parsed yet. "Unknown" is not smaller than 2, it is absent, and absent belongs
 * at the end of the list either way — which is why the null checks happen before the
 * direction is applied, in `sortRows` below.
 */
function compare(a: SortableValue, b: SortableValue): number {
  if (typeof a === 'number' && typeof b === 'number') {
    return a - b
  }

  return String(a).localeCompare(String(b), 'en', { sensitivity: 'base', numeric: true })
}

function sortRows<T>(
  rows: T[],
  column: Column<T> | undefined,
  direction: SortDirection,
): T[] {
  const read = column?.sortValue

  if (!read) {
    return rows
  }

  /* A copy, because sorting the prop in place mutates the caller's array — and if
     that array came from a store, the mutation is invisible to React. Array.sort is
     stable per spec, so rows that tie keep the order they arrived in. */
  return [...rows].sort((left, right) => {
    const a = read(left)
    const b = read(right)

    const aMissing = a === null || a === ''
    const bMissing = b === null || b === ''

    if (aMissing && bMissing) {
      return 0
    }
    if (aMissing) {
      return 1
    }
    if (bMissing) {
      return -1
    }

    return direction === 'asc' ? compare(a, b) : compare(b, a)
  })
}

/**
 * The selection box.
 *
 * Not the form `Checkbox`: that one renders a description paragraph beside itself and
 * has no indeterminate state, both of which are right for a consent box and wrong for
 * a 32px table cell. Same peer-driven pattern, so the two still look like one control.
 *
 * `indeterminate` is a DOM property with no HTML attribute, so it can only be set
 * through a ref — React will not pass it through as a prop.
 */
function SelectionCheckbox({
  label,
  checked,
  indeterminate = false,
  onChange,
}: {
  label: string
  checked: boolean
  indeterminate?: boolean
  onChange: (checked: boolean) => void
}) {
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (inputRef.current) {
      inputRef.current.indeterminate = indeterminate
    }
  }, [indeterminate])

  return (
    <span className="relative inline-flex">
      <input
        ref={inputRef}
        type="checkbox"
        className="peer absolute inset-0 size-full cursor-pointer appearance-none rounded-md"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
        aria-label={label}
      />
      <span
        aria-hidden="true"
        className={[
          'flex size-4.5 items-center justify-center rounded-md border transition-all duration-150',
          'text-transparent',
          'peer-checked:border-brand-500 peer-checked:bg-brand-500 peer-checked:text-white',
          'peer-indeterminate:border-brand-500 peer-indeterminate:bg-brand-500 peer-indeterminate:text-white',
          'peer-focus-visible:ring-4 peer-focus-visible:ring-brand-500/25',
          checked || indeterminate ? '' : 'border-neutral-300 bg-surface peer-hover:border-brand-400',
        ].join(' ')}
      >
        {indeterminate && !checked ? (
          <span className="h-0.5 w-2.5 rounded-full bg-current" />
        ) : (
          <CheckIcon className="size-3" />
        )}
      </span>
    </span>
  )
}

/** The header cell for a sortable column: a real button, so Space and Enter work. */
function SortButton({
  label,
  state,
  numeric,
  onClick,
}: {
  label: string
  state: SortDirection | 'none'
  numeric: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={[
        'group flex w-full items-center gap-1.5 rounded-md text-left',
        'transition-colors hover:text-neutral-900',
        numeric ? 'justify-end' : '',
      ].join(' ')}
    >
      {label}
      {/* Both arrows when unsorted, so the header offers a direction rather than
          claiming one. Dim until it means something. */}
      {state === 'none' ? (
        <ArrowUpDownIcon className="size-3.5 shrink-0 text-neutral-400 transition-colors group-hover:text-neutral-600" />
      ) : state === 'asc' ? (
        <ArrowUpIcon className="size-3.5 shrink-0 text-brand-600" />
      ) : (
        <ArrowDownIcon className="size-3.5 shrink-0 text-brand-600" />
      )}
    </button>
  )
}

export function DataTable<T>({
  rows,
  columns,
  rowKey,
  caption,
  initialSort,
  selectedIds,
  onSelectionChange,
  selectionLabel,
  rowActions,
  rowClassName,
  empty,
}: DataTableProps<T>) {
  const [sortColumnId, setSortColumnId] = useState(initialSort?.columnId ?? null)
  const [direction, setDirection] = useState<SortDirection>(initialSort?.direction ?? 'asc')

  const selectable = Boolean(selectedIds && onSelectionChange)
  const selected = useMemo(() => new Set(selectedIds ?? []), [selectedIds])

  const sortColumn = columns.find((column) => column.id === sortColumnId)
  const sorted = useMemo(
    () => sortRows(rows, sortColumn, direction),
    [rows, sortColumn, direction],
  )

  /* First click on a new column sorts ascending; clicking the active column flips it.
     Descending-first would be right for a date column and wrong for a name column,
     and a per-column preference is a knob nobody would ever set. */
  function toggleSort(columnId: string) {
    if (columnId === sortColumnId) {
      setDirection((current) => (current === 'asc' ? 'desc' : 'asc'))
      return
    }

    setSortColumnId(columnId)
    setDirection('asc')
  }

  const allKeys = sorted.map(rowKey)
  const selectedHere = allKeys.filter((key) => selected.has(key))
  const allSelected = allKeys.length > 0 && selectedHere.length === allKeys.length
  const someSelected = selectedHere.length > 0 && !allSelected

  /* Select-all covers what is on screen, not what exists. With a filter applied,
     ticking the header and pressing Delete should not reach the rows a person
     currently cannot see. */
  function toggleAll(next: boolean) {
    onSelectionChange?.(next ? allKeys : [])
  }

  function toggleOne(key: string, next: boolean) {
    if (next) {
      onSelectionChange?.([...selected, key])
      return
    }

    onSelectionChange?.([...selected].filter((id) => id !== key))
  }

  const columnCount = columns.length + (selectable ? 1 : 0) + (rowActions ? 1 : 0)

  const headerCell = 'px-4 py-3 text-xs font-semibold tracking-wide text-neutral-600'
  const bodyCell = 'px-4 py-3 align-middle text-sm text-neutral-700'

  return (
    <div className="w-full overflow-x-auto">
      <table className="w-full min-w-full border-collapse text-left">
        {/* Visually hidden rather than absent: it is the table's name, not a title —
            the Panel above already shows a heading and repeating it would be noise. */}
        <caption className="sr-only">{caption}</caption>

        <thead>
          <tr className="border-b border-hairline bg-surface-muted">
            {selectable ? (
              <th scope="col" className={`${headerCell} w-11`}>
                <SelectionCheckbox
                  label={allSelected ? 'Clear selection' : 'Select all rows'}
                  checked={allSelected}
                  indeterminate={someSelected}
                  onChange={toggleAll}
                />
              </th>
            ) : null}

            {columns.map((column) => {
              const isSorted = column.id === sortColumnId
              const state: SortDirection | 'none' = isSorted ? direction : 'none'

              return (
                <th
                  key={column.id}
                  scope="col"
                  aria-sort={
                    isSorted ? (direction === 'asc' ? 'ascending' : 'descending') : 'none'
                  }
                  className={[
                    headerCell,
                    column.numeric ? 'text-right' : '',
                    column.className ?? '',
                  ].join(' ')}
                >
                  {column.sortValue ? (
                    <SortButton
                      label={column.header}
                      state={state}
                      numeric={Boolean(column.numeric)}
                      onClick={() => toggleSort(column.id)}
                    />
                  ) : (
                    column.header
                  )}
                </th>
              )
            })}

            {rowActions ? (
              <th scope="col" className={`${headerCell} w-px text-right`}>
                <span className="sr-only">Actions</span>
              </th>
            ) : null}
          </tr>
        </thead>

        <tbody className="divide-y divide-hairline">
          {sorted.length === 0 ? (
            <tr>
              <td colSpan={columnCount} className="px-4 py-12">
                {empty}
              </td>
            </tr>
          ) : (
            sorted.map((row) => {
              const key = rowKey(row)
              const isSelected = selected.has(key)

              return (
                <tr
                  key={key}
                  className={[
                    'transition-colors duration-150',
                    isSelected ? 'bg-selected' : 'hover:bg-surface-muted',
                    rowClassName?.(row) ?? '',
                  ].join(' ')}
                >
                  {selectable ? (
                    <td className={`${bodyCell} w-11`}>
                      <SelectionCheckbox
                        label={selectionLabel?.(row) ?? `Select row ${key}`}
                        checked={isSelected}
                        onChange={(next) => toggleOne(key, next)}
                      />
                    </td>
                  ) : null}

                  {columns.map((column) => (
                    <td
                      key={column.id}
                      className={[
                        bodyCell,
                        column.numeric ? 'text-right tabular-nums' : '',
                        column.className ?? '',
                      ].join(' ')}
                    >
                      {column.cell(row)}
                    </td>
                  ))}

                  {rowActions ? (
                    <td className={`${bodyCell} text-right whitespace-nowrap`}>
                      {rowActions(row)}
                    </td>
                  ) : null}
                </tr>
              )
            })
          )}
        </tbody>
      </table>
    </div>
  )
}

/**
 * The "nothing here" block, shaped like the dashboard's empty panels so a library
 * with no documents and a project list with no projects read as the same product.
 *
 * An empty state is an instruction, not an apology: it names what is missing and
 * offers the one action that fixes it.
 */
export function TableEmptyState({
  icon,
  title,
  description,
  action,
}: {
  icon: ReactNode
  title: string
  description: string
  action?: ReactNode
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 text-center">
      <span
        aria-hidden="true"
        className="flex size-11 items-center justify-center rounded-xl bg-surface-muted text-neutral-500"
      >
        {icon}
      </span>
      <p className="text-sm font-medium text-neutral-900">{title}</p>
      <p className="max-w-sm text-xs leading-relaxed text-neutral-500">{description}</p>
      {action}
    </div>
  )
}
