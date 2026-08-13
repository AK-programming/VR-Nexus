# Evidence Library — RAG Backend

**WBS Section 6 — Evidence Library Management Subsystem**
Part of the *Tender Requirement Extraction & Evidence Assembly System*. Owner: **Afnan**.

Indexes three categories of company assets (case studies, methodology documents, company
documents) into PostgreSQL + pgvector so **Stage 3 evidence matching** can query them
semantically.

It is a working **RAG** system end to end: retrieval is the Section 6 deliverable, and a thin
generation layer (`POST /api/library/ask`) answers questions from the retrieved passages alone,
with citations, so the library can be demonstrated today without waiting for Stage 3.

---

## Contents

1. [What this subsystem does](#1-what-this-subsystem-does)
2. [Requirements implemented](#2-requirements-implemented)
3. [Technology stack](#3-technology-stack)
4. [How to run it](#4-how-to-run-it)
5. [How to test it](#5-how-to-test-it)
6. [How it works](#6-how-it-works)
7. [Retrieval-augmented generation](#7-retrieval-augmented-generation)
8. [The user interface](#8-the-user-interface)
9. [Project layout — every file explained](#9-project-layout--every-file-explained)
10. [API reference](#10-api-reference)
11. [How it merges with the other subsystems](#11-how-it-merges-with-the-other-subsystems)
12. [What to update, what to delete](#12-what-to-update-what-to-delete)
13. [How to demonstrate it](#13-how-to-demonstrate-it)
14. [What to push to the GitHub repo](#14-what-to-push-to-the-github-repo)
15. [Security status](#15-security-status)
16. [Troubleshooting](#16-troubleshooting)

---

## 1. What this subsystem does

A tender response needs *evidence*: past case studies, the firm's methodology, and company
compliance documents. Section 6 is the library that holds that evidence and makes it
**semantically searchable**, so Stage 3 can ask "show me healthcare data-migration work in
Punjab" rather than grepping filenames.

The unit of retrieval is a **chunk** (~800 tokens), not a document. Each chunk carries its
section name, phase label, page number and any image paths, so a hit can be traced back to
exactly where in which document it came from.

Three categories, three parsing strategies:

| Category | Why it is parsed differently |
|---|---|
| **Case study** | Has a recognisable six-part shape (Client, Sector, Scope, Challenge, Solution, Results). Splitting on those headings keeps each vector semantically coherent. |
| **Methodology** | Structured by phase/stage/step. Splitting on phase markers means a search for "requirements analysis" hits that phase, not the whole 60-page document. |
| **Company document** | A certificate or tax filing is short and serves *one* purpose. Splitting an ISO certificate would divorce "Scope of certification" from the certificate number, which is **worse** for retrieval. So these are deliberately **not** split. |

---

## 2. Requirements implemented

| WBS | Req | What | Where in code |
|---|---|---|---|
| 6.1.1 | LIB-IDX-01 | Three categories, separate upload endpoint each | `api/library.py` · `models.py:Category` |
| 6.1.2 | LIB-IDX-02 | Case study → Client/Sector/Scope/Challenge/Solution/Results; images to disk, linked by path | `services/parsers/case_study.py` |
| 6.1.3 | LIB-IDX-03 | Methodology → parsed by phase/section | `services/parsers/methodology.py` |
| 6.1.4 | LIB-IDX-04 | Company docs → single-purpose whole-file indexing | `services/parsers/company.py` |
| 6.1.5 | LIB-IDX-05 | ~800-token chunks, 100-token overlap, pgvector storage | `services/chunking.py` · `services/embeddings.py` |
| 6.1.6 | LIB-IDX-06 | Doc Type, Client, Sector, Service Line, Geography, Keywords | `services/metadata.py` |
| 6.1.7 | LIB-IDX-07 | Incremental — new asset only, no library re-index | `tasks/indexing.py` |
| 6.2.1 | LIB-UI-01 | Three category filters across the Documents and Upload views | `frontend/index.html` · `/stats` |
| 6.2.2 | LIB-UI-02 | Drag-and-drop: PDF, DOCX, PPTX, images | `frontend/js/app.js` · `services/storage.py` |
| 6.2.3 | LIB-UI-03 | Metadata fields + auto-tagging fallback | `frontend/index.html` · `services/metadata.py` |
| 6.2.4 | LIB-UI-04 | "Train / Memorize" → background pipeline | `POST /api/library/train` · `tasks/indexing.py` |
| 6.2.5 | LIB-UI-05 | WebSocket: Parsing → Tagging → Generating Embeddings → Indexing Complete | `api/ws.py` · `services/progress.py` |
| 6.2.6 | LIB-UI-06 | Duplicate check: file hash + semantic similarity | `services/search.py:check_duplicate` |
| 6.2.7 | LIB-UI-07 | Hot-reload — queryable with no restart | `services/search.py` (no cache, by design) |

---

## 3. Technology stack

**Web layer** — FastAPI 0.115.6, Uvicorn 0.34.0, websockets 14.1, python-multipart 0.0.20
**Config** — Pydantic 2.10.4, pydantic-settings 2.7.0
**Database** — PostgreSQL 16 (`pgvector/pgvector:pg16` image), SQLAlchemy 2.0.36,
Alembic 1.14.0, psycopg[binary] 3.2.3, pgvector 0.3.6
**Background jobs** — Celery 5.4.0, Redis 5.2.1, Flower 2.0.1
**Embeddings** — fastembed 0.5.1 (`BAAI/bge-base-en-v1.5`, **768-dim**, ONNX, CPU-only),
tiktoken 0.8.0
**LLM** — openai 1.59.6 SDK pointed at the Anthropic API, model `claude-opus-4-8`.
Used for `/ask` answer generation and as the parsing/auto-tagging fallback. Optional.
**Parsing** — pymupdf 1.25.1, python-docx 1.1.2, python-pptx 1.0.2, pillow 10.4.0,
pytesseract 0.3.13 + `tesseract-ocr` apt packages
**Frontend** — no framework, no build step. Plain HTML/CSS/JS served by FastAPI itself.
**Tests** — pytest 8.3.4, pytest-asyncio 0.25.2, httpx 0.28.1

### Two pinned versions that are not arbitrary

- **`pillow==10.4.0`** — fastembed 0.5.1 requires `pillow>=10.3.0,<11.0.0`. Pinning pillow 11
  makes the Docker build fail with `ResolutionImpossible`. Nothing else in the stack needs
  pillow 11 (pymupdf ships its own imaging; pytesseract accepts any pillow), so capping pillow
  is the smaller change.
- **`EMBEDDING_DIM=768`** — not a tuning choice. `chunks.embedding` is `vector(768)` in WBS
  1.1.3, and the column and the setting must agree or every insert fails. Changing the model
  means changing both, in one migration.

### Why embeddings run locally

The Implementation Plan specifies Google `text-embedding-004` (768-dim). The chat key available
to this project serves **chat models only** — `/v1/embeddings` is not available on it. Local
ONNX inference removes the dependency entirely: no key needed, no network call per chunk, and
the model is cached in a named volume after first download (~90 MB).

`BAAI/bge-base-en-v1.5` was chosen because it is **768-dim**, so it drops into the 1.1.3 column
without a schema change. (`bge-small` is the same family at 384-dim and would not fit.)

**To swap to a hosted provider:** add one `EmbeddingProvider` subclass in
`backend/app/services/embeddings.py`, register it in `get_provider()`, and add **one Alembic
migration** changing the vector column dimension. `EMBEDDING_DIM` and the migration must
always agree — `FastEmbedProvider.embed_documents()` raises with the exact fix in the message
if they drift.

The hosted model **is** used for chat: `/ask` answer generation, case-study section-mapping
fallback, methodology phase fallback, company doc-type classification, and metadata
auto-tagging. All of it is optional — set `LLM_ENABLED=false` and indexing and search still
work on heuristics alone.

---

## 4. How to run it

### Prerequisites

Docker and Docker Compose V2. Nothing else — no local Python, no local PostgreSQL.

### First run

```bash
cp .env.example .env
```

Then edit `.env`:
- Set `POSTGRES_PASSWORD` to a real password and put **the same** password inside
  `DATABASE_URL`. The two must match or the API cannot connect.
- Paste your Anthropic API key into `OPENAI_API_KEY` and leave
  `OPENAI_BASE_URL=https://api.anthropic.com/v1/`, **or** leave the key blank and set
  `LLM_ENABLED=false` to run fully offline on heuristics only. Offline, indexing and search
  work unchanged; only `/ask` generation and auto-tagging are lost.

> Never put a real key in `.env.example`. That file is committed; `.env` is not.

Bring the stack up:

```bash
docker compose up --build
```

Apply the schema (first run only):

```bash
docker compose exec api alembic upgrade head
```

Check it end to end:

```bash
./check.sh
```

### What is now running

| Service | Container | URL | Purpose |
|---|---|---|---|
| api | `evidence_api` | http://127.0.0.1:8000 | REST + WebSocket + the UI |
| postgres | `evidence_postgres` | `127.0.0.1:5432` | pgvector store |
| redis | `evidence_redis` | `127.0.0.1:6379` | Celery broker + progress pub/sub |
| worker | `evidence_worker` | — | Celery, concurrency 2 |
| flower | `evidence_flower` | http://127.0.0.1:5555 | Job monitoring |

- **UI** — http://127.0.0.1:8000/ui/ (`/` redirects there)
- **API docs (Swagger)** — http://127.0.0.1:8000/docs
- **Health check** — http://127.0.0.1:8000/health

Every port is bound to `127.0.0.1` only — nothing is reachable from the network.

There is **no frontend dev server and no build step**. FastAPI serves `frontend/` directly at
`/ui`, so `docker compose up -d` is the only thing that has to be running. No npm, no bundler.

### `.env` changes need a recreate, not a restart

Environment variables are read into the container at start, so editing `.env` and reloading the
page changes nothing. Recreate the containers that read it:

```bash
docker compose up -d --force-recreate api worker
```

`docker compose restart` is **not** enough — it restarts the process inside the existing
container, which still holds the old environment.

### Everyday commands

```bash
docker compose up -d
```

```bash
docker compose logs -f worker
```

```bash
docker compose restart worker
```

```bash
docker compose down
```

Stop and **also wipe the database, storage and model cache**:

```bash
docker compose down -v
```

### First-run notes

- The worker downloads the embedding model on its **first indexing job**, not at boot. The
  first Train is therefore slower; later ones read from the `fastembed_cache` volume and need
  no network.
- `backend/app`, `backend/alembic` and `frontend` are volume-mounted, so Python and UI edits
  hot-reload without a rebuild. **`backend/tests` is not mounted** — see the testing section.

### `check.sh` — one command that tells you if it works

```bash
./check.sh
```

Six checks in order, stopping at the first failure, so the first `FAIL` line is the actual
problem rather than the last symptom:

1. all five containers running
2. `/health` reports `ok`
3. the database is reachable
4. embeddings are **768-dim** — a dimension drift is silently wrong rather than loudly broken,
   which is exactly why it is asserted here
5. indexed document and chunk counts, read straight from Postgres
6. a real `/search` call returns hits

The LLM check is advisory, not a failure: generation is optional by design, so a missing key
prints a note and the script carries on.

### Running the API without Docker

Possible but not the supported path; you still need PostgreSQL with the pgvector extension and
a Redis instance.

```bash
cd backend && pip install -r requirements.txt
```

Then override the hostnames in `.env` (`postgres` → `localhost`, `redis` → `localhost`), set
`STORAGE_DIR` to a local path, and run:

```bash
uvicorn app.main:app --reload
```

---

## 5. How to test it

```bash
docker compose exec api pytest
```

Expected: **96 passed**.

For verbose per-test names:

```bash
docker compose exec api pytest -v
```

One file at a time:

```bash
docker compose exec api pytest tests/test_case_study_parser.py -v
```

### What the suite covers

| File | Tests | Covers |
|---|---|---|
| `test_case_study_parser.py` | 11 | LIB-IDX-02 — heading match, synonyms, inline label values, image paths, LLM fallback |
| `test_parsers.py` | 16 | LIB-IDX-03 phase splitting · LIB-IDX-04 company classification and identifier extraction |
| `test_metadata.py` | 14 | LIB-IDX-06 — user > heuristic > LLM precedence, auto-tag tracking |
| `test_storage.py` | 12 | Upload validation, hashing, path-traversal neutralisation |
| `test_duplicates.py` | 9 | LIB-UI-06 — hash hard block, similarity soft warning, failure tolerance |
| `test_rag.py` | 13 | `/ask` grounding — context assembly, the similarity floor, citation parsing, the refusal path, behaviour with the LLM off |
| `test_chunking.py` | — | LIB-IDX-05 — window size, overlap, section boundaries |

The RAG tests are worth calling out: they assert that an answer with **no** supporting passages
comes back as a refusal with `grounded: false`, and that the model is never asked at all when
retrieval finds nothing. That is the property that separates this from a chatbot, so it is
tested rather than assumed.

### The suite has no external dependencies

`backend/tests/conftest.py` states the contract:

> Tests must run with no database, no Redis, no network and no downloaded model. Anything that
> would reach outside the process is stubbed here.

It provides `StubEmbeddingProvider` (deterministic fake 768-dim vectors), an autouse `no_llm`
fixture that forces `llm.is_available() → False`, a temp `storage_dir`, and the shared
`CASE_STUDY_TEXT` / `METHODOLOGY_TEXT` / `COMPANY_DOC_TEXT` fixtures. Database-touching logic
is monkeypatched at the function boundary and called with `db=None`.

Because `pytest.ini` sets `pythonpath = . tests`, test modules import helpers as
`from conftest import ...` rather than via a relative import.

### Editing tests: the one gotcha

`docker-compose.yml` mounts `./backend/app`, `./backend/alembic`, `./backend/alembic.ini` and
`./frontend` — but **not `./backend/tests`**. Test files are baked into the image at build
time, so editing a test on the host does **not** change what runs in the container.

After editing any file under `backend/tests/`:

```bash
docker compose build api worker && docker compose up -d
```

If you edit tests often, add this line to the `api` service's `volumes:` in
`docker-compose.yml` and the problem goes away permanently:

```yaml
      - ./backend/tests:/app/tests
```

### Manual end-to-end check

The unit suite never touches PostgreSQL, so it cannot prove the vector path works. To verify
that, upload and train a real document through the UI, then search for a phrase from it — the
[demonstration guide](#13-how-to-demonstrate-it) is that test written out.

---

## 6. How it works

### The two-step design

Upload and Train are **separate calls on purpose**. The duplicate check has to happen *before*
anything is parsed or embedded, so uploading only stores and fingerprints the file, and Train
is what spends the CPU. An exact duplicate therefore costs one file read and nothing else.

### Step 1 — Upload

`POST /api/library/{category}/upload`

1. `storage.validate_upload()` — extension allowlist (`.pdf .docx .pptx .png .jpg .jpeg .tiff
   .tif`), size cap (`MAX_UPLOAD_MB`, default 100), reject empty files.
2. `storage.hash_bytes()` — sha256 of the content.
3. `extract.sample_text()` — a cheap text sample for the semantic check.
4. `search.check_duplicate()` — see below.
5. `storage.save_upload()` — written as `{document_id}{ext}`. The client filename is used
   **only** for its extension, so `../../etc/passwd` cannot escape the storage directory.
6. Row inserted at `training_status=QUEUED` with whatever metadata the uploader typed.

The insert is wrapped in a try/except that catches a lost race on the unique hash constraint
between the check and the commit, rolls back, removes the orphaned file and returns 409.

### Duplicate detection (LIB-UI-06)

Two signals, two very different consequences:

| Signal | Rule | Consequence |
|---|---|---|
| **sha256 match** | Byte-identical file already in the library | **Hard block** — HTTP 409. Indexing the same bytes twice can only dilute retrieval. |
| **Cosine similarity ≥ `DUPLICATE_SIMILARITY_THRESHOLD`** (default 0.95) | Semantically near-identical | **Soft warning** — the upload succeeds and the response carries `duplicate_warning`. Two case studies for the same client genuinely can read alike, so the uploader decides. |

Three deliberate behaviours worth knowing:

- An exact hash match **returns early and skips the embedding call** — no point paying for a
  vector when the answer is already decided.
- The semantic check is **skipped entirely when there is no text sample** (e.g. an image
  upload), because there is nothing cheap to embed.
- If the vector query *fails* (pgvector down, dimension mismatch), the exception is caught and
  logged and **the upload proceeds**. The hash check already ran and is the authoritative
  signal; a similarity failure is not fatal.

### Step 2 — Train

`POST /api/library/train` creates an `IndexJob` row per document and enqueues
`app.tasks.indexing.index_document`. Documents already `INDEXED` are skipped unless
`?force=true`; documents mid-run (`PARSING`, `TAGGING`, `EMBEDDING`) are always skipped, because
a second job would race
the first over the same chunk rows.

The Celery task runs `max_retries=0` **deliberately**: a parse failure is almost always a bad
file, and a silent retry would re-run OCR three times and confuse the progress display.
Failures are recorded on the document row for the user to see and re-trigger explicitly.

### The pipeline, stage by stage

```
Parsing (10% → 30%)
  extract.extract()          PDF/DOCX/PPTX/image → RawDoc (text, pages, images)
                             pytesseract OCR fallback when a PDF page has no text layer
  registry.parse(category)   → the right parser for the category
                             heuristics first; LLM only if heuristics fail
  document.page_count saved

Tagging (30% → 45%)                                          LIB-IDX-06
  Precedence, highest first:
    1. what the uploader typed        (never overwritten)
    2. what the parser found          (a case study's "Client:" line,
                                       a certificate's doc_type)
    3. metadata.extract() heuristics  (regex/keyword)
    4. LLM auto-tagging               (blank fields only)
  auto_tagged_fields records every field a machine filled, so a reviewer can
  tell guesses from human input.
  Title derived from the first plausible heading if the uploader left it blank.

Generating Embeddings (45% → 95%)                            LIB-IDX-05
  chunking.chunk_sections()  ~800-token windows, 100-token overlap,
                             never spanning a section boundary
  Old chunks for THIS document deleted here — not at the start, so a failed
  parse leaves the previously indexed version intact.
  Embedded in batches of 32 so a 400-chunk document reports progress as it goes.
  Vector count is checked against batch size; a mismatch raises rather than
  silently misaligning chunk↔vector.

Indexing Complete (100%)
  training_status=INDEXED, chunk_count, indexed_at set.
  Parse warnings (e.g. "Sections not found by heading match: Sector") are stored
  on document.training_error as advisory text — the document is still fully
  indexed.
```

Each `_advance()` call does **both** things: persists the job row *and* publishes to Redis.
Not either — the WebSocket carries live updates, but a client that connects late or reloads
mid-run reads the persisted row instead of missing the stage entirely.

### Progress over WebSocket (LIB-UI-05)

`GET /ws/library/{job_id}` (WebSocket)

1. On connect, the current `index_jobs` row is **replayed first** (`"replayed": true`), so a
   client that reloads mid-run does not sit on an empty progress bar while the job is already
   at "Generating Embeddings".
2. If the job is already `complete` or `failed`, the socket closes immediately — the snapshot
   told the whole story.
3. Otherwise it subscribes to that job's Redis channel and forwards each frame.
4. A `{"type": "ping"}` frame every second of silence keeps proxies from dropping an idle
   socket during a long parse, and surfaces a dead client as a disconnect.
5. If Redis is unreachable, the client is told to poll `GET /api/library/jobs/{id}` instead
   rather than being left with a silent socket.

The five stage labels are fixed by LIB-UI-05 and served from `GET /api/library/stages` so the
UI does not hardcode them: **Queued · Parsing · Tagging · Generating Embeddings · Indexing
Complete** (plus **Failed**).

### Incremental indexing (LIB-IDX-07)

One Celery task per document, and nothing in `tasks/indexing.py` reads or rewrites another
document's chunks. Training after adding one asset processes only that asset. Re-training one
document deletes **its own** chunks and rebuilds them; the rest of the library is never
re-embedded.

### Hot-reload (LIB-UI-07)

There is no code for this, and that is the point. `services/search.py` queries PostgreSQL on
every request — no in-memory index, no result cache. The moment the worker commits a chunk
batch, those rows are live to Stage 3. No reload, no restart, no invalidation step.

> **The design constraint: never add a cache to the search path.** Any cache introduced here
> silently breaks LIB-UI-07.

### Search

`GET /api/library/search?q=...`

pgvector's `<=>` returns cosine **distance**, so similarity is `1 - distance`. Only chunks
belonging to `training_status=INDEXED` documents with a non-null embedding are considered. When
a `category` filter is supplied it is applied to the chunk's own denormalised `category` column,
which avoids paying for the join before the vector scan narrows the candidate set.

Note that `embed_query()` and `embed_documents()` are **not** interchangeable: bge models
expect a retrieval-instruction prefix on queries but not on passages, and `query_embed()`
applies it.

**The endpoint returns chunks, not documents, and that is deliberate.** A chunk is what an
embedding covers, and Stage 3 wants the passage that matched — not a document it would have to
re-scan. The consequence is that `limit` counts *passages*: one strong case study can occupy
every row. Grouping passages back into documents is a presentation concern, and the UI does it
(see [section 8](#8-the-user-interface)) rather than the API, so the Stage 3 contract stays a
flat ranked list.

### Database schema

The document and chunk tables come from **WBS 1.1.2 / 1.1.3** (Maryam's models), adopted rather
than re-invented so Section 6 writes into the schema the rest of the system already expects.
Section 6 adds columns to them; it does not rename or restructure.

**`documents`** — one row per asset, all three categories.
`id` (UUID), `category`, `title`, `original_filename`, `file_path`, `file_type`, `file_hash`
(unique — serves double duty as the duplicate block *and* the "already indexed" check), the
LIB-IDX-06 metadata columns (`client`, `sector`, `service_line`, `geography`, `keywords`),
`training_status`, `training_error`, `uploaded_by` (for WBS 1.2), plus the Section 6 additions
`doc_type`, `auto_tagged_fields`, `page_count`, `chunk_count`, `indexed_at`.

**`chunks`** — the retrieval unit.
`id`, `document_id` (FK, `ON DELETE CASCADE`), `chunk_index`, `content`, `token_count`,
`section_name` (LIB-IDX-02), `page_number`, **`embedding VECTOR(768)`**, plus the Section 6
additions `category` (denormalised for filtering), `phase` (LIB-IDX-03) and `image_paths`
(JSON — **paths only, never pixel data**). Unique on `(document_id, chunk_index)`.

**`document_images`** — extracted images (LIB-IDX-02), linked by path.
`id`, `document_id` (FK cascade), `file_path`, `page_number`, `caption`.

**`index_jobs`** — one row per Train run, so progress survives a page reload.
`id`, `document_id` (FK cascade), `stage`, `progress`, `message`, `created_at`, `updated_at`.

Two enums that are easy to confuse:

| Enum | Column | Says |
|---|---|---|
| `DocumentTrainingStatus` | `documents.training_status` | What a document **is**: `QUEUED` `PARSING` `TAGGING` `EMBEDDING` `INDEXED` `FAILED` |
| `JobStage` | `index_jobs.stage` | Where one **Train run** got to: `queued` `parsing` `tagging` `embedding` `complete` `failed` |

They are separate on purpose: re-training an indexed document creates a new job at `queued`
while the document legitimately stays `INDEXED` until the new chunks replace the old ones.

Postgres stores the **name** for `DocumentCategory` (`CASE_STUDY`), because SQLAlchemy's native
enum defaults to names and 1.1.2's migration was generated that way. The wire format is still
the lowercase value (`case_study`), since these are `str` enums.

Deleting a document cascades to its chunks, images and jobs in the database, and
`storage.delete_document_files()` removes its file and image directory. Deletion is idempotent —
missing files are not an error.

---

## 7. Retrieval-augmented generation

`POST /api/library/ask` · `backend/app/services/rag.py`

Section 6 owns **retrieval**. Stage 3 owns generation and will call `/search` directly. This
endpoint is the thin generation layer on top, so the library can be shown working end to end
today. It adds no state and no tables — remove it and indexing and search are unaffected.

### What makes it RAG and not a chatbot

Both halves are real:

| Half | Where | What actually happens |
|---|---|---|
| **Retrieval** | `services/search.py` | The question is embedded with `bge-base-en-v1.5` and matched against `chunks.embedding` by cosine distance in pgvector. |
| **Augmented generation** | `services/rag.py` | The top passages are pasted into the prompt as numbered excerpts. The model answers from those excerpts and nothing else. |

The design rule is that **the model is never the source of facts**. It is given the excerpts and
told, in the system prompt, to answer only from them, to cite each claim as `[n]`, and — if the
excerpts do not answer the question — to reply with one exact sentence:

> The library does not contain an answer to this question.

That string is matched verbatim in code to set `grounded`. An answer is grounded only when the
model cited at least one passage **and** did not decline.

### The knobs, and why they are set where they are

| Constant | Value | Reasoning |
|---|---|---|
| `DEFAULT_CONTEXT_CHUNKS` | 6 | Enough to cover a question spanning two sections; few enough that the relevant passage is not buried. |
| `MIN_CONTEXT_SIMILARITY` | 0.25 | Vector search always returns its top-k, even when the library holds nothing relevant. Without a floor, an unrelated question hands the model unrelated text and asks it to make sense of it. |
| `MAX_CONTEXT_CHARS` | 24000 | A methodology chunk runs long; six of them plus a verbose question should not silently exceed the request limit. |

The floor here (0.25) is deliberately **lower than the UI's search floor (0.50)**. A
partially-relevant passage still earns its place as grounding context — the model can use it or
ignore it. In a human-scanned result list the same passage is just noise.

### The response

```json
{
  "question": "How do farmers pay for the solar pumps?",
  "answer": "Farmers pay through a pay-as-you-go model [2], with repayments...[3]",
  "grounded": true,
  "sources": [{ "...": "a full SearchHit", "cited": true }]
}
```

`sources` is not decoration. An answer is only trustworthy to the extent a reader can check it,
so the passages travel with it and `cited` marks the ones the answer actually used. When
generation is unavailable (`LLM_ENABLED=false` or no key), the endpoint still returns the
retrieved sources with `grounded: false` — retrieval is the deliverable and it does not depend
on the model.

---

## 8. The user interface

`frontend/` — plain HTML, CSS and JavaScript. **No framework, no build step, no dev server.**
`app/main.py` mounts the directory at `/ui` with `StaticFiles(html=True)`, so the API serves it
and `docker compose up -d` is the only thing that has to be running.

Five views, hash-routed (`#/search`), so a view is linkable and survives a refresh:

| View | What it demonstrates |
|---|---|
| **Overview** | Indexed/queued/failed counts, per-category breakdown, embedding model and dimension, LLM availability |
| **Documents** | Everything uploaded, filtered by category, with status pills — one per `DocumentTrainingStatus` value |
| **Upload & Train** | The four numbered steps: category → files → metadata → train. Drag-and-drop, duplicate warnings, live WebSocket progress (LIB-UI-01 … LIB-UI-06) |
| **Search** | Semantic retrieval, grouped by document |
| **Ask** | The RAG path — grounded answer, clickable `[n]` citations, numbered sources |

### Search results are grouped by document

The API returns chunks. A reader wants documents. Without grouping, one strong case study
appears seven times in a row — once per matching section — and pushes everything else off the
page.

So the Search view over-fetches passages and collapses them:

```js
const MIN_SIMILARITY = 0.5;   // hide the weak tail
const CHUNK_LIMIT    = 40;    // over-fetch passages...
const DOCUMENT_LIMIT = 8;     // ...to fill this many documents
const PASSAGES_SHOWN = 3;     // the rest go behind a toggle
```

**A document scores by its best passage, not the mean.** A long case study with one exact match
and twenty unrelated sections is a good result; averaging would bury it under a short document
that matches weakly throughout. Each card shows one relevance percentage, its top three
passages with their own scores, and the remainder behind a disclosure toggle.

Over-fetching is what makes the cap meaningful: asking for 8 chunks and grouping them can still
yield one document, so the request is for 40 passages and the *documents* are capped at 8.

### Citations are links

In the Ask view the model's `[2]` markers become anchors that scroll to the matching source
card, and cited sources are highlighted. The answer text is HTML-escaped **before** the markers
are replaced — doing it the other way round would let answer text inject markup through the
anchors the UI inserts.

### This is still a test harness

It exercises WBS 6.2 end to end and is how the subsystem is demonstrated, but Section 8 is the
production frontend and replaces it wholesale. See
[section 11](#11-how-it-merges-with-the-other-subsystems).

---

## 9. Project layout — every file explained

```
VR_Project/
├── docker-compose.yml          5 services, 3 named volumes, all bound to 127.0.0.1
├── check.sh                    Six-step health check — run after any change
├── .env.example                Template — copy to .env. Committed, so no real keys.
├── .env                        Real secrets. GITIGNORED. Never commit.
├── .gitignore
├── README.md                   This file
│
├── backend/
│   ├── Dockerfile              python:3.12-slim + tesseract-ocr
│   ├── requirements.txt        Pinned dependencies
│   ├── pytest.ini              testpaths=tests, pythonpath=". tests"
│   │
│   ├── alembic.ini
│   ├── alembic/
│   │   ├── env.py
│   │   ├── script.py.mako
│   │   └── versions/
│   │       └── 0001_initial.py   CREATE EXTENSION vector, 4 tables, 4 enums
│   │
│   ├── app/
│   │   ├── main.py             FastAPI app, CORS, /health, mounts /ui
│   │   ├── config.py           Pydantic settings — every env var lives here
│   │   ├── db.py               Engine, SessionLocal, Base, get_db dependency
│   │   ├── models.py           SQLAlchemy models (WBS 1.1.2/1.1.3) + 4 enums
│   │   ├── schemas.py          Pydantic request/response models
│   │   ├── celery_app.py       Celery configuration
│   │   │
│   │   ├── api/
│   │   │   ├── library.py      All REST endpoints (WBS 6.2) + /ask
│   │   │   ├── ws.py           Progress WebSocket (LIB-UI-05)
│   │   │   └── deps.py         current_user stub — THE AUTH SEAM (WBS 1.2)
│   │   │
│   │   ├── services/
│   │   │   ├── storage.py      Validation, hashing, safe paths
│   │   │   ├── embeddings.py   EmbeddingProvider ABC + FastEmbedProvider (768-dim)
│   │   │   ├── llm.py          Chat client, complete_json()
│   │   │   ├── rag.py          Grounded answer generation — the G in RAG
│   │   │   ├── chunking.py     Token windows (LIB-IDX-05)
│   │   │   ├── metadata.py     LIB-IDX-06 extraction + precedence
│   │   │   ├── progress.py     Redis pub/sub publish + channel naming
│   │   │   ├── search.py       pgvector search + duplicate detection
│   │   │   └── parsers/
│   │   │       ├── base.py         RawDoc, Section, ParseResult, registry hooks
│   │   │       ├── extract.py      PDF/DOCX/PPTX/image → RawDoc, OCR fallback
│   │   │       ├── case_study.py   LIB-IDX-02
│   │   │       ├── methodology.py  LIB-IDX-03
│   │   │       ├── company.py      LIB-IDX-04
│   │   │       └── registry.py     Category → parser dispatch
│   │   │
│   │   └── tasks/
│   │       └── indexing.py     The Celery pipeline
│   │
│   └── tests/                  96 tests. NOT volume-mounted — rebuild after editing.
│       ├── conftest.py         Stubs: no DB, no Redis, no network, no model
│       ├── test_case_study_parser.py
│       ├── test_parsers.py
│       ├── test_metadata.py
│       ├── test_chunking.py
│       ├── test_storage.py
│       ├── test_duplicates.py
│       └── test_rag.py         Grounding, citations, the refusal path
│
├── frontend/                   Test UI — Section 8 replaces this
│   ├── index.html              Sidebar + 5 hash-routed views
│   ├── css/styles.css          Light theme, CSS custom properties
│   └── js/app.js               Routing, document grouping, WebSocket, Ask
│
├── storage/                    RUNTIME ONLY, gitignored
│   ├── documents/              {document_id}.{ext}
│   └── images/{document_id}/   Extracted images (LIB-IDX-02)
│
├── VR-Nexus-maryam/            WBS 1.1.2/1.1.3 upstream models — READ ONLY,
│                               never modified. The schema source this adopts.
│
└── Planning documents (reference, not code)
    ├── Implementation_Plan_Maryam.docx
    ├── SRS_2_Shaheer.docx
    ├── WBS_Yasir.xlsx
    └── Scope_of_Work_DPL.pdf
```

### The files that matter most

If you are picking this codebase up, read these five in this order:

1. **`app/models.py`** — the data model tells you what the system is.
2. **`app/tasks/indexing.py`** — the pipeline tells you what it does.
3. **`app/api/library.py`** — the endpoints tell you how it is driven.
4. **`app/services/search.py`** — the retrieval seam Stage 3 consumes.
5. **`app/services/parsers/case_study.py`** — the most involved parser, and the pattern the
   other two follow.

---

## 10. API reference

Base path `/api/library`. Interactive docs at http://127.0.0.1:8000/docs.

### Upload and duplicates

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/{category}/upload` | Upload one file. `category` ∈ `case_study` `methodology` `company_document`. Multipart: `file` plus optional `title` `client` `sector` `service_line` `geography` `keywords` (comma-separated) `doc_type`. → 201, or **409** on exact duplicate. |
| `POST` | `/check-duplicate` | Dry run — nothing is stored. Lets the UI warn while a file is still in the drop zone. |

### Training

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/train` | Body `{"document_ids": [...]}`, or omit to train everything `QUEUED`. `?force=true` re-indexes already-indexed documents. Returns created jobs and skipped ids. |
| `POST` | `/documents/{id}/retrain` | Re-index one document. 409 if already indexing. |

### Reading

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/documents` | Filters: `category`, `status`, `limit` (≤500), `offset`. Newest first. |
| `GET` | `/documents/{id}` | One document. `?include_chunks=true` returns its chunks in order. |
| `DELETE` | `/documents/{id}` | 204. Cascades to chunks and jobs; removes files from disk. |
| `GET` | `/stats` | Per-category × per-status counts, total chunks, embedding model and dimension, whether the LLM is available. |
| `GET` | `/stages` | The LIB-UI-05 stage labels. |
| `GET` | `/jobs/{id}` | Job state — the polling fallback when the WebSocket is unavailable. |
| `GET` | `/documents/{id}/jobs` | All jobs for one document, newest first. |
| `GET` | `/documents/{id}/images/{name}` | Serve one extracted image. Any path syntax in `name` is rejected outright rather than sanitised. |

### Search and ask — the Stage 3 seam

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/search` | `q` (≥2 chars), optional `category`, `limit` (≤50), `min_similarity` (0–1). Returns **chunks**, ranked by cosine similarity. |
| `POST` | `/ask` | Body `{"question": "...", "category": "...", "limit": 6}`. Retrieves, then generates an answer from the retrieved passages only. Returns `answer`, `grounded`, and the `sources` with `cited` flags. |

Two notes that matter when reading results:

- **`/search` returns passages, not documents.** `limit` counts chunks, so one strong document
  can fill the whole response. The UI over-fetches and groups (see
  [section 8](#8-the-user-interface)); a programmatic consumer gets the flat list and decides
  for itself.
- **The floors differ on purpose.** The UI hides anything below **0.50** because a weak passage
  is noise in a scanned list. `/ask` keeps passages down to **0.25**, because a partially
  relevant excerpt is still usable grounding.

### Elsewhere

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Real DB round-trip. Reports `degraded` and names the failing dependency rather than returning 502. Also reports the embedding model, its dimension and whether the LLM is available. |
| `WS` | `/ws/library/{job_id}` | Live training progress. |
| `GET` | `/` → `/ui/` | The UI. |

---

## 11. How it merges with the other subsystems

Section 6 is one subsystem of a larger system built by several engineers. It is designed to be
**consumed**, not modified, by the others.

### The integration map

```
Section 1.2 — Authentication  (another engineer, NOT STARTED)
      │
      │  provides: JWT verification
      ▼
  app/api/deps.py :: current_user()          ← THE ONLY FILE THAT CHANGES
      │
Section 6 — Evidence Library  (THIS REPO)
      │
      │  provides: GET /api/library/search
      ▼
Stage 3 — Requirement Matching  (consumes this subsystem)
      │
      ▼
Section 8 — Production Frontend  (replaces frontend/)
```

### Merging with Section 1.2 (Authentication) — inbound

Auth is WBS 1.2 (`AUTH-01..06`), owned by another engineer and **not started**. There is no
token issuer to validate against yet, so every route currently depends on a stub.

Every handler already takes `user: Principal = Depends(current_user)`. That is not decoration —
it means wiring real auth is a change to **one file**, `backend/app/api/deps.py`, and to no
handler signature anywhere:

```python
# backend/app/api/deps.py — replace the body only
def current_user(token: str = Depends(oauth2_scheme)) -> Principal:
    payload = verify_jwt(token)          # from Section 1.2
    if payload is None:
        raise HTTPException(401, "Invalid or expired token")
    return Principal(id=payload["sub"], email=payload["email"], is_authenticated=True)
```

`Principal` is already a frozen dataclass with `id`, `email` and `is_authenticated`. If 1.2
ships a different shape, keep this class as the adapter rather than changing every route.

**Also required when 1.2 lands:** add the WebSocket to the auth story. `/ws/library/{job_id}`
does not take `current_user` today, because a browser WebSocket cannot send an `Authorization`
header — it needs a query-param or subprotocol token. That is a known, deliberate gap.

### Merging with Stage 3 (Requirement Matching) — outbound

Stage 3 is the primary consumer. It should call exactly one endpoint:

```
GET /api/library/search?q=<requirement text>&category=case_study&limit=10&min_similarity=0.4
```

Each hit carries everything needed to cite the evidence:

```json
{
  "query": "healthcare data migration in Punjab",
  "hits": [{
    "chunk_id": "...", "document_id": "...",
    "original_filename": "moh_punjab_case_study.pdf",
    "title": "Ministry of Health Punjab — HMIS Migration",
    "category": "case_study",
    "section_name": "Solution",
    "phase": "",
    "page_number": 3,
    "content": "We migrated 4.2 million patient records...",
    "similarity": 0.8731,
    "image_paths": ["images/<id>/page3_img1.png"],
    "cited": false
  }]
}
```

Contract notes for whoever integrates Stage 3:

- **`similarity` is cosine similarity in `[0, 1]`**, already converted from pgvector distance.
  Higher is better. Use `min_similarity` to cut the tail server-side rather than filtering
  client-side.
- **A hit is a chunk, not a document.** `limit` counts passages, so several hits can share one
  `document_id`. Group on `document_id` if you want one entry per document, and score the group
  by its **best** passage rather than the mean.
- **Only `training_status=INDEXED` documents are searchable.** A `QUEUED` upload is invisible
  here, by design.
- **`section_name` and `phase` are the citation labels.** Case studies populate `section_name`
  (Challenge, Solution, Results…); methodology documents populate `phase` (`Phase 2:
  Requirements Analysis`); company documents put the doc type in `section_name`.
- **No cache means no staleness.** Do not add one on the Stage 3 side either without accepting
  that LIB-UI-07 no longer holds.
- **`image_paths` are storage-relative.** Fetch them through
  `GET /api/library/documents/{id}/images/{name}` — never construct filesystem paths.
- Use `category` filtering when the requirement type is known. It is applied before the join
  and is meaningfully faster.

### Merging with Section 8 (Production Frontend) — replacement

`frontend/` is a **test harness** that exercises WBS 6.2 end to end. It is not the production
UI and Section 8 replaces it wholesale.

When Section 8 lands:

1. Delete `frontend/` (see [section 12](#12-what-to-update-what-to-delete)).
2. Remove the `./frontend:/app/frontend` volume from the `api` service.
3. `app/main.py` mounts `/ui` **only if the directory exists** and otherwise redirects `/` to
   `/docs`, so no code change is needed — the mount simply stops happening.
4. Add the Section 8 dev-server origin to `CORS_ORIGINS`. Port 3000 is already in the default
   (`.env.example` notes it is there for Next.js).

Every UI-facing constant is already served from the API rather than hardcoded — stage labels
from `/stages`, category counts from `/stats` — so Section 8 does not need to duplicate them.
Two behaviours are worth reimplementing rather than rediscovering: **grouping search hits by
document** and **scoring a group by its best passage**. Both are in `frontend/js/app.js` and
both exist because the API's chunk-level output reads badly without them.

### Merging with WBS 1.1.2 / 1.1.3 (data models) — adopted

`VR-Nexus-maryam/` holds the upstream model definitions. Section 6 **adopted** that schema
rather than defining a parallel one: `documents` and `chunks` are 1.1.2/1.1.3 tables, and
Section 6 only adds columns to them (`doc_type`, `auto_tagged_fields`, `page_count`,
`chunk_count`, `indexed_at`, `phase`, `image_paths`, chunk `category`).

Two compatible tightenings worth flagging to that owner:

- `documents.file_hash` is `unique` here. 1.1.2 leaves it nullable and non-unique. The
  constraint is what makes the LIB-UI-06 duplicate block and LIB-IDX-07's "already indexed,
  skip it" check work. Every row 1.1.2 accepts, this accepts too.
- `chunks.embedding` is `vector(768)` exactly as 1.1.3 specifies. That is why the embedding
  model is `bge-base` and not `bge-small`.

**`VR-Nexus-maryam/` is read-only.** It is a reference copy, not a dependency that gets edited.

### Shared-infrastructure caution

If Section 6 is merged into a monorepo alongside other subsystems, three things collide:

- **Port numbers** — 8000, 5432, 6379, 5555 are all claimed here.
- **Enum type names** — `document_category`, `document_file_type`, `document_training_status`
  and `job_stage` are created as PostgreSQL types at the database level. If another subsystem
  creates a type with the same name in the same database, migrations fail. Use a separate
  database, or prefix the types.
- **The `.env` file** — Compose reads a single root `.env` for every service. Merging repos
  means merging env files, and `DATABASE_URL` must stay consistent with `POSTGRES_PASSWORD`.

---

## 12. What to update, what to delete

### Files you will need to update

| File | When | What to change |
|---|---|---|
| `.env` | Before first run | Real `POSTGRES_PASSWORD` (mirrored into `DATABASE_URL`), `OPENAI_API_KEY` |
| `backend/app/api/deps.py` | When WBS 1.2 lands | Replace the `current_user()` body with real JWT verification |
| `.env` → `CORS_ORIGINS` | When Section 8 lands | Add the production frontend origin |
| `docker-compose.yml` | If you edit tests often | Add `./backend/tests:/app/tests` to the `api` volumes |
| `backend/app/services/embeddings.py` + a new Alembic migration | If you change embedding model | New provider subclass **and** matching vector dimension. `EMBEDDING_DIM` and the migration must agree. |
| `backend/app/services/parsers/case_study.py` → `SECTION_SYNONYMS` | When real documents use headings the parser misses | Add the synonym; it is a data change, not a logic change |
| `backend/app/services/parsers/company.py` → `DOC_TYPE_PATTERNS` | When a new company document type appears | Add weighted phrases. Weight 5 = decisive, 1 = weak hint |
| `frontend/js/app.js` → `MIN_SIMILARITY` / `DOCUMENT_LIMIT` | If results feel too thin or too noisy | Presentation only. The API is unchanged; Stage 3 is unaffected. |
| `backend/requirements.txt` | Dependency bumps | Note that `pillow` is capped by fastembed — read the comment before changing it |

### Files safe to delete

| Path | Why | When |
|---|---|---|
| `frontend/` | Test harness only; Section 8 supersedes it | When Section 8 is integrated — **not before** |
| `storage/` contents | Runtime uploads, not source | When resetting a demo. Delete DB rows too, or you get orphaned rows |
| `__pycache__/`, `.pytest_cache/`, `.ruff_cache/` | Build artefacts, gitignored | Any time |
| Any `*.txt` extracted from a `.docx` | Working files, gitignored via `*.txt` | Any time; the `.docx` originals are the real documents |

Already removed in the last cleanup: `Implementation_Plan_Maryam.txt`, `SRS_2_Shaheer.txt`
(extracted text — the `.docx` originals remain), `ask.json` (a curl scratch payload, replaced by
the Ask view), and every build-artefact cache directory.

### Do NOT delete these

| Path | Why it looks deletable but is not |
|---|---|
| `backend/app/api/deps.py` | Looks like a no-op stub. It is the auth seam — deleting it means editing every route handler later. |
| `backend/alembic/versions/0001_initial.py` | Never edit or delete an applied migration. Add a new one. |
| `.env.example` | The only documentation of what `.env` must contain. Commit it; commit `.env` never. |
| `backend/tests/conftest.py` | Without its stubs the entire suite requires PostgreSQL, Redis and a model download. |
| `frontend/` — *before* Section 8 exists | It is currently the only way to demonstrate WBS 6.2. |
| `check.sh` | Six lines of output that answer "is it broken, and where" faster than reading logs. |
| `VR-Nexus-maryam/` | The upstream WBS 1.1.2/1.1.3 schema this subsystem adopted. Reference, read-only. |
| The planning documents (`.docx`, `.xlsx`, `.pdf`) | The requirement source of truth. |

### One-line guard for the whole section

> Update `.env`, `deps.py`, and parser pattern tables. Delete `frontend/` only when Section 8
> replaces it, and extracted `.txt` files any time. Touch an applied Alembic migration, or
> anything in `VR-Nexus-maryam/`, never.

---

## 13. How to demonstrate it

A demo that proves all 14 requirements takes about ten minutes. Prepare three files first: a
**case study** (PDF or DOCX with Client/Challenge/Solution/Results headings), a **methodology
document** (with Phase 1/2/3 headings), and a **company document** (a certificate or
registration). A scanned image-only PDF is a good optional fourth, to show OCR.

### Before the audience arrives

```bash
docker compose up -d && docker compose exec api alembic upgrade head
```

Then **train one throwaway document and delete it**. This forces the worker to download the
embedding model into the cache volume, so your live demo does not stall for a minute on the
first Train. Confirm the stack is healthy:

```bash
./check.sh
```

Every line should read `OK`. If the LLM line prints a note instead, the Ask step below will
return sources without a generated answer — fine if that is deliberate, a surprise if not.

### The walkthrough

**1. Open the UI** — http://127.0.0.1:8000/ui/

The Overview lands first: indexed counts, per-category breakdown, the embedding model and its
dimension. The sidebar has five views.
→ **Proves LIB-UI-01 / LIB-IDX-01.**

**2. Go to Upload & Train, pick "Case Studies", drag the case study in**

The four numbered steps make the flow obvious. At step 3 fill in **only** Client — leave Sector,
Service Line, Geography and Keywords blank. Say out loud that you are leaving them blank on
purpose.
→ **Proves LIB-UI-02, LIB-UI-03.**

**3. Click "Train / Memorize"**

Watch the progress move through the four labels: **Parsing → Tagging → Generating Embeddings →
Indexing Complete**. This is a live WebSocket, not a poll.
→ **Proves LIB-UI-04, LIB-UI-05.**

**4. Reload the page mid-run**

Do this while the bar is still moving. It resumes at the correct stage rather than resetting —
the WebSocket replays the persisted job row on connect.
→ **Proves the LIB-UI-05 replay design.**

**5. Open Documents and expand the trained document**

The section names are there: Client, Challenge, Solution, Results. The metadata fields you left
blank are now filled and flagged as auto-tagged, while the Client you typed is unchanged.
→ **Proves LIB-IDX-02 and LIB-IDX-06 precedence.**

**6. Go to Search and search for a phrase worded differently from the document**

Say the document contains "migrated 4.2 million patient records" — search for `hospital data
transfer`. It still hits. That is semantic retrieval, not keyword matching. Point out that the
document was indexed sixty seconds ago and nothing was restarted.
→ **Proves LIB-IDX-05 and LIB-UI-07.**

Worth pausing on the result card: **one card per document**, with a single relevance
percentage, its strongest passages listed underneath, and the weaker ones behind a toggle. The
API returned seven separate chunks from that document; the score you see is its best one.

**7. Go to Ask and ask a question the document answers**

The answer comes back with `[1]`-style citations that are clickable — each one scrolls to the
source passage it came from, and cited sources are highlighted. Then ask something the library
**cannot** answer ("what is our revenue in Brazil?"). It refuses rather than inventing an
answer, and the response is flagged ungrounded.

That contrast is the whole point: it is answering from the library, not from the model.
→ **Proves the RAG path end to end.**

**8. Back in Upload, upload the exact same file again**

Blocked immediately with "This exact file is already in the library as ...". Nothing was parsed
or embedded — the check ran on the hash before any cost was paid.
→ **Proves the LIB-UI-06 hard block.**

**9. Edit a sentence in the case study, save as a new filename, upload that**

Now the upload **succeeds** but carries a near-duplicate warning. Explain the distinction: a
different hash means it is not the same bytes, but 0.95+ cosine similarity means it is
substantially the same document, and the human decides.
→ **Proves the LIB-UI-06 soft warning.**

**10. Switch the category to Methodology, upload and train the methodology document**

Chunks are labelled `Phase 1: ...`, `Phase 2: ...` in document order.
→ **Proves LIB-IDX-03.**

**11. Switch to Company, upload and train the certificate**

It is **not** split into sections, and the doc type was classified automatically (Certificate,
Registration, Tax, …). Explain that splitting a certificate would divorce its scope from its
number, which is worse for retrieval — so single-purpose indexing is a decision, not a
limitation.
→ **Proves LIB-IDX-04.**

**12. Click Train again with everything already indexed**

Nothing re-runs. Every document is reported as skipped. Then upload one new file and Train:
only the new one is processed.
→ **Proves LIB-IDX-07, the incremental requirement.**

**13. Return to Overview, then open Flower**

Overview gives per-category counts, total chunk count, the embedding model and dimension.
Flower at http://127.0.0.1:5555 shows the completed task history with real durations.

### Optional extras worth showing

- **OCR** — train the scanned image-only PDF. There is no text layer; pytesseract extracts the
  text and it becomes searchable.
- **Rejection path** — try to upload a `.txt` or `.exe`. Clean 400 with the allowlist in the
  message.
- **Failure handling** — train a corrupt PDF. The job goes to **Failed**, the reason is stored
  on the document, and the rest of the library is untouched.
- **The tests** — `docker compose exec api pytest` in a terminal, 96 passing, no database or
  network required.
- **Swagger** — http://127.0.0.1:8000/docs, to show the API is the deliverable and the UI is
  just one client of it.

### Reset between demos

```bash
docker compose down -v && docker compose up -d --build
```

```bash
docker compose exec api alembic upgrade head
```

`-v` removes the database, the uploaded files **and** the model cache — so re-warm the model
before the next run.

---

## 14. What to push to the GitHub repo

> **This directory is not a git repository yet.** `git status` reports *fatal: not a git
> repository*. The steps below initialise one safely.

### Initialising, first time

```bash
cd "C:/Users/Muhammad Afnan Khan/Desktop/VR_Project"
```

```bash
git init
```

Before staging anything, confirm `.gitignore` is doing its job. This must print nothing:

```bash
git status --porcelain --ignored | grep -E "^!! \.env$"
```

Actually the safest single check is to list what git *would* add and read it:

```bash
git add --dry-run .
```

Read that output and confirm `.env` is absent from it. Then:

```bash
git add .
```

```bash
git commit -m "Evidence Library subsystem (WBS Section 6)"
```

```bash
git branch -M main
```

```bash
git remote add origin <your-repo-url>
```

```bash
git push -u origin main
```

### Push these

| Path | Why |
|---|---|
| `README.md` | This file |
| `.gitignore` | Must be committed, or the ignore rules do not travel |
| `.env.example` | The template. Safe — it has no real secrets |
| `docker-compose.yml` | Service topology |
| `backend/Dockerfile` | Image definition |
| `backend/requirements.txt` | Pinned dependencies |
| `backend/pytest.ini` | Test configuration |
| `backend/alembic.ini`, `backend/alembic/**` | Schema history, including `versions/0001_initial.py` |
| `backend/app/**` | All application code |
| `backend/tests/**` | All 96 tests. A subsystem without its tests is not reviewable |
| `frontend/**` | The test UI — it is how WBS 6.2 is demonstrated |
| `check.sh` | The end-to-end status check |

### Never push these

| Path | Reason |
|---|---|
| **`.env`** | Contains the real database password and API key. Already gitignored — keep it that way |
| `storage/` | Uploaded client documents. Potentially confidential, and large |
| `*.pem`, `*.key` | Private keys |
| `__pycache__/`, `*.pyc`, `.pytest_cache/`, `.ruff_cache/`, `.mypy_cache/` | Build artefacts |
| `.venv/`, `venv/` | Local environments |
| `.fastembed_cache/` | ~90 MB model binary. It re-downloads on demand |
| Extracted `*.txt` working files | Caught by the `*.txt` rule |
| `.vscode/`, `.idea/`, `.DS_Store`, `Thumbs.db`, `desktop.ini` | Editor and OS noise |

The existing `.gitignore` already covers every row in that table. Its `*.txt` rule has an
explicit `!requirements.txt` exception, so the dependency file is still tracked.

> **Check `.env.example` before every commit.** It is committed by design, which makes it the
> easiest place to leak a key by accident. Every value in it must be a placeholder.

### The planning documents — a judgement call

`Implementation_Plan_Maryam.docx`, `SRS_2_Shaheer.docx`, `WBS_Yasir.xlsx` and
`Scope_of_Work_DPL.pdf` are **not** gitignored, so `git add .` will stage them.

Decide deliberately:

- **Internal or private repo** → commit them. They are the requirement source of truth and
  belong with the code.
- **Public repo, or a repo shared outside the team** → do not. `Scope_of_Work_DPL.pdf` is a
  client document, and the WBS names individual engineers. Add them to `.gitignore` first:

```bash
printf '\n# Planning documents — internal only\n*.docx\n*.xlsx\nScope_of_Work_DPL.pdf\n' >> .gitignore
```

### If a secret is ever committed

Deleting the file in a later commit does **not** remove it — it stays in history and remains
retrievable. Rotate the exposed credential first (change the database password, revoke the API
key at the provider's console), then rewrite history with `git filter-repo`, then force-push.
Rotating first is what actually protects you; the history rewrite is cleanup.

The same applies to a key pasted into a chat, a screenshot, or a terminal that logs its
scrollback. Exposure is exposure. Rotate.

### Suggested branch workflow

`main` stays deployable. Work on branches named for the requirement, so reviewers can map a
diff to the WBS:

```bash
git checkout -b feature/LIB-IDX-06-metadata
```

Never push directly to `main` once anyone else is consuming the repo. Open a PR and reference
the requirement id in the title.

---

## 15. Security status

### ⚠️ No authentication yet

Every endpoint is **unauthenticated**. Auth is WBS 1.2 (`AUTH-01..06`), owned by another
engineer and not started, so there is nothing to integrate with. Anyone who can reach the port
can upload, list, or delete documents.

Mitigations in place: extension/MIME allowlist, size cap, UUID-generated storage names (never
client paths), and Compose binds every service to `127.0.0.1`. Route handlers take a
`current_user` dependency stub so wiring real JWT is a one-file change.

**Do not expose this to a network until 1.2.x lands.**

### What is already hardened

| Control | Where |
|---|---|
| Extension allowlist — 8 types, nothing else | `services/storage.py:ALLOWED_EXTENSIONS` |
| Size cap, default 100 MB; empty files rejected | `services/storage.py:validate_upload` |
| Client filenames used for their **extension only**; files stored as `{uuid}{ext}`, so `../../etc/passwd` cannot escape | `services/storage.py:save_upload` |
| Image serving rejects any path syntax outright rather than sanitising it, then re-checks the resolved path is inside the document's own directory | `api/library.py:get_image` |
| Every service bound to `127.0.0.1` | `docker-compose.yml` |
| CORS restricted to an explicit origin list | `app/config.py:cors_origins` |
| Secrets in `.env` only, gitignored, with `.env.example` as the committed template | `.gitignore` |
| Error messages truncated (2000 chars on the row, 500 on the wire) so a stack trace cannot bloat the DB or the UI | `tasks/indexing.py:_fail` |
| Answer text HTML-escaped **before** citation markers become links, so answer content cannot inject markup | `frontend/js/app.js:linkCitations` |

### Known gaps, tracked deliberately

1. **No authentication or authorisation** — blocked on WBS 1.2.
2. **The WebSocket has no auth path even after 1.2** — browsers cannot set an `Authorization`
   header on a WebSocket, so it needs a query-param or subprotocol token. Anyone who knows a
   job UUID can watch its progress.
3. **No rate limiting** — an unauthenticated caller can upload until the disk fills.
4. **MIME mismatches are not fatal** — browsers are inconsistent about Office MIME types, so the
   extension is treated as authoritative and parsing fails loudly on a genuinely malformed
   file. This is a deliberate trade-off, documented in `validate_upload`.
5. **Uploaded documents are not scanned for malware.**
6. **Text is sent to a third-party LLM** when `OPENAI_API_KEY` is set — up to 6000 characters of
   a case study for parsing fallback, 3000 of a company document, and up to 24000 characters of
   retrieved passages on every `/ask` call. If client documents may not leave the network, set
   `LLM_ENABLED=false`; parsing falls back to heuristics only, search is unaffected, and the
   test suite already proves that path works.
7. **`/ask` is unauthenticated like everything else**, and it will summarise any indexed
   document for anyone who can reach the port. That is the same exposure as `/search`, but it
   reads more like a leak because the output is prose.

---

## 16. Troubleshooting

### Start here

```bash
./check.sh
```

It stops at the first failure, so the first `FAIL` line is the actual problem rather than the
last symptom. The entries below are the failures worth explaining.

### `alembic upgrade head` fails: `type "document_category" already exists`

The enum type is already in the database but the migration tries to create it again. This
happens when the tables were created outside the migration, or a partial run left the types
behind.

**Wiping the volume is not the fix, and usually not what you want** — it destroys every indexed
document to work around a bookkeeping problem. Two better options:

If the schema is already correct and only the revision record is missing, stamp it:

```bash
docker compose exec api alembic stamp head
```

If the migration itself is creating a type SQLAlchemy has already emitted, the migration should
declare the enum with `create_type=False` and create it explicitly once — that is how
`0001_initial.py` handles it. `postgresql.ENUM(..., create_type=False)` tells SQLAlchemy the
type is managed by hand rather than auto-created per column.

Check what the database actually has before choosing:

```bash
docker compose exec postgres psql -U evidence -d evidence_library -c "\dt"
```

```bash
docker compose exec postgres psql -U evidence -d evidence_library -c "\dT"
```

Only as a genuine last resort, on a database you are willing to lose:

```bash
docker compose down -v && docker compose up -d
```

### An `.env` change had no effect

Environment variables are baked into the container at start. `docker compose restart` restarts
the process inside the **existing** container, which still holds the old values. Recreate:

```bash
docker compose up -d --force-recreate api worker
```

This is the single most common "I changed the key and nothing happened" cause.

### Docker build fails with `ResolutionImpossible` on pillow

`fastembed 0.5.1` requires `pillow>=10.3.0,<11.0.0`. `requirements.txt` pins `pillow==10.4.0`
for exactly this reason — read the comment above the pin before changing it.

### A test edit does not take effect

`backend/tests` is not volume-mounted. Rebuild:

```bash
docker compose build api worker && docker compose up -d
```

### First Train hangs at "Generating Embeddings"

The worker is downloading the ~90 MB model. Watch it:

```bash
docker compose logs -f worker
```

You are waiting for `Loading embedding model` then `Embedding model ready`. Subsequent runs
read from the `fastembed_cache` volume.

### Search returns nothing after a successful Train

Check in this order:

1. Is the document actually indexed? `GET /api/library/documents?status=indexed`
2. Are there chunks? `GET /api/library/stats` → `chunk_count`
3. Is `min_similarity` too high? Retry with `min_similarity=0`.
4. Are you searching in the UI? It hides everything below **50%**. The API has no such floor —
   compare against `GET /api/library/search?q=...&min_similarity=0` before concluding the index
   is empty.

Only `training_status=INDEXED` documents with non-null embeddings are searchable.

### `/ask` answers "The library does not contain an answer to this question"

That is the designed refusal, not a bug. It means no retrieved passage cleared the 0.25
similarity floor, or the model judged the passages insufficient. Check what retrieval actually
found:

```bash
curl "http://localhost:8000/api/library/search?q=<your+question>&min_similarity=0"
```

If the passages there do answer the question, the floor is the problem. If they do not, the
library genuinely lacks the evidence — which is the honest answer.

### `/ask` returns sources but no generated answer

Generation is off. `./check.sh` prints `llm off` in this case. Either `LLM_ENABLED=false` or
`OPENAI_API_KEY` is blank — and remember an `.env` fix needs `--force-recreate`, not `restart`.

### `/health` reports `degraded`

The `database` field names the actual error. Most often `POSTGRES_PASSWORD` and the password
embedded in `DATABASE_URL` have drifted apart in `.env` — they must match.

### Progress bar never moves

The API and the worker are separate containers. Confirm the worker is alive and consuming:

```bash
docker compose ps
```

```bash
docker compose logs --tail=50 worker
```

If the worker is up but idle, Redis is likely unreachable from one of the two containers; the
WebSocket will have told the client to fall back to polling `/api/library/jobs/{id}`.

### Everything is broken and you want a clean slate

```bash
docker compose down -v && docker compose build --no-cache && docker compose up -d
```

```bash
docker compose exec api alembic upgrade head
```

---

## Current status

- All 14 WBS Section 6 requirements implemented.
- **96 tests passing** (`docker compose exec api pytest`), no external dependencies required.
- Retrieval **and** generation both working — `POST /api/library/ask` answers from the indexed
  library with citations, and refuses when the library cannot support an answer.
- Embeddings are 768-dim (`bge-base-en-v1.5`), matching the WBS 1.1.3 `chunks.embedding` column.
- Data models adopted from WBS 1.1.2/1.1.3 rather than defined in parallel.
- Blocked on WBS 1.2 for authentication; every seam for it is in place.
- `frontend/` is a five-view test harness pending Section 8.

