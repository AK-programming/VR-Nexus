/**
 * The Excel export customizer — client requirement (Users admin follow-up):
 * "set excel sheet to customize ... what column they want what they delete
 * and what they mean they will set there format ... implement that changes
 * and then paste on the folder."
 *
 * Opened from the tender review workspace, either from the "Is this format
 * OK?" prompt shown once a tender reaches Ready for review, or any time
 * from the "Customize Excel format" toolbar button. Two save targets, per
 * the client's own answer:
 *   - "Save for this tender" (always) — PUTs the per-tender override, which
 *     the server applies immediately by regenerating the output zip.
 *   - "Also use this as my default" (checkbox) — additionally PUTs the
 *     account default, so future tenders start from this same shape.
 *
 * Column customization is deliberately scoped to the fixed columns
 * (FIXED_EXCEL_COLUMNS) plus the user's own added blank columns — show/hide,
 * reorder, rename, and add. Per-tender "extra fields" (Requirement.extra_fields)
 * are not exposed here: they vary per tender by definition, so a saved
 * template naming one would silently stop applying to the next tender that
 * doesn't have it (the backend already tolerates that gracefully — see
 * _build_template_columns — this UI just doesn't surface something that
 * inherently can't be "the reusable default").
 */

import { useEffect, useRef, useState } from 'react'
import {
  FIXED_EXCEL_COLUMNS,
  emptyExcelTemplate,
  type ExcelColumnConfig,
  type ExcelTemplate,
} from '@/models/tenders'
import { ActionButton, IconAction } from '@/components/ui/ActionButton'
import { AlertMessage } from '@/components/feedback/AlertMessage'
import {
  ArrowDownIcon,
  ArrowUpIcon,
  CloseIcon,
  PlusIcon,
  SettingsIcon,
} from '@/components/ui/icons'

type Column = Omit<ExcelColumnConfig, 'label'> & { label: string; defaultLabel: string }

function toEditableColumns(template: ExcelTemplate | null): Column[] {
  if (template && template.columns.length > 0) {
    return template.columns.map((c) => {
      const known = FIXED_EXCEL_COLUMNS.find((f) => f.key === c.key)
      return {
        key: c.key,
        label: c.label ?? known?.label ?? c.key,
        visible: c.visible,
        defaultLabel: known?.label ?? c.key,
      }
    })
  }
  return FIXED_EXCEL_COLUMNS.map((f) => ({
    key: f.key,
    label: f.label,
    visible: true,
    defaultLabel: f.label,
  }))
}

type ExcelTemplateCustomizerProps = {
  open: boolean
  /** The template to start from — this tender's override if it has one, else
   *  the account default, else null (platform default). Resolved by the
   *  caller so this component doesn't need to know that precedence. */
  initialTemplate: ExcelTemplate | null
  busy: boolean
  error: string | null
  onCancel: () => void
  /** `saveAsDefault` tells the caller whether to also PUT the account default. */
  onSave: (template: ExcelTemplate, saveAsDefault: boolean) => void
  onResetToDefault: () => void
}

export function ExcelTemplateCustomizer({
  open,
  initialTemplate,
  busy,
  error,
  onCancel,
  onSave,
  onResetToDefault,
}: ExcelTemplateCustomizerProps) {
  const dialogRef = useRef<HTMLDialogElement>(null)
  const [columns, setColumns] = useState<Column[]>(() => toEditableColumns(initialTemplate))
  const [deleteEmptyRows, setDeleteEmptyRows] = useState(initialTemplate?.delete_empty_rows ?? false)
  const [addedColumns, setAddedColumns] = useState<string[]>(initialTemplate?.added_columns ?? [])
  const [newColumnName, setNewColumnName] = useState('')
  const [saveAsDefault, setSaveAsDefault] = useState(false)

  /* Re-seed local edit state every time the dialog opens against a (possibly
     different) starting template — a stale in-progress edit from the last
     open should never bleed into this one. */
  useEffect(() => {
    if (open) {
      setColumns(toEditableColumns(initialTemplate))
      setDeleteEmptyRows(initialTemplate?.delete_empty_rows ?? false)
      setAddedColumns(initialTemplate?.added_columns ?? [])
      setNewColumnName('')
      setSaveAsDefault(false)
    }
  }, [open, initialTemplate])

  useEffect(() => {
    const dialog = dialogRef.current
    if (!dialog) return
    if (open && !dialog.open) dialog.showModal()
    else if (!open && dialog.open) dialog.close()
  }, [open])

  function move(index: number, direction: -1 | 1) {
    setColumns((prev) => {
      const next = [...prev]
      const target = index + direction
      if (target < 0 || target >= next.length) return prev
      ;[next[index], next[target]] = [next[target], next[index]]
      return next
    })
  }

  function toggleVisible(index: number) {
    setColumns((prev) => prev.map((c, i) => (i === index ? { ...c, visible: !c.visible } : c)))
  }

  function rename(index: number, label: string) {
    setColumns((prev) => prev.map((c, i) => (i === index ? { ...c, label } : c)))
  }

  function addColumn() {
    const name = newColumnName.trim()
    if (!name || addedColumns.includes(name)) return
    setAddedColumns((prev) => [...prev, name])
    setNewColumnName('')
  }

  function removeAddedColumn(name: string) {
    setAddedColumns((prev) => prev.filter((c) => c !== name))
  }

  function handleSave() {
    const template: ExcelTemplate = {
      columns: columns.map(({ key, label, visible, defaultLabel }) => ({
        key,
        label: label.trim() && label !== defaultLabel ? label.trim() : null,
        visible,
      })),
      delete_empty_rows: deleteEmptyRows,
      added_columns: addedColumns,
    }
    onSave(template, saveAsDefault)
  }

  const visibleCount = columns.filter((c) => c.visible).length

  return (
    <dialog
      ref={dialogRef}
      onCancel={(event) => {
        event.preventDefault()
        onCancel()
      }}
      aria-labelledby="excel-template-title"
      className={[
        'm-auto w-[calc(100%-2rem)] max-w-2xl rounded-2xl border border-hairline bg-surface p-0',
        'shadow-panel backdrop:bg-ink-950/40',
      ].join(' ')}
    >
      <div className="flex items-start justify-between gap-4 border-b border-hairline p-5 sm:p-6">
        <div className="flex items-start gap-3">
          <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-brand-50 text-brand-700">
            <SettingsIcon className="size-5" />
          </span>
          <div>
            <h2 id="excel-template-title" className="font-display text-base font-semibold text-neutral-900">
              Customize the Excel format
            </h2>
            <p className="mt-1 text-sm leading-relaxed text-neutral-600">
              Choose which columns appear, their order and labels, whether empty rows are
              dropped, and any extra blank columns for your own notes.
            </p>
          </div>
        </div>
        <button
          type="button"
          onClick={onCancel}
          aria-label="Close"
          className="rounded-lg p-1.5 text-neutral-400 transition-colors hover:bg-surface-muted hover:text-neutral-700"
        >
          <CloseIcon className="size-4" />
        </button>
      </div>

      <div className="max-h-[65vh] overflow-y-auto p-5 sm:p-6">
        {error ? (
          <AlertMessage tone="error" title="That did not save">
            {error}
          </AlertMessage>
        ) : null}

        <div className="mt-1 flex flex-col divide-y divide-hairline rounded-xl border border-hairline">
          {columns.map((col, index) => (
            <div key={col.key} className="flex items-center gap-2 px-3 py-2">
              <input
                type="checkbox"
                checked={col.visible}
                onChange={() => toggleVisible(index)}
                aria-label={`Show ${col.defaultLabel} column`}
                className="size-4 shrink-0 rounded border-neutral-300 text-brand-600"
              />
              <input
                type="text"
                value={col.label}
                onChange={(event) => rename(index, event.target.value)}
                disabled={!col.visible}
                className={[
                  'min-w-0 flex-1 rounded-lg border border-transparent bg-transparent px-2 py-1 text-sm',
                  'focus:border-hairline focus:bg-surface-muted focus:outline-none',
                  !col.visible ? 'text-neutral-400 line-through' : 'text-neutral-800',
                ].join(' ')}
              />
              <div className="flex shrink-0 items-center gap-0.5">
                <IconAction
                  label="Move up"
                  icon={<ArrowUpIcon />}
                  onClick={() => move(index, -1)}
                  disabled={index === 0}
                />
                <IconAction
                  label="Move down"
                  icon={<ArrowDownIcon />}
                  onClick={() => move(index, 1)}
                  disabled={index === columns.length - 1}
                />
              </div>
            </div>
          ))}
        </div>
        <p className="mt-2 text-xs text-neutral-500">
          {visibleCount} of {columns.length} columns will appear in the sheet.
        </p>

        <div className="mt-5 flex items-center gap-2.5">
          <input
            type="checkbox"
            id="delete-empty-rows"
            checked={deleteEmptyRows}
            onChange={(event) => setDeleteEmptyRows(event.target.checked)}
            className="size-4 rounded border-neutral-300 text-brand-600"
          />
          <label htmlFor="delete-empty-rows" className="text-sm text-neutral-700">
            Delete rows that are empty across every visible column
          </label>
        </div>

        <div className="mt-5">
          <p className="text-sm font-medium text-neutral-800">Your own added columns</p>
          <p className="mt-0.5 text-xs text-neutral-500">
            Blank columns appended at the end for notes you fill in yourself — VR-Nexus
            doesn't populate these.
          </p>
          {addedColumns.length > 0 ? (
            <ul className="mt-2 flex flex-wrap gap-1.5">
              {addedColumns.map((name) => (
                <li
                  key={name}
                  className="inline-flex items-center gap-1 rounded-full border border-hairline bg-surface-muted py-1 pl-2.5 pr-1 text-xs text-neutral-700"
                >
                  {name}
                  <button
                    type="button"
                    onClick={() => removeAddedColumn(name)}
                    aria-label={`Remove ${name} column`}
                    className="rounded-full p-0.5 text-neutral-400 hover:bg-surface hover:text-neutral-700"
                  >
                    <CloseIcon className="size-3" />
                  </button>
                </li>
              ))}
            </ul>
          ) : null}
          <div className="mt-2 flex items-center gap-2">
            <input
              type="text"
              value={newColumnName}
              onChange={(event) => setNewColumnName(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') {
                  event.preventDefault()
                  addColumn()
                }
              }}
              placeholder="e.g. Internal Owner"
              className="min-w-0 flex-1 rounded-lg border border-hairline bg-surface px-3 py-1.5 text-sm placeholder:text-neutral-400 focus:border-brand-400 focus:outline-none"
            />
            <ActionButton
              variant="secondary"
              size="sm"
              leadingIcon={<PlusIcon />}
              onClick={addColumn}
            >
              Add column
            </ActionButton>
          </div>
        </div>

        <div className="mt-5 flex items-center gap-2.5 border-t border-hairline pt-4">
          <input
            type="checkbox"
            id="save-as-default"
            checked={saveAsDefault}
            onChange={(event) => setSaveAsDefault(event.target.checked)}
            className="size-4 rounded border-neutral-300 text-brand-600"
          />
          <label htmlFor="save-as-default" className="text-sm text-neutral-700">
            Also use this as my default format for every tender
          </label>
        </div>
      </div>

      <div className="flex flex-col-reverse gap-2 border-t border-hairline px-5 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-6">
        <button
          type="button"
          onClick={onResetToDefault}
          disabled={busy}
          className="text-xs font-medium text-neutral-500 underline-offset-2 hover:text-neutral-800 hover:underline disabled:pointer-events-none disabled:opacity-50"
        >
          Reset to the platform default
        </button>
        <div className="flex gap-2">
          <ActionButton variant="secondary" onClick={onCancel} disabled={busy}>
            Cancel
          </ActionButton>
          <ActionButton variant="primary" onClick={handleSave} disabled={busy}>
            {busy ? 'Saving…' : 'Save & apply'}
          </ActionButton>
        </div>
      </div>
    </dialog>
  )
}

export { emptyExcelTemplate }
