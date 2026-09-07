# VR-Nexus — Deployment & Operations

`README.md` covers running VR-Nexus for development. This document covers running
it in production. It preserves the existing Docker architecture — the same
images, volumes and storage layout — and adds only what production needs:
a built frontend behind nginx, and a compose file that runs the API without a
hot-reloading source mount.

## Two compose files

- **`docker-compose.yml`** — development. The API runs with `--reload` over a
  mounted source tree, every service is published to `127.0.0.1`, and there is
  no frontend container (you run `npm run dev`). Unchanged.
- **`docker-compose.prod.yml`** — production. The API and worker run the code
  baked into their image, only the frontend is exposed (nginx proxies `/api` and
  `/ws` inward), and Postgres/Redis are not published to the host at all.

## Production bring-up

```bash
cp .env.example .env          # then edit — see "Configuration" below
docker compose -f docker-compose.prod.yml build
docker compose -f docker-compose.prod.yml up -d postgres redis
docker compose -f docker-compose.prod.yml run --rm api alembic upgrade head
docker compose -f docker-compose.prod.yml up -d api worker frontend
```

The app is then served on `http://<host>/`. Flower (the Celery dashboard) comes
up with `docker compose -f docker-compose.prod.yml up -d flower`, bound to
`127.0.0.1:5555` — reach it over an SSH tunnel rather than exposing it.

Migrations are a deliberate separate step, for the reason the dev flow documents:
the `vector` extension must exist before any table with a `vector` column is
created, and `docker/init-extensions.sql` runs `CREATE EXTENSION vector` on the
database's first start. An older Postgres volume from before that mount existed
will skip it — connect and run `CREATE EXTENSION IF NOT EXISTS vector;` by hand.

## Configuration

`.env` at the repo root is read by compose and injected into every container.
Five settings have no default and the app refuses to start without them:
`DATABASE_URL`, `REDIS_URL`, `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`,
`JWT_SECRET_KEY`. In addition, set a real `POSTGRES_PASSWORD` — the production
compose fails fast if it is unset.

`JWT_SECRET_KEY` signs every access token. Generate a strong random value and
keep it stable — changing it logs everyone out (which is also the correct
emergency response if it ever leaks).

### Language-model configuration

VR-Nexus runs on a **single LLM provider: Google Gemini**, through Gemini's
OpenAI-compatible endpoint. One key powers everything that generates text — both
tender requirement extraction (Stage 2 of the pipeline) and the Evidence Library
assistant (`/api/library/ask`) and auto-tagging:

```
OPENAI_API_KEY=<your Gemini API key>
OPENAI_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
OPENAI_MODEL=gemini-3.6-flash
LLM_ENABLED=true
```

There is no Anthropic key and no second provider. Embeddings are separate and
run **locally** through `fastembed` (no key, no network) — this Gemini key is not
used for them, so the Evidence Library indexes and searches with or without it.

With `OPENAI_API_KEY` empty (or `LLM_ENABLED=false`): library indexing and search
still work, and the assistant's **Find** mode plus the `sources` on **Ask** still
return passages straight from the vector index — but generated answers are
disabled and **tender extraction cannot run**, so set the key before analysing a
tender.

Keep the root `.env` and `backend/.env` in step: compose reads the root one, and
a native `uvicorn` run from `backend/` reads `backend/.env`.

### Extraction speed & tuning

Tender extraction makes one LLM call per ~2000-token chunk, so a large tender is
many calls. Two settings govern how fast that goes:

- **`EXTRACTION_CONCURRENCY`** (default `4`) — how many chunks are extracted at
  once. Raise it (8–10) on a paid Gemini tier for more speed; lower it to `2` if
  the free tier returns `429` / `RESOURCE_EXHAUSTED` a lot. It is the main knob.
- A **60-second per-request timeout** is baked into the client so one slow or
  rate-limited call can no longer stall a run (the SDK default was 600s).

The ultimate ceiling is Gemini's requests-per-minute limit on your key: on the
free tier a big tender still takes a few minutes no matter the concurrency. If
you see many `429`s in the worker log, either move to a paid tier (then raise
`EXTRACTION_CONCURRENCY`) or accept the pace. A crashed/restarted worker mid-run
does not corrupt anything — re-upload the tender to re-extract cleanly.

## TLS / HTTPS

The `frontend` service serves plain HTTP on port 80 and is the single public
entry point. For HTTPS, terminate TLS in front of it — the two low-friction
options:

- **Caddy** in front of `frontend:80`, which obtains and renews Let's Encrypt
  certificates automatically. Add it as one more service on the compose network.
- **nginx + certbot** on the host, proxying `443 → frontend:80`.

Do not expose the `api` service directly; all browser traffic should go through
the frontend, which already proxies `/api` and `/ws` to it with the correct
WebSocket upgrade headers and a 120 MB body limit for uploads.

## The frontend image and the lockfile

`myapp/Dockerfile` builds the SPA with `npm install` (rather than `npm ci`) so a
`package-lock.json` that has not yet been regenerated after a dependency change
still builds. Once you have run `npm install` locally and committed the updated
lockfile, switch that line to `npm ci` for reproducible builds.

## Data, backups and persistence

Three named volumes hold all state:

- `postgres_data` — the database (users, tenders, requirements, matches, the
  library index). **This is what to back up.** `pg_dump` on a schedule is enough.
- `storage_data` — uploaded tenders, library assets, and generated output
  folders/zips. Back this up alongside the database; a database row that
  references a file whose bytes are gone (e.g. a restored DB against an empty
  storage volume) will 404 honestly rather than crash, but the file is lost.
- `fastembed_cache` — the ~130 MB embedding model, downloaded on first indexing.
  Not worth backing up; it re-downloads.

`docker compose down` keeps all three; only `docker compose down -v` wipes them.

## Scaling notes

- The `worker` runs the tender pipeline and library indexing. Raise
  `--concurrency` or run more `worker` replicas to process more tenders in
  parallel; they share the queue through Redis.
- The `api` runs with `--workers 2` in the production compose; raise it or scale
  the service for more concurrent HTTP/WebSocket load.
- Postgres and Redis are single instances. For higher availability, move them to
  managed services and point `DATABASE_URL` / `REDIS_URL` at them.

## Health

`GET /health` performs a real `SELECT 1`, so it fails when the database is
unreachable — wire it into your orchestrator's health probe. Flower shows the
Celery queue and task history.
