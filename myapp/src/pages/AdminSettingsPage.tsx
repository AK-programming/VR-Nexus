/**
 * API Settings — admin-only. Client follow-up request: an expired or
 * compromised Anthropic API key was "a big issue" with no way to fix it
 * short of editing the server's .env and restarting it, and the estimated
 * cost on the API Usage page had no way to stay correct if Anthropic's real
 * prices changed. Extended by a later follow-up: the admin wanted to point a
 * task at OpenAI or Gemini instead of Anthropic, entering that provider's
 * own key and picking its model. This screen is the fix for all of that, at
 * runtime, no restart:
 *
 *   - Change the API key for any of the three supported providers
 *     (Anthropic, OpenAI, Google Gemini). Takes effect for the very next
 *     call routed to that provider, on every worker (see
 *     backend/app/services/app_settings.py).
 *   - Pick which provider, and which of that provider's models, each kind
 *     of call actually uses (tender/library extraction vs. the Evidence
 *     Library's grounded Ask), from among the models priced in the table
 *     below. Also takes effect on the very next call — see
 *     app_settings.py's MODEL_TASKS.
 *   - View and hand-edit the per-model pricing table the API Usage page's
 *     cost estimates are built from, plus a best-effort "Refresh from
 *     Anthropic" that tries to read current prices off Anthropic's own
 *     public pricing page (Anthropic-only — OpenAI and Gemini have no
 *     equivalent scrape here, so those rows are edited by hand). Anthropic
 *     has no pricing API, so this is a page scrape and is labelled as
 *     best-effort rather than authoritative — manual editing always works
 *     regardless of what Refresh finds.
 *
 * Reachable only via ROUTES.adminSettings, wrapped in RequireAdmin
 * (@/app/guards.tsx) the same way AdminUsersPage is — and, as with that
 * page, the client-side guard is only half the story: every route here is
 * behind require_role(UserRole.ADMIN) on the backend.
 */

import { useEffect, useMemo, useState } from 'react'
import type { AppSettings, ModelPricing, ModelTask, Provider, TaskModelSelection } from '@/models'
import {
  MODEL_TASKS,
  MODEL_TASK_DESCRIPTIONS,
  MODEL_TASK_LABELS,
  PROVIDER_LABELS,
  PROVIDERS,
} from '@/models'
import { adminService } from '@/services/adminService'
import { useAsyncData } from '@/hooks/useAsyncData'
import { errorMessage } from '@/lib/apiClient'
import { formatRelativeTime } from '@/lib/formatting'
import { Panel } from '@/components/dashboard/Panel'
import { ActionButton } from '@/components/ui/ActionButton'
import { ErrorBlock, LoadingRows } from '@/components/feedback/DataState'
import {
  AlertTriangleIcon,
  CheckCircleIcon,
  DollarSignIcon,
  EyeIcon,
  EyeOffIcon,
  InfoIcon,
  LockIcon,
  RefreshIcon,
  SparklesIcon,
} from '@/components/ui/icons'

const API_KEY_SOURCE_LABEL: Record<string, string> = {
  settings: 'Set here, in Settings',
  env: "Set in the server's .env (default)",
  none: 'Not configured',
}

export function AdminSettingsPage() {
  const data = useAsyncData((signal) => adminService.getSettings(signal), [])

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-4">
      <header>
        <h1 className="font-display text-2xl font-semibold tracking-tight text-neutral-900 sm:text-3xl">
          API Settings
        </h1>
        <p className="mt-1 text-sm text-neutral-500">
          Each provider's API key, which provider and model each task uses, and the per-model
          pricing used to estimate cost.
        </p>
      </header>

      {data.status === 'error' && data.data === null ? (
        <ErrorBlock
          title="Settings could not be loaded"
          message={data.error ?? 'The request did not complete.'}
          offline={data.offline}
          onRetry={data.refetch}
        />
      ) : data.status === 'loading' && data.data === null ? (
        <Panel title="API Settings" flush>
          <LoadingRows rows={4} label="Loading settings" />
        </Panel>
      ) : data.data ? (
        <>
          <ApiKeyPanel settings={data.data} onSaved={data.refetch} />
          <ModelSelectionPanel settings={data.data} onSaved={data.refetch} />
          <PricingPanel settings={data.data} onSaved={data.refetch} />
        </>
      ) : null}
    </div>
  )
}

/**
 * Which provider and model each task calls. Client follow-up: the admin
 * wanted to move extraction off Haiku (or onto a different Haiku/Sonnet id)
 * without a .env edit, the same runtime-override the API key and pricing
 * above already get — and later, to point a task at OpenAI or Gemini
 * instead, once that provider's key is configured below. See
 * backend/app/services/app_settings.py's MODEL_TASKS and PROVIDERS.
 *
 * The model dropdown's options come from the pricing table, grouped by
 * provider (`settings.models_by_provider`) — a model has to have a price
 * entry (below) before this app can estimate what calling it costs, so a
 * provider with no priced models yet shows an empty dropdown until one is
 * added in the pricing panel.
 */
function ModelSelectionPanel({
  settings,
  onSaved,
}: {
  settings: AppSettings
  onSaved: () => void
}) {
  const [selection, setSelection] = useState<Partial<Record<ModelTask, TaskModelSelection>>>(
    settings.model_overrides,
  )
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [justSaved, setJustSaved] = useState(false)

  const dirty = MODEL_TASKS.some((task) => {
    const current = selection[task]
    const saved = settings.model_overrides[task]
    return current?.provider !== saved?.provider || current?.model !== saved?.model
  })

  function setTaskProvider(task: ModelTask, provider: Provider) {
    setSelection((current) => {
      const models = settings.models_by_provider[provider] ?? []
      const existing = current[task]
      // Switching provider almost always invalidates the previously chosen
      // model id (an OpenAI id means nothing to Anthropic's API), so fall
      // back to that provider's first priced model rather than carrying
      // over a selection that would fail on the very next call.
      const model =
        existing?.provider === provider ? existing.model : (models[0] ?? existing?.model ?? '')
      return { ...current, [task]: { provider, model } }
    })
    setJustSaved(false)
  }

  function setTaskModel(task: ModelTask, modelId: string) {
    setSelection((current) => {
      const provider = current[task]?.provider ?? 'anthropic'
      return { ...current, [task]: { provider, model: modelId } }
    })
    setJustSaved(false)
  }

  async function handleSave() {
    const complete = MODEL_TASKS.every((task) => selection[task]?.model)
    if (!complete) {
      setError('Pick a model for every task before saving.')
      return
    }
    setSaving(true)
    setError(null)
    try {
      const updated = await adminService.setModelOverrides({
        model_overrides: selection as Record<ModelTask, TaskModelSelection>,
      })
      setSelection(updated.model_overrides)
      setJustSaved(true)
      onSaved()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Panel
      collapsible
      defaultOpen
      title="Model selection"
      description="Which provider and model each kind of call uses — change without a restart."
    >
      <div className="flex flex-col divide-y divide-hairline">
        {MODEL_TASKS.map((task) => {
          const overridden = settings.overridden_model_tasks.includes(task)
          const current = selection[task] ?? settings.model_overrides[task]
          const provider = current?.provider ?? 'anthropic'
          const modelOptions = settings.models_by_provider[provider] ?? []
          return (
            <div key={task} className="flex flex-col gap-2 py-3 first:pt-0 last:pb-0">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="flex items-center gap-1.5 text-sm font-medium text-neutral-900">
                    <SparklesIcon className="size-3.5 shrink-0 text-neutral-400" />
                    {MODEL_TASK_LABELS[task]}
                    {overridden ? (
                      <span className="rounded-full bg-brand-50 px-1.5 py-0.5 text-[0.6rem] font-medium text-brand-700">
                        edited
                      </span>
                    ) : (
                      <span className="rounded-full bg-surface-muted px-1.5 py-0.5 text-[0.6rem] font-medium text-neutral-500">
                        default
                      </span>
                    )}
                  </p>
                  <p className="mt-0.5 text-xs text-neutral-500">
                    {MODEL_TASK_DESCRIPTIONS[task]}
                  </p>
                </div>
              </div>
              <div className="flex flex-col gap-2 sm:flex-row">
                <select
                  value={provider}
                  onChange={(event) => setTaskProvider(task, event.target.value as Provider)}
                  className="h-9 w-full max-w-[10rem] rounded-lg border border-hairline bg-field px-2.5 text-xs text-neutral-900 outline-none transition-colors hover:border-neutral-300 focus:border-brand-400 focus:bg-surface focus:ring-4 focus:ring-brand-500/15"
                >
                  {PROVIDERS.map((p) => (
                    <option key={p} value={p}>
                      {PROVIDER_LABELS[p]}
                    </option>
                  ))}
                </select>
                <select
                  value={current?.model ?? ''}
                  onChange={(event) => setTaskModel(task, event.target.value)}
                  className="h-9 w-full max-w-xs rounded-lg border border-hairline bg-field px-2.5 font-mono text-xs text-neutral-900 outline-none transition-colors hover:border-neutral-300 focus:border-brand-400 focus:bg-surface focus:ring-4 focus:ring-brand-500/15"
                >
                  {modelOptions.length === 0 ? (
                    <option value="">No priced models for this provider yet</option>
                  ) : (
                    modelOptions.map((modelId) => (
                      <option key={modelId} value={modelId}>
                        {modelId}
                      </option>
                    ))
                  )}
                </select>
              </div>
            </div>
          )
        })}
      </div>

      {error ? (
        <p className="mt-3 rounded-lg bg-rose-50 px-3 py-2 text-xs text-rose-700">{error}</p>
      ) : null}
      {justSaved && !dirty ? (
        <p className="mt-3 inline-flex items-center gap-1.5 rounded-lg bg-emerald-50 px-3 py-2 text-xs text-emerald-700">
          <CheckCircleIcon className="size-3.5" />
          Model selection saved and active.
        </p>
      ) : null}

      <div className="mt-4 flex items-center gap-2">
        <ActionButton variant="primary" disabled={saving || !dirty} onClick={() => void handleSave()}>
          {saving ? 'Saving…' : 'Save model selection'}
        </ActionButton>
        {dirty ? <span className="text-xs text-neutral-500">Unsaved changes</span> : null}
      </div>
    </Panel>
  )
}

/**
 * One panel, one row per provider — each row is its own independent rotate
 * key / revert flow, working off `settings.provider_keys[provider]` rather
 * than the old single `api_key_*` fields.
 */
function ApiKeyPanel({
  settings,
  onSaved,
}: {
  settings: AppSettings
  onSaved: () => void
}) {
  return (
    <Panel
      collapsible
      defaultOpen
      title="API keys"
      description="One key per provider — used for whichever task is pointed at it below."
    >
      <div className="flex flex-col divide-y divide-hairline">
        {PROVIDERS.map((provider) => (
          <div key={provider} className="py-4 first:pt-0 last:pb-0">
            <ProviderKeyRow provider={provider} settings={settings} onSaved={onSaved} />
          </div>
        ))}
      </div>
    </Panel>
  )
}

function ProviderKeyRow({
  provider,
  settings,
  onSaved,
}: {
  provider: Provider
  settings: AppSettings
  onSaved: () => void
}) {
  const status = settings.provider_keys[provider]
  const [draft, setDraft] = useState('')
  const [reveal, setReveal] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [justSaved, setJustSaved] = useState(false)

  async function handleSave() {
    if (!draft.trim()) {
      return
    }
    setSaving(true)
    setError(null)
    try {
      await adminService.setApiKey(provider, { api_key: draft.trim() })
      setDraft('')
      setJustSaved(true)
      onSaved()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  async function handleRevert() {
    setSaving(true)
    setError(null)
    try {
      await adminService.clearApiKey(provider)
      onSaved()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  const placeholder =
    provider === 'anthropic' ? 'sk-ant-...' : provider === 'openai' ? 'sk-...' : 'AIza...'

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm font-medium text-neutral-900">{PROVIDER_LABELS[provider]}</p>
        <div className="flex items-center gap-3">
          {status?.configured ? (
            <span className="inline-flex items-center gap-1.5 text-xs font-medium text-emerald-700">
              <CheckCircleIcon className="size-3.5" />
              Configured
            </span>
          ) : (
            <span className="inline-flex items-center gap-1.5 text-xs font-medium text-rose-700">
              <AlertTriangleIcon className="size-3.5" />
              Not configured
            </span>
          )}
        </div>
      </div>
      <p className="text-xs text-neutral-500">
        {status ? (API_KEY_SOURCE_LABEL[status.source] ?? status.source) : ''}
        {status?.masked ? ` — ${status.masked}` : ''}
      </p>

      <div className="flex flex-col gap-2 sm:flex-row">
        <div className="relative flex-1">
          <input
            // Chrome ignores a bare autoComplete="off" on type="password"
            // inputs (deliberately, since 2018 - it decided sites were
            // abusing "off" to fight password managers) and will instead
            // autofill the page's saved LOGIN credentials into this field,
            // because a masked input with no other signal reads to Chrome's
            // heuristics as "this is a login password box". That's exactly
            // what happened here: the admin's own account password
            // (@ibrahim4321) got autofilled into the Anthropic key field,
            // silently saved as the "API key", and every extraction call
            // failed with a 401 "Invalid Anthropic API Key" - a key that was
            // never actually a key. "new-password" is the value Chrome
            // actually honours for "do not autofill a saved login here"; the
            // data-* attributes are the equivalent opt-outs for 1Password,
            // LastPass and Bitwarden, whose own heuristics aren't governed by
            // autoComplete at all. A unique id/name (instead of none) also
            // removes one more signal Chrome's matcher was using.
            id={`api-key-${provider}`}
            name={`api-key-${provider}`}
            type={reveal ? 'text' : 'password'}
            value={draft}
            onChange={(event) => {
              setDraft(event.target.value)
              setJustSaved(false)
            }}
            placeholder={placeholder}
            autoComplete="new-password"
            data-lpignore="true"
            data-1p-ignore="true"
            data-bwignore="true"
            spellCheck={false}
            className="h-10 w-full rounded-xl border border-hairline bg-surface px-3.5 pr-10 font-mono text-sm text-neutral-900 outline-none transition-colors focus:border-brand-400 focus:ring-4 focus:ring-brand-500/15"
          />
          <button
            type="button"
            onClick={() => setReveal((value) => !value)}
            aria-label={reveal ? 'Hide key' : 'Show key'}
            className="absolute inset-y-0 right-0 flex w-9 items-center justify-center text-neutral-400 hover:text-neutral-700"
          >
            {reveal ? <EyeOffIcon className="size-4" /> : <EyeIcon className="size-4" />}
          </button>
        </div>
        <ActionButton
          variant="primary"
          leadingIcon={<LockIcon />}
          disabled={saving || !draft.trim()}
          onClick={() => void handleSave()}
        >
          {saving ? 'Saving…' : 'Save key'}
        </ActionButton>
      </div>

      {justSaved ? (
        <p className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-50 px-3 py-2 text-xs text-emerald-700">
          <CheckCircleIcon className="size-3.5" />
          New key saved and active.
        </p>
      ) : null}
      {error ? (
        <p className="rounded-lg bg-rose-50 px-3 py-2 text-xs text-rose-700">{error}</p>
      ) : null}

      {status?.source === 'settings' ? (
        <div>
          <ActionButton variant="secondary" size="sm" disabled={saving} onClick={() => void handleRevert()}>
            Revert to .env key
          </ActionButton>
        </div>
      ) : null}
    </div>
  )
}

function PricingPanel({
  settings,
  onSaved,
}: {
  settings: AppSettings
  onSaved: () => void
}) {
  const [rows, setRows] = useState<Record<string, ModelPricing>>(settings.pricing)
  const [dirty, setDirty] = useState(false)
  const [saving, setSaving] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [refreshMessage, setRefreshMessage] = useState<{ ok: boolean; text: string } | null>(null)

  useEffect(() => {
    if (!dirty) {
      setRows(settings.pricing)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [settings.pricing])

  const modelIds = useMemo(() => Object.keys(rows).sort(), [rows])

  function updateRate(modelId: string, field: 'input' | 'output', value: string) {
    const parsed = Number(value)
    setDirty(true)
    setRows((current) => ({
      ...current,
      [modelId]: { ...current[modelId], [field]: Number.isFinite(parsed) ? parsed : 0 },
    }))
  }

  async function handleSave() {
    setSaving(true)
    setError(null)
    try {
      const updated = await adminService.setPricing({ pricing: rows })
      setRows(updated.pricing)
      setDirty(false)
      onSaved()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  async function handleRefresh() {
    setRefreshing(true)
    setError(null)
    setRefreshMessage(null)
    try {
      const result = await adminService.refreshPricing()
      setRefreshMessage({ ok: result.success, text: result.message })
      if (result.success) {
        const updated = await adminService.getSettings()
        setRows(updated.pricing)
        setDirty(false)
      }
      onSaved()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setRefreshing(false)
    }
  }

  return (
    <Panel
      collapsible
      defaultOpen
      title="Model pricing"
      description="USD per million tokens, used to estimate cost on the API Usage page."
      action={
        <ActionButton
          variant="secondary"
          size="sm"
          leadingIcon={<RefreshIcon />}
          disabled={refreshing}
          onClick={() => void handleRefresh()}
        >
          {refreshing ? 'Refreshing…' : 'Refresh from Anthropic'}
        </ActionButton>
      }
    >
      <p className="mb-3 flex items-start gap-2 rounded-lg bg-surface-muted px-3 py-2 text-xs text-neutral-600">
        <InfoIcon className="mt-0.5 size-3.5 shrink-0" />
        <span>
          "Refresh" only reads Anthropic's public pricing page — OpenAI and Gemini rows are edited
          by hand below. Anthropic doesn't publish a pricing API either, so even that refresh is a
          best-effort page scrape — it can come back having found nothing to update if the page
          layout doesn't match what it looks for. Editing the numbers below by hand always works.
        </span>
      </p>

      {refreshMessage ? (
        <p
          className={[
            'mb-3 rounded-lg px-3 py-2 text-xs',
            refreshMessage.ok ? 'bg-emerald-50 text-emerald-700' : 'bg-amber-50 text-amber-800',
          ].join(' ')}
        >
          {refreshMessage.text}
        </p>
      ) : null}
      {settings.last_pricing_refresh_at ? (
        <p className="mb-3 text-xs text-neutral-500">
          Last refresh attempt: {formatRelativeTime(settings.last_pricing_refresh_at)}
          {settings.last_pricing_refresh_result ? ` — ${settings.last_pricing_refresh_result}` : ''}
        </p>
      ) : null}

      <div className="overflow-x-auto">
        <table className="w-full min-w-[420px] border-separate border-spacing-y-1 text-sm">
          <thead>
            <tr className="text-left text-xs font-medium text-neutral-500">
              <th className="pb-1 pr-2">Model</th>
              <th className="pb-1 pr-2">Input ($/M tok)</th>
              <th className="pb-1">Output ($/M tok)</th>
            </tr>
          </thead>
          <tbody>
            {modelIds.map((modelId) => {
              const rate = rows[modelId]
              const overridden = settings.overridden_models.includes(modelId)
              return (
                <tr key={modelId}>
                  <td className="rounded-l-lg bg-surface-muted py-2 pr-2 pl-2.5 align-middle">
                    <div className="flex items-center gap-1.5">
                      <DollarSignIcon className="size-3.5 shrink-0 text-neutral-400" />
                      <span className="truncate font-mono text-xs text-neutral-800">{modelId}</span>
                      {overridden ? (
                        <span className="shrink-0 rounded-full bg-brand-50 px-1.5 py-0.5 text-[0.6rem] font-medium text-brand-700">
                          edited
                        </span>
                      ) : null}
                    </div>
                  </td>
                  <td className="bg-surface-muted py-2 pr-2 align-middle">
                    <input
                      type="number"
                      min={0}
                      step="0.01"
                      value={rate?.input ?? 0}
                      onChange={(event) => updateRate(modelId, 'input', event.target.value)}
                      className="h-8 w-24 rounded-lg border border-hairline bg-surface px-2 text-sm tabular-nums outline-none focus:border-brand-400 focus:ring-4 focus:ring-brand-500/15"
                    />
                  </td>
                  <td className="rounded-r-lg bg-surface-muted py-2 pr-2.5 align-middle">
                    <input
                      type="number"
                      min={0}
                      step="0.01"
                      value={rate?.output ?? 0}
                      onChange={(event) => updateRate(modelId, 'output', event.target.value)}
                      className="h-8 w-24 rounded-lg border border-hairline bg-surface px-2 text-sm tabular-nums outline-none focus:border-brand-400 focus:ring-4 focus:ring-brand-500/15"
                    />
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {error ? (
        <p className="mt-3 rounded-lg bg-rose-50 px-3 py-2 text-xs text-rose-700">{error}</p>
      ) : null}

      <div className="mt-4 flex items-center gap-2">
        <ActionButton
          variant="primary"
          disabled={saving || !dirty}
          onClick={() => void handleSave()}
        >
          {saving ? 'Saving…' : 'Save pricing'}
        </ActionButton>
        {dirty ? <span className="text-xs text-neutral-500">Unsaved changes</span> : null}
      </div>
    </Panel>
  )
}
