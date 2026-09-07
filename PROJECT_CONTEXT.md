# VR-Nexus — Project Context (read this first)

**New chat / new session: read THIS file before doing anything else.** It is the
single source of truth for what VR-Nexus is, where everything lives, how it runs,
what is done, and the traps. You should not need to explore the tree to get
oriented — come back to specific files only when you touch them.

Companion docs: `README.md` (deep developer notes + troubleshooting),
`USER_GUIDE.md` (end-user manual), `docs/DEPLOYMENT.md` (production/ops).

---

## 1. What it is

VR-Nexus is an **AI Tender Intelligence & Evidence Matching platform**. A user
uploads a large procurement tender (PDF, hundreds of pages); the system reads it
clause by clause, extracts every requirement with its marks, matches each against
the company's **Evidence Library** (case studies, methodology docs, company docs),
lets a human review/accept/reject the matches, and produces a reviewable Excel
tracker + a ZIP document pack. There is a deliberate **human checkpoint**: the AI
proposes matches, a person finalizes.

Two halves: **Evidence Library** (built once, ahead of time) and **Tender
Analysis** (per tender). The tender matcher can only find evidence already indexed
in the library.

## 2. Tech stack

- **Backend**: FastAPI (Python 3.12), SQLAlchemy 2 + Alembic, Celery + Redis,
  PostgreSQL 16 + **pgvector**, Pydantic v2. JWT auth (python-jose + passlib/bcrypt).
- **Frontend**: React 19 + **Vite** (NOT Next.js — the plan said Next, the build is
  Vite; do not migrate), React Router 7, Tailwind CSS 4, Zustand, react-pdf.
- **LLM**: Google **Gemini** via its OpenAI-compatible endpoint (one key for
  everything — see §6). **Embeddings**: local `fastembed` (`BAAI/bge-base-en-v1.5`,
  768-dim, CPU, no key), stored/searched in pgvector.
- **Infra**: Docker Compose (Postgres, Redis, api, worker, flower). Nginx for prod.

## 3. Repository layout

```
vr-nexus-frontend/                 <- THE project root (run everything from here)
  docker-compose.yml               <- dev stack (api runs --reload, source-mounted)
  docker-compose.prod.yml          <- prod stack (built images, nginx frontend)
  package.json                     <- root: one-command dev (concurrently)
  .env / backend/.env / .env.example
  docker/init-extensions.sql       <- creates the `vector` extension on 1st DB start
  README.md USER_GUIDE.md PROJECT_CONTEXT.md CLAUDE.md
  docs/DEPLOYMENT.md
  backend/
    Dockerfile  requirements.txt  alembic/ (9 migrations)  tests/ (10 pytest files)
    app/
      main.py  celery_app.py
      api/routes/{auth,tenders,library}.py   api/deps.py (get_current_user, require_role)
      core/{config.py(Settings), database.py, security.py(JWT), ws_manager.py}
      models/{user, document, tender, tender_chunk, requirement, enums}.py
      schemas/{tender, library}.py
      services/
        chunking.py            <- TENDER chunker (~2000-tok, page-bounded)
        extraction.py          <- Gemini requirement extraction (Stage 2)
        pdf_extraction.py progress.py tender_storage.py
        library/
          chunking.py          <- LIBRARY chunker (~800-tok) -- DIFFERENT module, same fn name!
          embeddings.py(fastembed) search.py rag.py(answer) llm.py metadata.py
          library_progress.py storage.py
      tasks/{tender_pipeline.py (Stages 2-4), library_indexing.py}
  myapp/                              <- the frontend (Vite app)
    Dockerfile nginx.conf vite.config.ts vitest.config.ts package.json
    src/
      app/{router.tsx, guards.tsx, providers.tsx}
      constants/routes.ts
      pages/  (Dashboard, Login, Register, Documents*, Tender*, TenderReviewPage,
               AiAssistantPage, PdfViewerPage, PlaceholderPage)
      components/{dashboard, documents, tender, ui, feedback}/
      services/{authService, documentService, tenderService}.ts
      models/{auth, documents, tenders, dashboard}.ts
      hooks/{useAsyncData, useJobProgress, useTenderProgress}.ts
      store/{authStore, authStorage, themeStore}.ts   lib/{apiClient, formatting, validation, pdfWorker, theme}.ts
      pages also include ActivityPage, SettingsPage (theme toggle); public/vr-nexus-logo.png
  VR_Project/ , VR-Nexus-maryam/      <- ARCHIVAL prototypes. DO NOT RUN. Only backend/ runs.
```

## 4. The two pipelines (the core workflow)

**Tender pipeline** (Celery, `tasks/tender_pipeline.py`), 9 stages tracked over a
WebSocket (`/ws/tenders/{id}/progress`):
`uploaded → parsing → chunking → extracting → merging → matching → reporting →
assembling_folder → ready_for_review` (then terminal `finalized` / `failed`).
- parse (PyMuPDF, OCR fallback Tesseract) → section-aware ~2000-tok chunks →
  **extract** (one Gemini call per chunk → strict-JSON requirements, dedup by
  clause+desc hash) → **match** each requirement to the library (vector search +
  confidence: AUTO ≥0.85, SUGGESTED 0.50–0.84, else MISSING) → **report** (marks
  captured vs available) → **assemble** Excel + ZIP → pause at `ready_for_review`.
- Finalize (`POST /api/tenders/{id}/finalize`) rebuilds outputs from accepted
  matches and moves to `finalized`. **AI never auto-finalizes.**

**Library indexing pipeline** (`tasks/library_indexing.py`), stages over
`/ws/library/{job_id}`: `queued → parsing → tagging → embedding → indexed`
(or `failed`). Parse → chunk (~800-tok) → **tag** (Gemini metadata, has fallback)
→ **embed** (local fastembed) → store chunks+vectors+metadata in pgvector.

## 5. Key endpoints (all JWT-auth; frontend proxies /api and /ws to :8000)

- `/api/auth`: `register`, `login`, `refresh`.
- `/api/tenders`: `POST`(upload) · `GET`(list) · `GET/PATCH {id}` ·
  `GET {id}/requirements` · `GET {id}/matches` · `PATCH {id}/matches/{matchId}`
  (accept/reject/reassign) · `GET {id}/report` · `GET {id}/file` · `GET {id}/download`
  (output zip) · `POST {id}/finalize`.
- `/api/library`: `POST {category}/upload` · `POST check-duplicate` · `POST train` ·
  `POST documents/{id}/retrain` · `GET documents[/{id}]` · `GET stats` ·
  `GET jobs/{id}` · `GET search` · `POST ask` (grounded RAG) · `GET documents/{id}/file`.

## 6. LLM / RAG configuration (ONE Gemini key does everything)

- `.env` (root, used by Docker) and `backend/.env` (used by native uvicorn) must
  agree. Both set:
  - `OPENAI_API_KEY=<Gemini key>`
  - `OPENAI_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/`
  - `OPENAI_MODEL=gemini-3.6-flash`  (Gemini retires models — bump this when the API
    returns 404 "model no longer available")
  - `LLM_ENABLED=true`, `EXTRACTION_CONCURRENCY=4`
- This key powers: tender **extraction**, library **tagging**, and the AI Assistant
  **Ask**. Embeddings are **local** (fastembed) — no key, first index downloads a
  ~130 MB model once into the `fastembed_cache` volume.
- **RAG** = retrieve (local embeddings + pgvector) → generate (Gemini), only in the
  AI Assistant's Ask and where the tender matcher retrieves evidence.
- There is **no Anthropic** anymore (removed).

## 7. How to run (from `vr-nexus-frontend/`)

One command (starts Postgres+Redis+api+**worker**+Vite:5173 together):
```
npm run install:all      # once
npm run migrate          # first run only (alembic upgrade head via Docker)
npm run dev
```
Or manually:
```
docker compose up -d postgres redis
docker compose run --rm api alembic upgrade head
docker compose up -d api worker
cd myapp && npm run dev
```
Verify: containers are named **`vrnexus_*`**; API docs at http://127.0.0.1:8000/docs;
frontend at http://localhost:5173. Stop with `docker compose down` (keeps data).

## 8. Status — done vs remaining

**Done (this project's core scope):**
- Tender **review workspace** (`/tender-analysis/:tenderId`): requirements table,
  evidence accept/reject/reassign, coverage, finalize.
- **Output assembly**: Excel (Requirements/Summary/Evidence Matches/Instructions) +
  ZIP with original tender + `Required Documents/` evidence files.
- **AI Assistant** (`/ai-assistant`): Ask (grounded) + Find, with sources.
- Auth, RBAC, both pipelines, WebSocket progress, library indexing/search — all working.
- Single-provider Gemini; extraction runs concurrently with a 60s call timeout, and a
  user **Stop** halts a running tender (`POST /api/tenders/{id}/cancel` + cooperative
  cancel in extraction).
- **Upload hands off to Processing automatically.** Tender: one press uploads, saves
  the optional details and lands on `/tender-analysis/processing?tender=<id>` (a
  details-save failure travels as a dismissible notice instead of holding the form).
  Documents: one press uploads *and* enqueues indexing, landing on
  `/documents/processing?job=<id>` — except when a file was refused or came back with a
  near-duplicate warning, which still stops for a human (the Index button stays).
- **Delete + Reanalyse** on every settled tender.
  Backend: `DELETE /api/tenders/{id}` removes the row (cascades tender_chunks/
  requirements/matches) and best-effort cleans the source PDF, output folder and
  zip; allowed at any status. `POST /reprocess` (already there) is used for both
  the "Retry" on a failed row and the "Reanalyse" on a ready-for-review or
  finalized one.
  Frontend: Overview's Actions column now shows both — Reanalyse (RefreshIcon)
  for anything not currently in flight, Delete (TrashIcon, danger tone) for
  everything, gated by a ConfirmDialog that names the file. Per-row spinner
  state so one running action does not disable the other rows.
- **Contact technical support** on a failed tender (for non-technical teams).
  The button opens the user's **Gmail compose** window (`mail.google.com/mail/?view=cm`)
  pre-addressed to `SUPPORT_EMAIL` with the full failure (reason + stack) in the
  body; the user presses Send from their own Gmail. Sending from the user's
  mailbox means no server SMTP account, no app password, no new-sender spam, and
  a replyable message for the support team. `POST /api/tenders/{id}/report-issue`
  no longer sends mail; it only records `support_requested_at` (migration
  `a2e9f4c11d63`, cleared on reprocess), which flips the error log entry to the
  calm "we're on it, please wait 3-4 working days" state and keeps it across
  reloads. Frontend `supportGmailCompose()` builds the compose URL and the window
  is opened synchronously in the click (popup-blocker safe). The SMTP path
  (`app/services/support_email.py`, `SMTP_*` config) is now UNUSED but left in
  place in case a server-send option is wanted later.
- **Shell / navigation (this round):**
  - Scrollbar chrome hidden app-wide in `index.css` (`scrollbar-width:none` +
    `::-webkit-scrollbar{display:none}`); scrolling still works.
  - Sidebar text was using `text-neutral-*`, which INVERTS in dark mode → invisible
    on the always-dark rail. Switched to fixed `text-white/*` alphas.
  - **Collapsible sidebar** (lg only): toggle row at the top of the nav; collapsed
    shows only the logo mark + centred icons; state persisted in localStorage
    (`vrnexus.sidebar.collapsed`), owned by `DashboardLayout`.
  - **Header search is now a working typeahead** (`HeaderSearch` in `Header.tsx`):
    lazy-loads `listTenders`+`listDocuments` on first focus, filters client-side,
    dropdown navigates to the tender/document; Enter picks the first hit.
  - **Notification bell is functional** (`NotificationsMenu`): popover of recent
    notable events (tenders ready-for-review / failed, documents indexed) from the
    same two lists; unread badge vs a per-browser last-seen timestamp
    (`vrnexus.notifications.seen`), cleared on open. `Header` no longer takes
    `unreadNotifications`.
  - **About page** at `/about` (`pages/AboutPage.tsx`, route `ROUTES.about`, sidebar
    link under Account): product intro, capabilities, stack, and the team array
    (edit `TEAM` in that file to correct names/roles).
- **Error log** on the Processing page (below Pipeline, and shown even when the queue
  is empty): every failed run with the **stage it died at**, the one-line reason, the
  exception + stack tail behind a "Show technical detail" disclosure, and a Retry
  button. Backed by three new `tenders` columns — `failed_stage`, `error_detail`,
  `failed_at` (migration `d7b2e4c88a19`) — set by `_fail()` in the pipeline and by
  `/cancel`, and cleared by `/reprocess`. `_error_detail()` always names the exception
  class (a bare `str(exc)` is empty for many exceptions) and keeps the last
  `ERROR_FRAME_COUNT` frames, capped at `ERROR_DETAIL_LIMIT`. Tests:
  `backend/tests/test_failure_record.py`.
- **Failed tenders leave the Processing queue** (that page lists live work only) and
  come to rest in **Tender Overview**, where each failed row gets a **Retry** button
  (`POST /api/tenders/{id}/reprocess`). Reprocess resets the row to `uploaded` and
  re-enqueues the pipeline; it is idempotent because every stage deletes its own prior
  chunks/requirements/matches first. It 409s while a tender is still running.
- **Activity** page (real feed from tenders + library) and **Settings** page with a
  working **light/dark theme** (Settings → Appearance, or the header toggle).
- **Dashboard** runs on real data (tenders + library stats); all mock data removed
  (`src/mocks/` deleted). AI Assistant sources are deduped to one row per document.
- Brand mark is the supplied logo at `myapp/public/vr-nexus-logo.png`; the top header
  no longer duplicates the account (identity + sign-out live in the sidebar).
- Tests: frontend Vitest (`models/tenders.test.ts`), backend `test_output_assembly.py`
  + the original 8. Prod Docker (frontend Dockerfile/nginx, `docker-compose.prod.yml`).

**Remaining / not built (were out of scope or "where practical"):**
- Full HTTP/auth + end-to-end **integration tests** (need a live Postgres),
  load/perf and security testing, UAT (WBS 9.3).
- Optional **PDF/DOCX summary report** generator (WBS 5.3.1).
- All account pages are built: Activity, Settings (with theme), and Profile.
- Extra Figma screens (separate Compliance Matrix / Risks & Gaps tabs) not built.

## 8b. The tracker contract (the heart of the product)

The Excel tracker must reproduce the client's own spreadsheet. Its first 13 columns
are fixed, in this order, and are written VERBATIM from the tender:

  Page Number | Section Name | Responsibility | Reference Number |
  Clause / Requirement Description | Mandatory (Yes/No) |
  Evaluation Impact (...) | DPL | PRIME Responsibility (Yes/No) |
  The Tulepaak Responsibility (Yes/No) | Joint Responsibility (Yes/No) |
  Evidence / Document Required | Remarks

Then VR-Nexus adds `Marks`, `Matched File(s)`, `Coverage`, and finally **one column
per extra label** the tender carried (`Requirement.extra_fields`).

Rules that matter:
- **Verbatim wins.** `page_label`, `mandatory_raw` and `evaluation_impact_raw` hold the
  tender's own words; the normalised `page_number` / `is_mandatory` / `evaluation_impact`
  columns exist only for sorting, coverage and marks. Real tenders say "1-2",
  "No/Advisory" (WBS TN-EXT-02 calls it the "Mandatory/Advisory flag") and compound
  impacts like "Financial / Pass-Fail" or "Technical Compliance" - the enums cannot
  hold these, so never render the enum into the tracker.
- **Unstated means blank.** Never "N/A", never guessed. The extraction prompt asks for
  "" and `_clean()` strips placeholder noise.
- **Marks column always exists**, blank when the tender states none (many tenders have
  no scoring matrix; the shape stays consistent).
- `backend/tests/test_output_assembly.py` pins this layout - if you change a column,
  that test should be the thing that fails first.

## 9. Traps / gotchas (read before editing)

1. **Two chunkers, same function name.** `services/chunking.py` (tender, ~2000-tok)
   and `services/library/chunking.py` (library, ~800-tok) both export `chunk_text`.
   Import from the right one; a wrong import fails silently.
2. **Archival folders.** `VR_Project/` and `VR-Nexus-maryam/` (and a separate
   `Desktop\VR_Project` on this machine) are dead prototypes — DB `evidence`, no
   `app.celery_app`. Only `backend/` runs. Running the prototype's compose is the
   classic mistake (containers `vr_project-*` + "database evidence does not exist").
3. **pgvector.** `CREATE EXTENSION vector` must exist before migrations; handled by
   `docker/init-extensions.sql` on first Postgres start. An old volume skips it.
4. **Windows node_modules.** The working copy's `myapp/node_modules` is a Windows
   install. `tsc`/`eslint` run cross-platform, but the Vite **bundler** and test
   runners must run on the user's machine (`npm install` there first).
5. **Gemini model name drifts.** When a run 404s with "model no longer available",
   update `OPENAI_MODEL` in `.env` + `backend/.env` and recreate api+worker.
6. **Env picked up at container create**, not restart: after `.env` changes run
   `docker compose up -d --force-recreate api worker` (or `restart worker` for a
   code-only change, since code is source-mounted but Celery doesn't auto-reload).
7. **Extraction speed** is capped by Gemini's per-key RPM; tune `EXTRACTION_CONCURRENCY`.
   - **Dark-mode selection fills:** use `bg-selected` (a theme-aware token in
     `index.css`) for any selected / active / focused / cited fill that carries
     ordinary `text-neutral-*` body text. Do NOT use `bg-brand-50` for those — it
     is a FIXED light pink, and the neutral text inverts to light in dark mode, so
     light-on-light text disappears (the "selected card text invisible in dark
     theme" bug). `bg-brand-50` is fine only for small brand chips/badges whose
     text is brand-coloured (non-inverting).
8. **Extraction-cause probe:** `GET /api/health/llm` (auth'd) hits Gemini with a
   trivial prompt using the exact URL/auth/model the extraction pipeline uses. It
   returns `{ok, model, base_url, reply|error, status?, response_body?}` — so when
   extraction fails, one curl says *why* without waiting for a full tender to fail
   again. Quick call from the host: `curl -sS -H "Authorization: Bearer $TOKEN"
   http://127.0.0.1:8000/api/health/llm | python -m json.tool` (get $TOKEN from
   login). Interpretation: 401/403 = key rejected, 404 = retired model, 429 = quota,
   timeout = worker egress blocked, 200 with reply "pong" = LLM is fine and the
   failure is in per-chunk content (see chunk warnings in the worker log).
9. **Zero requirements is a FAILED run, not a finished one.** `run_extraction` raises
   `ExtractionFailed` when it creates 0 rows, wording the "every chunk failed to reach
   the model" case (configuration: key/model/egress) apart from the "read fine, found
   nothing" case (usually a scanned PDF with no text layer). Without it the run parked
   at `ready_for_review` and showed an empty review screen and an empty tracker as a
   success.
9. **Never branch on `data === null` to mean "still loading".** A fetcher that resolves
   to `[]` for a closed/idle state (as `ReassignDialog` does) makes `data` non-null from
   the first render, so `status === 'loading' && data === null` never fires and an
   in-flight *or failed* read falls through to the empty state — the dialog told users
   their evidence library was empty when the request had merely failed. Branch on
   `status` (plus `isRefreshing`), and show errors regardless of `data`.
10. **Model columns without a migration.** `Requirement.responsibility/dpl/prime/the_t/
   joint_responsibility` were declared in the model but never created in Postgres, so
   every tender run died with `UndefinedColumn: column "responsibility" ... does not
   exist` — on the INSERT in extracting, then on the SELECT in merging. Fixed by
   migration `f1a6c07d3e58`. If a run fails with `UndefinedColumn`, the cause is always
   this class of drift: add a migration, then `npm run migrate` and recreate the worker.

## 10. Where to look for X

- Change what a tender screen shows → `myapp/src/pages/Tender*.tsx`,
  `components/tender/*`, data in `models/tenders.ts`, calls in `services/tenderService.ts`.
- Change extraction/matching/scoring/output → `backend/app/tasks/tender_pipeline.py`,
  `services/extraction.py`.
- Change the library/AI-assistant → `services/documentService.ts` + `pages/AiAssistantPage.tsx`
  (frontend); `backend/app/api/routes/library.py`, `services/library/*` (backend).
- Add a config setting → `backend/app/core/config.py` (`Settings`), then `.env`/`.env.example`.
- Auth/RBAC → `backend/app/api/deps.py`, `core/security.py`, `models/enums.py` (roles: admin/user).
