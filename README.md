# VR-Nexus

One frontend, one backend, one database.

`myapp/` is the React frontend — Vite, React 19, TypeScript, Tailwind v4. `backend/` is the FastAPI service behind it, and it covers three things: authentication, the tender analysis pipeline, and the Section 6 Evidence Library — document upload, parsing, chunking, local embeddings, pgvector search, and grounded question answering over the indexed library.

There used to be two backends. There is now one.

## How this backend came to be

Two working trees existed for a while and drifted apart, which is the failure this merge exists to end.

`VR-Nexus-maryam/backend/` owned the real database: the users table, the tender pipeline, the five-migration Alembic chain that has actually been applied, and a package-style layout with real JWT authentication. `VR_Project/` was a flatter prototype focused only on the Evidence Library, with authentication stubbed out to a no-op development principal.

The merged tree in `backend/` is maryam's, because it was the superset and because its library contract already matched what the frontend was written against. The prototype's genuine additions were folded in on top: the file-serving endpoint the PDF viewer needs, the eight-file pytest suite, this README, `.env.example`, a fuller `docker-compose.yml`, and a handful of corrected comments.

Both source folders are now archival. Read them to learn what something used to do; do not run them, and do not assume a fix made in one has reached the other. Everything the frontend talks to lives in `backend/`.

## Prerequisites

Docker Desktop is the short path and handles everything below for you.

Without it you need Python 3.12, PostgreSQL 16, Redis 7, and Node 20 or newer. Tesseract is optional and only matters for OCR fallback on scanned PDFs.

**PostgreSQL needs the `pgvector` extension, and it is a prerequisite rather than something the migrations install.** `chunks.embedding` and `tender_chunks.embedding` are both declared `vector(768)`, so `CREATE EXTENSION vector` has to have already run in the target database before `alembic upgrade head` touches it. Under Docker this is handled by `docker/init-extensions.sql`, which the postgres service mounts into `/docker-entrypoint-initdb.d/`. That directory only runs on first start against an empty data volume, so an older volume from before that mount existed will silently skip it — connect and run `CREATE EXTENSION IF NOT EXISTS vector;` by hand, or drop the volume. A native install needs `setup_database.sql`, and needs a Postgres with pgvector actually built in; the stock installer does not include it.

## Configuration, and the two places `.env` lives

`.env.example` at this directory is the canonical template. It documents every setting, including the ones that do nothing and why they are still listed.

Copy it to one of two places depending on how you run the backend, and note that the contents are identical either way:

```
Docker:  cp .env.example .env               # here, beside docker-compose.yml
Native:  cp .env.example backend/.env       # beside app/ and alembic.ini
```

The split is not arbitrary. Compose reads `env_file: .env` relative to the compose file and injects the values into each container as real environment variables. A native `uvicorn app.main:app` started from `backend/` has pydantic-settings read `env_file=".env"`, and that resolves against the **process working directory** — so it looks for `backend/.env` and finds nothing if you only filled in the root copy. If you use both paths, keep the two files in step; nothing checks that they agree.

**Five settings have no default and the app will not start without them:** `DATABASE_URL`, `REDIS_URL`, `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND` and `JWT_SECRET_KEY`. Leave any of them out and you get a pydantic `ValidationError` at import time, before the first request. That is deliberate — a backend quietly running on a default signing key is worse than one that refuses to boot.

**Settings uses `extra="ignore"`, so a key it does not recognise is swallowed rather than rejected.** The one to watch for is `STORAGE_DIR`: it was the prototype's single storage setting, it no longer exists, and setting it has no effect whatsoever. Storage is now four values — `STORAGE_ROOT`, `TENDER_STORAGE_DIR`, `LIBRARY_STORAGE_DIR`, `OUTPUT_STORAGE_DIR` — because tender uploads, library assets and generated output folders have different lifetimes.

## Running it with Docker Compose

From this directory:

```bash
cp .env.example .env          # then set JWT_SECRET_KEY and POSTGRES_PASSWORD
docker compose up -d postgres redis
docker compose run --rm api alembic upgrade head
docker compose up -d api worker
```

The API is then on `http://127.0.0.1:8000` with interactive docs at `/docs`. Flower, for watching the Celery queue, comes up with `docker compose up -d flower` on port 5555.

Migrations are a separate step on purpose. The app does not create tables on startup, because the `vector` extension has to exist before any table referencing a `vector` column can be created — ordering matters and is not left to import side effects.

The first indexing job is slower than every one after it. `fastembed` downloads the `BAAI/bge-base-en-v1.5` ONNX model on first use, roughly 130 MB, into the `fastembed_cache` volume. It survives `docker compose down` and is only lost if you pass `-v`.

Host ports are 5432, 6379, 8000 and 5555, and containers are named `vrnexus_*`. Port 8000 in particular has to stay as it is, because `myapp/vite.config.ts` proxies to `127.0.0.1:8000` and a proxy pointing at the wrong port fails in a way that reads like a backend bug. If those ports are already held, `docker ps` will show you by which stack.

## Running it on the host

Useful when you want a debugger on the API. Bring the databases up in Docker and run the Python processes yourself:

```bash
docker compose up -d postgres redis

cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1        # PowerShell
pip install -r requirements.txt
cp ../.env.example .env
```

Then edit `backend/.env`, because the committed defaults are container-network values. The hostnames `postgres` and `redis` only resolve inside the compose network, so from the host they become `127.0.0.1`:

```
DATABASE_URL=postgresql+psycopg://tender_admin:tender_dev_password@127.0.0.1:5432/tender_analysis
REDIS_URL=redis://127.0.0.1:6379/0
CELERY_BROKER_URL=redis://127.0.0.1:6379/0
CELERY_RESULT_BACKEND=redis://127.0.0.1:6379/0
```

The storage paths need the same treatment — `/data/storage` is the container volume, so point them at a real local directory. A relative path like `./storage` resolves against each process's working directory, so either start both uvicorn and the worker from `backend/` or give absolute paths. The API writes the upload and the worker reads it back to parse it; if the two disagree, uploads succeed and every indexing job fails with a missing file.

The driver must be `psycopg` (v3), not `psycopg2`. `requirements.txt` pins `psycopg[binary]` and `psycopg2` is not installed, so a DSN of the form `postgresql://` without the `+psycopg` suffix will fail to find a driver.

Then, in three terminals:

```bash
alembic upgrade head
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
celery -A app.celery_app worker --loglevel=info --pool=solo
```

`--pool=solo` is for Windows. Celery's default prefork pool does not work there, and the failure mode is a worker that starts, announces itself ready, and silently processes nothing.

## The frontend

```bash
cd myapp
npm install
npm run dev
```

Vite serves on 5173 and proxies both `/api` and `/ws` to `127.0.0.1:8000`, so the browser only ever makes same-origin requests. That is why `VITE_API_BASE_URL` is left empty — the client builds relative URLs and the proxy does the rest. Setting it to an absolute origin turns every request cross-origin and puts you at the mercy of the `CORS_ORIGINS` list, which is a larger change than it looks.

The proxy target is `127.0.0.1`, not `localhost`, and that is on purpose. Node may resolve `localhost` to `::1` while uvicorn is bound to IPv4 only, producing a connection refused that reads like the API is down.

`npm run build` typechecks before it bundles, so it is the real gate on the TypeScript. `npm run typecheck` alone is faster when that is all you need.

## What the API exposes

Authentication is at `/api/auth`. `POST /register` returns `201` with the created user and no tokens — registration does not sign you in, and the frontend redirects to the login page with a success message rather than assuming a session. `POST /login` returns an access token, a refresh token and the user; it answers with a deliberately generic `401` so a caller cannot distinguish a wrong password from an unknown account, `423` once an account is locked out after five consecutive failures, and `403` if the account is inactive. `POST /refresh` takes `{refresh_token}` and rejects an access token passed in its place. `GET /me` returns the current user, and the frontend calls it on startup to validate a restored session.

The Evidence Library is at `/api/library`, and the tender endpoints are at `/api/tenders`, served by two routers that deliberately share that prefix.

Two WebSocket endpoints carry progress, and they are mounted at the root rather than under `/api`. Library indexing publishes to `/ws/library/{job_id}`, which replays a snapshot from the persisted `index_jobs` row on connect so a late subscriber is not left blank. The tender pipeline publishes to `/ws/tenders/{id}/progress` and takes its JWT as a **query parameter**, because browsers cannot set headers on a `WebSocket`.

`/health` performs a real `SELECT 1` rather than returning a hardcoded `ok`, so it fails when the database is unreachable. `/demo` serves `backend/static/tender_console.html`, a standalone dark-theme console covering the tender upload-and-track flow. `myapp/` now covers that flow itself — see the section below — so `/demo` has stopped being the only way to exercise it and is now a fallback for checking the pipeline without the React app running. It is not part of `myapp/` and can go once you no longer want that.

## What the frontend actually covers

Ten screens are built and reachable. Authentication is sign-in and register. The dashboard is one page. The Evidence Library is a section of three — the library listing, an upload screen, and live indexing progress — plus a PDF viewer that sits outside the section's tabs because it is one document open for reading rather than a fourth peer of the others. Tender Analysis mirrors that shape exactly: a listing, an upload screen, live pipeline progress, and a detail URL outside the tabs.

Five routes render a placeholder inside the real dashboard shell. Four are sidebar destinations — AI Assistant, Activity, Settings, Profile. The fifth is the tender review workspace at `/tender-analysis/:tenderId`, which is the one screen the tender flow reaches but does not yet draw: the backend already returns extracted requirements, evidence matches and a scored report for a finished tender, and nothing renders them.

Every placeholder is registered deliberately rather than left out, and this is the part worth remembering before adding a link anywhere. `myapp/src/app/router.tsx` ends in a catch-all that sends unknown URLs to sign-in, so an unregistered path does not show a "not found" page — it signs the user out. A link to a route that does not exist is therefore not a dead end, it is a logout button. Register the path first, even if all it renders is `PlaceholderPage`.

Two API surfaces have full backend schemas and no frontend at all: `/api/library/search` and `/api/library/ask`. There are no TypeScript types, no service wrappers and no UI for either.

## Layout

```
vr-nexus-frontend/
  .env.example          canonical template — copy to ./.env or ./backend/.env
  docker-compose.yml    postgres, redis, api, worker, flower
  setup_database.sql    native-install database and pgvector bootstrap
  docker/
    init-extensions.sql runs CREATE EXTENSION vector on first container start
  backend/
    app/
      main.py           app factory, CORS, /health, /demo, six routers
      celery_app.py     explicit task includes, set_default()
      core/             config, database, security, ws_manager
      models/           SQLAlchemy: user, document, chunk, index_job,
                        tender, tender_chunk, requirement, audit_log, enums
      schemas/          Pydantic: auth, tender, library
      api/
        deps.py         get_current_user and friends
        routes/         auth, library, library_ws, tender, tenders, ws
      services/         tender side: extraction, pdf_extraction, chunking,
                        tender_storage, progress, pipeline_stages
        library/        library side: storage, chunking, embeddings, search,
                        metadata, llm, rag, library_progress
          parsers/      extract, case_study, methodology, company, registry, base
      tasks/
        library_indexing.py   the Celery indexing pipeline
    alembic/versions/   five migrations, strictly linear
    tests/              8 files, no database and no network required
    static/             tender_console.html, served at /demo
    requirements.txt
    Dockerfile
    pytest.ini
  myapp/                the Vite + React + TypeScript frontend
```

## Tests

The backend suite runs with nothing else running — no database, no Redis, no network, no downloaded model:

```bash
cd backend
pytest
```

`tests/conftest.py` does three jobs. It sets the five no-default settings to throwaway values before importing anything from `app`, because otherwise collection dies on a `ValidationError` before a single assertion runs. It stubs the embedding provider with deterministic fake vectors. And it turns the LLM off for every test by default via an autouse fixture, so the suite is fast and its failures say something about the code rather than about the environment.

`pytest.ini` sets `pythonpath = . tests`, which is what lets a test write `from conftest import CASE_STUDY_TEXT` — the shared sample documents live there rather than in fixtures, because several tests assert on their exact wording.

The eight files cover upload validation and path safety (`test_storage.py`), chunk windowing and overlap (`test_chunking.py`), the three parsers' section and phase resolution (`test_case_study_parser.py` and `test_parsers.py`), metadata precedence of user over heuristic over model (`test_metadata.py`), duplicate detection (`test_duplicates.py`), and grounded answering including every way it can fail (`test_rag.py`).

There is no coverage of the HTTP layer, the auth routes, the Celery task or the tender pipeline. All of those need a live Postgres with pgvector, which is the line this suite deliberately does not cross. It is a gap worth closing, not a design decision to preserve.

## Things that look like duplication and are not

The merged tree contains several pairs that a reasonable person would try to unify. Each is deliberate, and each is documented at the place it applies as well as here.

**There are two service families, and the split follows the two products.** `app/services/` is the tender side; `app/services/library/` is the Evidence Library. They were written by different people against different requirements and have no reason to converge.

**There are two chunkers, and this is the live trap.** `app/services/library/chunking.py` produces roughly 800-token windows with 100 tokens of overlap, bounded by section, and returns a library `Chunk`. `app/services/chunking.py` produces roughly 2000-token windows with 200 tokens of overlap, bounded by page, and returns a `TenderTextChunk`. **Both export a function named `chunk_text`**, so `from app.services import chunking` when you meant the library one resolves silently to the wrong module and produces plausible, wrong results instead of an `ImportError`. Always import the full path.

**There are two progress systems** for the same reason: tender progress goes through Redis channel `tender:{id}:progress` with a 24-hour state key, library progress through `library:progress:{job_id}` with its snapshot persisted in the `index_jobs` row.

**Celery task names are frozen and intentionally do not match their module.** The tasks live in `app/tasks/library_indexing.py` but stay registered under their original `app.tasks.indexing.*` names, because the registered name is the routing key embedded in every already-queued message. Renaming them would orphan any message in flight. `app/celery_app.py` lists its task modules explicitly with `include=[...]` rather than walking the package, and calls `set_default()` so FastAPI's worker threads resolve `current_app` correctly instead of falling back to `amqp://localhost:5672`.

**The first migration's filename does not match its revision id.** `0001_initial.py` contains revision `97d1f63e027d`. The chain is strictly linear from there: tender progress columns, then `tender_chunks`, then the Section 6 library additions, then optional user contact fields at the head. Alembic reads the id inside the file and ignores the filename, so this is cosmetic.

**`0b55a5033c01` adds NOT NULL columns with no server default**, which would fail on a non-empty table. It has been left exactly as written because it has already been applied to the real database, and editing an applied migration is worse than the sharp edge it leaves behind.

## Twenty files that exist only to raise

Nothing in this environment could delete files during the merge, so the prototype's orphaned modules were emptied and replaced with a docstring and a `raise ImportError`. They are `app/config.py`, `app/db.py`, `app/models.py`, `app/schemas.py`, `app/api/library.py`, `app/api/ws.py`, six modules directly under `app/services/`, the seven files of `app/services/parsers/`, and `app/tasks/indexing.py`.

Each one names its live replacement and the specific failure it prevents. The two that matter most: the old `app/api/library.py` took its principal from a no-op development stub, so registering it — even accidentally, even second — would expose an unauthenticated copy of every library endpoint on the same paths. And `app/tasks/indexing.py` must raise rather than sit there importable, because a stray import would register a second set of tasks under those frozen names, and the last registration wins.

`app/models.py` and `app/schemas.py` are a special case: Python's path finder prefers a package over a same-named module in the same directory, so they are unreachable by construction and their raises can never fire. They are documentation.

**Deleting all twenty is safe and encouraged.** Neither `app/api/__init__.py` nor `app/services/__init__.py` re-exports any of them, `main.py` imports only from `app.api.routes`, and `celery_app.py` names its modules explicitly. They are tombstones for a merge, not part of the design.

## Two configuration values worth understanding

**`EMBEDDING_DIM=768` is not a free choice.** `chunks.embedding` and `tender_chunks.embedding` are `vector(768)` in the migration chain, and `BAAI/bge-base-en-v1.5` hits that width exactly. `EMBEDDING_PROVIDER`, `EMBEDDING_MODEL` and `EMBEDDING_DIM` move as a set, and changing them means writing a migration against both vector columns rather than editing a line. `embeddings.py` checks the width the model actually returns and raises with that instruction rather than letting pgvector reject the insert several steps later.

Library embeddings are local ONNX inference through `fastembed`, never an API call. That is why the whole indexing pipeline works with no credentials at all.

**The LLM is optional, and leaving it off is a supported configuration.** With `OPENAI_API_KEY` empty, `llm_available` is false and every caller falls back: the parsers use their heading heuristics, `metadata.py` uses its label and keyword rules, and `rag.py` returns retrieved passages without generating prose over them. Parsing, chunking, embedding, search and duplicate detection are unaffected. What you lose is auto-tagging polish on documents whose structure the heuristics cannot resolve, and generated answers on `/api/library/ask`.

`app/services/library/llm.py` uses the `openai` library with a configurable `OPENAI_BASE_URL` and `OPENAI_MODEL`, which covers OpenAI, Azure OpenAI, vLLM and Ollama alike. Tender requirement extraction is separate and calls Anthropic directly via `ANTHROPIC_API_KEY`; without it, tender uploads fail at the extraction stage with a message naming that setting while everything else keeps working.

**One thing from the prototype is deliberately not reproduced.** Its config carried `OPENAI_USER_AGENT=claude-cli/1.0.60 (external, cli)` and its `llm.py` sent that as a `default_headers` override, with a comment explaining that the endpoint *"allowlists client User-Agents and rejects the SDK default."* That value is not configuration. Its only function is to make the request look like Anthropic's first-party CLI so that a reseller's allowlist accepts it. It is omitted here, and the setting does not exist in `config.py` at all, so putting it in `.env` would do nothing.

This is the project's own stated rule rather than an imported one — `VR_Project`'s committed `.env.example` ships `OPENAI_USER_AGENT=vr-nexus-evidence-library/0.1` with the comment *"Identify this application; do not impersonate another client."*

No API key is committed anywhere in this repository. `OPENAI_API_KEY=` and `ANTHROPIC_API_KEY=` in `.env.example` are intentionally empty, and `.env` is gitignored and should stay that way.

## Troubleshooting

A worker that starts and processes nothing, on Windows, is almost always the Celery pool. Use `--pool=solo`.

`type "vector" does not exist` during `alembic upgrade head` means the extension was never created in that database. See the pgvector note under Prerequisites; an existing Postgres volume predating the `init-extensions.sql` mount is the usual cause.

`relation "chunks" does not exist` means the migrations have not run against the database the API is actually pointed at. Check `DATABASE_URL` — the compose form uses the hostname `postgres`, which does not resolve outside the compose network.

A `ValidationError` naming `JWT_SECRET_KEY` on startup means the process found no `.env` where it looked. From `backend/` it reads `backend/.env`, not the root one.

Every user suddenly logged out means `JWT_SECRET_KEY` changed. That invalidates every issued token, which is also the correct emergency response if it ever leaks.

A `404` on a progress WebSocket usually means the path was prefixed. Both sockets are mounted at the root — `/ws/library/{job_id}` and `/ws/tenders/{id}/progress` — not under `/api`. A tender socket that connects and immediately closes is usually the missing JWT query parameter.

A PDF that lists in the library but will not open in the viewer is a document row outliving its bytes. Rows are in Postgres and files are on the `storage_data` volume, and `docker compose down -v` wipes the second without touching the first, so `GET /api/library/documents/{id}/file` honestly returns `404` for a document that genuinely exists.

An upload returning `409` is a byte-identical duplicate, and it normally carries a structured body: `detail.message` for a person and `detail.duplicate` with the matching document. There is a second `409` on the same endpoint that carries only a plain string, reached when two uploads of the same bytes race between the hash check and the insert. It is rare, but a client that reads `detail.duplicate` unconditionally will find `undefined` there rather than a match, so treat the structured shape as the common case and not a guarantee.

A merely similar file uploads successfully and carries `duplicate_warning` instead, for a person to judge. `POST /train` returning documents under `skipped` is not an error either — that is what pressing Train twice looks like, and it is the point: training after adding one asset reindexes that asset, not the library.

`TESSERACT_CMD` set in `backend/.env` and apparently ignored is working as built. It is read with `os.getenv` in `pdf_extraction.py` rather than through Settings, and pydantic-settings does not export `.env` values into the real process environment. It works under compose, which injects real environment variables, but on a native run you have to set it in your shell. Every other setting goes through Settings and works either way.
