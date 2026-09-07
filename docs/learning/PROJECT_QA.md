# VR-Nexus Viva Preparation: Questions and Answers

A study aid for defending VR-Nexus, a Tender Intelligence and Evidence Matching Platform, in a viva, interview, or demonstration. Organized by topic, each with Q/A pairs written the way a student would say them out loud. It draws only on what the codebase and its own documentation show, including the parts that are unfinished, simplified, or dead code, because "what would you do differently" tests honesty as much as competence.

---

## 1. Project Overview and Motivation

**Q: In one sentence, what does VR-Nexus do?**
A: It takes an uploaded procurement tender PDF, often hundreds of pages, automatically extracts every requirement it contains, matches each requirement against a company's own evidence library using semantic search, and produces a reviewable Excel tracker plus a downloadable output package a bid team can submit.

**Q: Who is the user, and what does their day look like without this tool?**
A: A bid or proposal team member, typically non-technical, at a company responding to tenders. Without automation someone has to read a 200 to 400 page document, manually copy every clause that looks like a requirement into a spreadsheet, judge whether it is mandatory, work out its evaluation weight, then separately dig through case studies, certificates and methodology documents for proof the company can meet it. That is slow, error-prone under deadline pressure, and does not scale across several simultaneous bids.

**Q: What is actually automated versus left to a human?**
A: Reading the document, extracting requirements into a structured form, and finding candidate evidence via vector search are automated. The judgment call is not: every proposed match must be accepted, rejected, or reassigned by a human before a tender can be finalized, and nothing auto-finalizes. Getting a requirement or a match wrong in a real submission has real consequences, so the AI produces a first draft for review, not a final answer.

**Q: What does "evidence matching" mean concretely?**
A: Every library document is chunked and each chunk is embedded into a vector locally. Each extracted requirement's text is embedded the same way, and the system runs cosine-similarity search against the stored vectors in Postgres via pgvector. A match at 0.85 similarity or above auto-matches; 0.60 to 0.84 is offered as a suggestion a human must confirm; below that is treated as no evidence found and flagged. So it is "search by meaning across the company's own library, with similarity confidence deciding how much the system trusts its own suggestion."

**Q: Isn't it risky trusting an LLM to extract requirements accurately?**
A: Yes, and the design treats it that way. Extraction runs a strict JSON schema per chunk with deduplication, and the pipeline fails hard rather than continuing silently: if over 30 percent of chunks fail after retries, or zero requirements come out, the whole run raises rather than producing an incomplete result that looks finished. Compound or non-standard tender wording ("No/Advisory," "Financial / Pass-Fail") is kept verbatim in a raw column alongside the normalized value, so nothing gets silently rewritten. And nothing is finalized without human review.

---

## 2. High-Level Architecture

**Q: Walk through the major pieces and how they talk to each other.**
A: The client is a React SPA served by Vite. It talks over HTTP to FastAPI, which reads and writes PostgreSQL (with pgvector) through async SQLAlchemy. Slow work is never done in the request handler: FastAPI writes a job row and hands it to Celery, using Redis as the broker between the API process and the worker process. The worker does the heavy lifting (parsing, OCR, LLM calls, embeddings) and publishes progress to Redis as it goes. The frontend holds a WebSocket connection to a small FastAPI route that subscribes to those Redis messages and forwards them live. The sixth piece is Anthropic Claude, used for extraction, auto-tagging, and grounded question-answering.

**Q: Why do you need a background worker instead of doing everything in the request handler?**
A: An HTTP request has an implicit deadline; a client, proxy, or load balancer eventually gives up. Extracting 150-plus requirements by calling an LLM once per chunk, or OCRing dozens of scanned pages, can take minutes. Doing that inline means either the request times out with the client unsure whether it succeeded, or a web thread is tied up per upload, which does not scale. Celery splits "describe the work" from "do the work": the route creates a row and enqueues a task, returning in well under a second, while a separate worker process does the actual job independently of any request's lifetime.

**Q: How does the browser see progress if the request already returned?**
A: Through a WebSocket, not polling. The worker publishes progress payloads to a Redis Pub/Sub channel and also writes the latest payload to a plain key with a TTL, so a snapshot always exists. The frontend opens a WebSocket that, on connect, immediately sends the current snapshot (so a reconnecting client sees current state right away) and then subscribes to the channel for everything after. The server pushes the instant something changes, instead of the browser asking "done yet?" every second.

**Q: Redis plays three roles here. What are they, and why one instance?**
A: Celery broker (the task queue), progress cache (Pub/Sub plus the snapshot key), and short-lived single-use tokens (WebSocket tickets, password-reset redemption), leaning on Redis's atomic operations (GETDEL, SET NX) and built-in key expiry. One instance doing three well-separated jobs keeps the operational footprint small for a project this size; splitting them onto separate instances would be reasonable at much larger scale.

**Q: What happens if Redis goes down mid-pipeline?**
A: New tasks cannot be enqueued or picked up, and a running worker loses its ability to publish progress the moment it tries. A task's in-memory computation might continue briefly, but the broker dependency means this is a real single point of failure with no fallback broker or persistence layer today, worth naming honestly rather than glossing over.

---

## 3. Tech Stack Justification

**Q: Why FastAPI over Django or Flask?**
A: Native async support (the app spends most of its time waiting on I/O), automatic request validation and OpenAPI docs from Pydantic type hints, and a dependency-injection system that let authentication and role checks live in one place (`get_current_user`, `require_role`) instead of being reimplemented per route. Django would bring an ORM, admin panel and templating layer the project doesn't use, and its async story was less mature when this stack was chosen. Flask is closer in spirit but would mean hand-rolling the validation and DI layer FastAPI gives for free.

**Q: Why async SQLAlchemy rather than the classic sync ORM?**
A: The API is I/O-bound, mostly waiting on the database or a network call, not computing. Async SQLAlchemy lets one process handle many concurrent requests without blocking a thread per query, which matters because FastAPI runs on an async event loop and blocking calls would stall it. It costs real complexity (sessions, engines and query patterns all have async-specific quirks), but for an I/O-bound API it's the right tradeoff.

**Q: Why Celery and Redis instead of FastAPI's own BackgroundTasks?**
A: BackgroundTasks run in the same process, after the response, fine for something quick but wrong for work that can take minutes and needs to survive the web process restarting, needs retries and time limits, and needs to be observable and cancellable externally. Celery gives a durable, distributed queue: a task queued by the API stays in Redis until a worker, possibly on another machine, picks it up, and settings like `task_acks_late` and time limits give real guarantees about worker crashes. Worth the operational overhead for a pipeline calling an LLM 150-plus times per tender.

**Q: Why Postgres with pgvector instead of a dedicated vector database?**
A: Embeddings are one property of documents that already need to live relationally alongside users, tenders, requirements and audit logs. Keeping vectors in the same Postgres instance means they share transactions, backups, and joins with everything else, a chunk's category and its parent document's metadata can be filtered together with its embedding in one query. pgvector adds a native vector type and fast nearest-neighbor operators (`<=>` for cosine distance) directly inside Postgres, avoiding a whole extra system to deploy and keep in sync. A dedicated vector database would likely win at much larger scale, but not at this project's scale.

**Q: The plan specified Next.js; the build is Vite. What happened, and is that a problem?**
A: A genuine, documented deviation. The Implementation Plan called for Next.js 15 with the App Router; what was actually built is Vite plus React 19 using classic React Router (`<Routes>`/`<Route>`, not the data-router loaders/actions API). Functionally the two are similar for this app's needs, a single-page authenticated dashboard with no requirement for SSR or file-based routing, and nothing depends on a Next-specific feature. But it's a real deviation, likely drift across a team split across branches, that was reviewed afterward and deliberately kept rather than migrated, with Vite's simpler build model and faster dev server cited as a reasonable, if retroactive, justification.

**Q: Why Tailwind, and specifically v4?**
A: Utility classes styled directly in JSX avoid separate CSS files drifting out of sync across a multi-person project. v4 specifically runs as a Vite plugin rather than through PostCSS, so there is no separate `tailwind.config.js` or `postcss.config.js`; design tokens (colors, fonts, semantic surface/border tokens) are defined in CSS via the `@theme` directive in `index.css`, letting the same class names resolve differently under a dark-mode selector with no JS-side theme logic.

**Q: Why Anthropic Claude, and why two models (Sonnet and Haiku)?**
A: Claude is the single provider for every AI feature (extraction, auto-tagging, grounded Ask), reached through one API key via the OpenAI-compatible endpoint; the `openai` package here is just HTTP plumbing to Anthropic, not a second provider. The two-model split is cost and latency, not capability: extraction runs 150-plus times per tender doing mechanical, well-specified work ("copy this field verbatim"), so it uses the cheaper, faster Haiku-tier model (`ANTHROPIC_EXTRACTION_MODEL`). Grounded Ask has to weigh several retrieved passages and produce connected, cited prose, which justifies the stronger Sonnet-tier model (`ANTHROPIC_MODEL`). Making the model a per-call-site setting rather than one global constant turns that tradeoff into a config change, not a code change.

**Q: Why local embeddings instead of a hosted embeddings API?**
A: Anthropic doesn't serve an embeddings endpoint at all, so a hosted API would mean a second provider and a second API key purely for that one capability. More generally, a second external dependency is a second point of failure and a second credential to manage. The app runs `fastembed` (`BAAI/bge-base-en-v1.5`, 768-dim, ONNX, CPU-only) inside the Celery worker, no network call. The cost is a one-time model download and CPU time per document, slower than hosted throughput, but it removes an entire "the embeddings API is down or rate-limited" failure mode for the volume this project handles.

---

## 4. Security Design Decisions

**Q: Explain the access and refresh token design, and why two tokens.**
A: Login issues a short-lived access token (24 hours) sent on every request, and a longer-lived refresh token (7 days) used only to get a new access token via a dedicated refresh endpoint. The token used constantly is short-lived to limit exposure if it leaks; the refresh token, used rarely, can safely live longer without daily re-login. `decode_token` only checks signature and expiry, not token type, so each caller must check the `type` claim itself (access route requires `type == "access"`, refresh route requires `type == "refresh"`), stopping a leaked refresh token from working as an access token. Honest gap: refresh is stateless, the old refresh token isn't invalidated when a new pair is issued, so it isn't rotating, and a leaked refresh token stays valid until it naturally expires.

**Q: How does account lockout work, and why implement it?**
A: Login checks `locked_until` before checking the password. A wrong password increments `failed_login_attempts`, and reaching a threshold (five, by default) locks the account for a configured window, slowing brute-force password guessing. Login returns the identical "Incorrect email or password" error whether the email doesn't exist or the password is wrong, so the endpoint can't be used to enumerate registered emails. A successful reset also clears any lockout, since a forgotten password is often the actual reason for the lockout.

**Q: Explain the WebSocket ticket system fully, including why GETDEL matters.**
A: A browser's WebSocket constructor can't set custom headers, so it can't carry `Authorization: Bearer <token>`. Putting the real access token in the connection URL instead would leak a 24-hour credential into browser history, proxy access logs, and potentially a Referer header for as long as it stays valid. The fix: an already-authenticated HTTP endpoint mints a random 32-byte ticket and stores it in Redis with a 60-second TTL, scoped to a specific resource, so a ticket for one tender can't be pointed at another. The frontend connects using that ticket instead of the real token. `redeem_ticket` uses Redis's `GETDEL`, reading and deleting the key as one atomic operation, instead of a separate GET then DELETE. A WebSocket handshake can be retried or double-fired (a React effect re-running, a reconnect racing the original attempt), and a naive read-then-delete leaves a race window where two near-simultaneous attempts could both see the ticket as valid before either deletes it. GETDEL closes that window structurally: only the first caller ever succeeds, the second sees nothing, not a rare bug but something the operation makes impossible.

**Q: How is the password reset token made single-use, given a JWT's signature alone can't guarantee that?**
A: A bare JWT verifies successfully every time it's presented until it expires, no matter how many times. Reset tokens travel through email, where they can sit unread or get clicked twice by accident, so `create_password_reset_token` mints a random `jti` claim, and redemption goes through a Redis `SET ... NX` check keyed on that jti: the first successful redemption marks it used, every later attempt with the same token is rejected even though the JWT itself still verifies. `SET NX` performs "is this used, and if not, mark it used" atomically, closing the same kind of race window GETDEL closes, using the mirror-image primitive for "claim once" instead of "read and remove."

**Q: Is there per-user ownership on tenders and documents? What about IDOR risk?**
A: No, deliberately. The Evidence Library and tender workspace are shared resources for a whole internal team; any signed-in user can view, edit, or delete any tender or document, and `uploaded_by` exists for attribution, not access control. This was flagged explicitly in an external code review as a potential IDOR issue, since neither `_get_tender` nor `_get_document` checks ownership. The decision, made consciously, was to keep it fully shared, because this is a small internal tool for one team, not multi-tenant SaaS. That reasoning is now documented directly in both functions as an explicit trust boundary. It's a defensible answer at this scale, but it would need to change the moment this product serves more than one organization's data in one deployment.

**Q: Why do secrets live in .env and never get committed?**
A: A JWT secret, database credentials, or an API key committed to git is effectively permanently compromised the moment that history is pushed anywhere, deleting it in a later commit doesn't remove it from prior history. Keeping secrets in an untracked `.env`, read once via a cached settings object instead of scattered `os.getenv` calls, means values only exist where actually configured, and rotating a compromised secret doesn't require rewriting history. `alembic.ini` follows the same discipline: `sqlalchemy.url` is left blank and filled at runtime from settings, so the connection string exists in exactly one place.

---

## 5. The Tender Analysis Pipeline End to End

**Q: Walk through upload to visible progress.**
A: The upload route is thin: validate the file (PDF, under 100MB, non-empty), create a `Tender` row in `UPLOADED` state, save the bytes under a path keyed by the tender's UUID, publish an initial progress message, and enqueue the Celery task, returning in well under a second. Everything from parsing onward happens in that task in a separate worker process. The frontend mints a WebSocket ticket over an authenticated call, opens a progress socket that replays current state immediately, then streams updates as the worker moves through parsing, chunking, extraction, matching, reporting and folder assembly.

**Q: How does chunking and extraction work, and why not send the whole document at once?**
A: A tender can run hundreds of pages, larger than most context windows can handle reliably, and even where it would fit, extraction accuracy suffers when asked to find everything in one huge pass. The pipeline extracts per-page text and tables via PyMuPDF, falling back to Tesseract OCR on pages whose extracted text is suspiciously short (a signature of a scanned image). It then does section-aware chunking: detecting section boundaries by pattern, grouping pages by section, splitting each into roughly 2000-token windows with roughly 200 tokens of overlap, keeping a running token-to-page map so every chunk carries an accurate page range. Overlap matters because a requirement can fall across a chunk boundary; without it, that requirement could be silently lost. Extraction then runs one LLM call per chunk, bounded by a concurrency limit so 150-plus chunks run several at a time rather than sequentially or all at once against a rate limit. Requirements from overlapping chunks are deduplicated by hashing clause reference plus description.

**Q: How is Cancel or Retry mid-pipeline handled safely if a worker might already be running?**
A: Via a monotonically increasing `run_generation` counter on the `Tender` row. Every write the pipeline makes is an atomic conditional update: `UPDATE tenders SET ... WHERE id = :id AND run_generation = :expected_generation`, never a separate read then write. Cancel or Reprocess immediately bumps `run_generation`. The next time the running worker tries to write progress, its captured `expected_generation` no longer matches, the update affects zero rows, and the code treats that as "superseded" and stops cleanly without needing to be told why. `expected_generation` is captured once at enqueue time, not re-read when the task starts, because a task can sit queued behind other work, and a fresh re-read at start time could wrongly claim ownership of a newer generation bumped during that wait, causing two tasks to race as if they were the same run. Cancel also issues a hard Celery `revoke(terminate=True)` using the stored `celery_task_id`, so the generation guard and the hard revoke work together.

**Q: What does the failure path look like, separate from cancellation?**
A: A dedicated `_fail` path gated by the same `run_generation` check, because `TenderCancelled` just means someone acted, and if that action was Stop immediately followed by Retry, a new worker may already be running by the time the old worker's exception handler catches up; writing `FAILED` unconditionally would clobber the new run's live status. `_fail` also calls `db.rollback()` before reading the tender's status, so the failing stage's half-committed work is discarded first, making the recorded `failed_stage` describe the last stage that actually completed rather than a half-applied leftover.

**Q: What does the reviewable output actually contain?**
A: A four-sheet Excel workbook (Requirements, Summary, Evidence Matches, Instructions) plus a zip with the original tender PDF and a "Required Documents" subfolder of the actual evidence files for every covered requirement. The Requirements sheet reproduces the tender's own wording verbatim wherever it doesn't fit a clean enum, normalized values exist only for sorting and coverage math. "Coverage" is computed consistently: a match counts only if a human accepted it, or it auto-matched above 0.85 and hasn't since been rejected. A narrative clause the tender never asked to be proven (`evidence_required` false) is excluded from "missing evidence" rather than mislabeled. The folder is rebuilt from scratch on every finalize, so a rejected match never leaves a stale file behind.

**Q: Can a run fail with zero requirements, and how does that differ from finding nothing legitimately?**
A: Zero requirements is treated as a hard failure, not a valid empty result, because a run showing 40 of 400 real requirements as "finished," with nothing telling the user, is worse than one that fails loudly and points at what to check. Without this check a run could reach `ready_for_review` with an empty tracker presented as success, which was an actual observed bug, distinct from genuinely finding no usable text (a scanned page with no text layer).

---

## 6. The Evidence Library and RAG Pipeline End to End

**Q: Walk through upload to searchable.**
A: Upload and training are separate. Uploading only validates the file, computes a SHA-256 hash, checks for exact or near duplicates, and stores it with a `Document` row in `QUEUED` state, nothing is parsed or embedded yet, so no CPU is spent before a duplicate check might reject it. A separate Train call enqueues indexing, either for specific ids or everything queued; already-indexed documents are skipped unless forced, which is what makes retraining incremental. Indexing is one Celery task per document (so training one new asset never touches the rest of the library) walking Parsing, Tagging (filling metadata the uploader left blank, keyword heuristics first, cheap LLM tier as last resort), and Embedding (chunking and embedding in batches so progress reports incrementally on a large document).

**Q: How does parsing differ by document type?**
A: Case studies resolve into six canonical sections (Client, Sector, Scope, Challenge, Solution, Results) via a heading-synonym table, falling back to an LLM section map if fewer than three sections are found, and to one undifferentiated blob only as a last resort. Company documents (certificates, filings) are deliberately not split into sections at all, since fragmenting a short certificate would divorce "Scope of certification" from the certificate number that gives it meaning; instead the parser classifies type by weighted keywords and extracts identifiers (certificate number, dates) onto the document row. Methodology documents split by phase markers ("Phase 2," numbered headings), since that content is sequential and a phase label tells a reader where a retrieved passage belongs, something a bare similarity score can't convey.

**Q: How does search work, and what does "grounded" mean for Ask?**
A: Search runs cosine-distance queries directly against Postgres via pgvector's `<=>` operator, no in-memory index or cache, so a document indexed a moment ago is immediately searchable. Ask builds on retrieval with a strict rule: the model only sees retrieved chunks, is instructed to answer using only those, and must produce an exact sentinel string when the context doesn't answer the question. Chunks are numbered in the prompt, and the answer is parsed afterward for those citation numbers; an uncited retrieved chunk is still returned, since knowing what was considered but unused is itself useful. `grounded` is true only when the answer cites at least one source and doesn't decline, so confident prose with nothing cited is correctly reported as ungrounded.

**Q: What happens if the library has nothing relevant, or no API key is configured?**
A: If retrieved passages don't answer the question, the model declines and the response comes back `grounded: false`, with the retrieved passages still shown rather than hidden, since honestly showing the closest evidence is more useful than showing nothing. With no API key, `complete()` in the LLM wrapper returns an empty string on failure rather than raising, and every call site tolerates that and falls back to heuristics, so the whole library pipeline still runs end to end without machine-assisted tagging or generated answers. The frontend's "Find" mode skips generation entirely and returns ranked passages directly, working with zero LLM configuration.

**Q: How does the same library serve both tender matching and Ask?**
A: Both read the exact same `Chunk` table and embeddings through the same search module; tender evidence matching calls the same seam the `/search` REST endpoint calls. An answer through Ask and a match surfaced during tender review are always grounded in the same documents, with no separate, potentially drifting copy of "what evidence exists."

---

## 7. Database Design

**Q: Why Alembic migrations instead of auto-creating tables?**
A: Auto-creation works for a throwaway prototype but breaks the moment more than one environment needs the same schema, and leaves no record of why a change happened. Alembic keeps a versioned history (`upgrade()`/`downgrade()` per migration) plus a table recording what's applied. A manual `ALTER TABLE` instead means no other environment picks it up, no record of why, and Alembic's bookkeeping now disagrees with reality, which can break the next real migration or silently do the wrong thing. This project hit the concrete failure mode migrations prevent: several `Requirement` fields (`responsibility`, `dpl`, `prime`, others) were added to the model but a migration was initially missed, and every tender run failed with `UndefinedColumn` until it was added.

**Q: Why is the embedding column vector(768), and why does that matter operationally?**
A: 768 is the output width of the embedding model in use (`BAAI/bge-base-en-v1.5`). It isn't a free parameter later, two vector columns are already committed to it; switching models to a different width means a real column migration and re-embedding every previously-indexed chunk, not just relabeling. The embedding provider checks at runtime that returned vectors actually match `EMBEDDING_DIM` and raises immediately with an actionable message, rather than letting a mismatch surface later as an opaque pgvector insert failure inside a Celery task.

**Q: What is the "tombstone" pattern, and why does it matter here?**
A: This backend merged two earlier prototypes, a flat one with no real auth or database, and a fuller tender-analysis system. Where both had a same-named module and only one is live, the losing file wasn't deleted, its body was replaced with a docstring explaining the situation and a `raise ImportError(...)` naming the live replacement. Quietly deleting relies on nobody importing it from memory or an old branch; leaving it unused but importable is actively dangerous, since a stray import could silently run old, incompatible code built against a no-op auth stub. A tombstone fails loudly at the exact line instead of failing mysteriously elsewhere or not failing at all. It shows up at real scale here: `app/config.py`, `app/db.py`, `app/api/library.py`, `app/api/ws.py`, several `app/services/` modules, and a whole tombstoned parser package all follow it.

**Q: Is there audit logging, and what does it capture?**
A: A deliberately generic `AuditLog` table (`action`, `resource_type`, `resource_id`, a free-form JSON `details` blob) covers logins, tender runs, document training and user-management actions without a table per action type. `user_id` is nullable, since some events (a failed login against an unknown email, a system-level error) have no authenticated user to attach to.

**Q: Why does Requirement have both normalized and raw verbatim fields?**
A: Real tenders write compound or non-boolean values a clean enum can't represent ("No/Advisory," "Financial / Pass-Fail"). Storing only a normalized value would force the tracker to either drop the tender's actual wording or approximate it, and the tracker's job is to reproduce the client's own wording exactly. So the model keeps both: a normalized column for sorting, filtering and coverage math, and a `_raw` column with the tender's exact text, with output assembly always using the raw fields where they exist.

---

## 8. Frontend Architecture

**Q: Explain the routing and layout nesting.**
A: Classic React Router `<Routes>`/`<Route>` (not the data-router loaders/actions API). Layout routes render a shared shell with an `<Outlet />`: `DashboardLayout` is the outermost authenticated shell (sidebar, header, footer); inside it, `DocumentsLayout` and `TenderAnalysisLayout` each render their own tab bar with a nested outlet; the page component renders inside that. The sidebar and tab bar are written once each, and switching tabs doesn't remount the outer shell. One deliberate exception: a tender or document's detail/review page is not nested as a fourth tab, it sits as a sibling route directly under `DashboardLayout`, to avoid implying you can tab away from a review screen and back, when the real model is "open one item, then go back to the list."

**Q: How is state managed, local versus store versus server data?**
A: Component-private state stays in `useState`; state genuinely shared across the tree, or that must survive a navigation without refetching, goes into a Zustand store. There are exactly two: `authStore` (user, both tokens, bootstrap/submission state) and `themeStore` (light/dark/system preference). Everything else that looks like data is server state, loaded via `useAsyncData` (or `useJobProgress`/`useTenderProgress` for WebSocket progress), which tracks loading, error and refresh itself and stays with the page that requested it rather than living globally.

**Q: Why a thin API client wrapper instead of calling fetch() from components?**
A: `apiClient.ts` is the only file that calls `fetch()` directly; it attaches the current access token, retries once on 401 using a single-flight pattern (several near-simultaneous 401s trigger only one refresh, the rest await it), and unwraps FastAPI's several error-body shapes into one message. A service layer (`authService.ts`, `documentService.ts`, `tenderService.ts`) sits on top knowing endpoint paths and shapes but nothing about how a fetch happens; components only call service functions. Changing how a request is made never touches a page component; changing an endpoint never touches the low-level fetch logic.

**Q: How are the two progress WebSockets consumed on the frontend?**
A: Two hooks, `useJobProgress` (library indexing) and `useTenderProgress` (tender pipeline), sharing a state machine (`idle`, `live`, `polling`, `offline`, `closed`) rather than a boolean. Each first mints a ticket over HTTP, then opens the socket with that ticket instead of the real token. Three consecutive connection failures fall back to polling the REST endpoint every couple of seconds, so a corporate proxy blocking WebSocket upgrades doesn't leave the UI stuck. `useTenderProgress` treats `ready_for_review` as not socket-terminal, since the connection needs to stay open through human review; only `finalized`/`failed` close it. Both null out the socket's handlers before calling `.close()`, since closing fires `onclose`, and without nulling first, that teardown event would itself try to start polling right as the component unmounts.

**Q: How does the frontend display private, authenticated files like a tender PDF?**
A: Nothing lets a plain `<img src>` or `<a href>` attach an Authorization header. The consistent pattern: fetch the resource as a blob through the authenticated client, convert it via `URL.createObjectURL()`, hand that object URL to the `<img>`, `<a>`, or `react-pdf`, and call `URL.revokeObjectURL()` when done. Used for a tender's source PDF and generated output, and a library document's original file and extracted page images.

---

## 9. Testing, Reliability, and Failure Modes

**Q: What happens if a Celery worker crashes mid-job?**
A: `task_acks_late=True` means a task is only marked complete after it finishes, so a crash mid-task doesn't lose the message, it can be redelivered. `worker_prefetch_multiplier=1` stops one worker from hoarding several jobs while a sibling sits idle, which matters for this heavy-per-task workload. On the database side, `run_generation` fencing means even overlapping or re-run tasks for the same tender just become no-ops if superseded, rather than corrupting the row. What's not automatic is a mid-failure full retry: library indexing is registered with `max_retries=0`, since a parse failure is almost always a bad file rather than transient, so an automatic retry would just re-run expensive OCR pointlessly; failures are recorded for a human to explicitly re-trigger.

**Q: What happens if the LLM call fails after retries?**
A: In tender extraction, each chunk retries individually, and the pipeline tracks failure rate overall: over 30 percent of chunks failing, or zero requirements extracted, raises a hard `ExtractionFailed` rather than continuing incomplete. Three dedicated failure columns (`failed_stage`, `error_detail`, `failed_at`) exist because `progress_message` gets overwritten by every later stage, so without them there'd be no record of which stage actually died. In the library, the LLM wrapper is tolerant by design: `complete()` returns empty string on failure instead of raising, and every call site falls back to heuristics or an honest "no answer," which is why the library pipeline still functions with no API key configured.

**Q: What does the health check endpoint verify, and why does it matter operationally?**
A: `GET /health` runs a real `SELECT 1` against Postgres, so a liveness probe proves the database is reachable, not just that the process is alive. `GET /api/health/llm` round-trips a trivial prompt through the exact same Anthropic client configuration real extraction uses. Without it, an operator whose extraction is failing has to guess between a bad key, a retired model name, a network block, or a spent quota, usually by re-running a whole tender and reading worker logs; this answers it in seconds. It always returns HTTP 200, distinguishing "the probe ran, here's what it found" from "the probe itself crashed," so a caller checks one field in one response shape.

**Q: What test coverage exists, and what is honestly missing?**
A: Backend unit tests cover storage path-safety, both chunkers, both parsers, metadata precedence, duplicate detection, and RAG failure modes, all without a live database. Missing: any test of the HTTP/auth layer, the Celery pipeline end to end, or true integration tests, all of which need a live Postgres with pgvector that the current suite avoids. Frontend testing got a Vitest setup later with one model-layer test file; before that there was no frontend test framework at all. There's also no load/performance testing and no dedicated security pass beyond fixes from one external code review.

---

## 10. Tradeoffs and Honest Limitations

**Q: What are the real limitations, honestly?**

1. **No per-user access control on tenders or documents.** Deliberate for a small shared team tool, but a real IDOR-shaped gap the moment this needs to serve more than one organization. Identified in review and consciously kept, a legitimate but load-bearing tradeoff.

2. **Refresh tokens aren't rotated or revocable.** A valid refresh token mints new access tokens for its full lifetime; there's no server-side blocklist to invalidate one early (a stolen laptop, say). Production handling more sensitive data would want rotation and revocation.

3. **A fully-built support-email feature is dead code.** `services/support_email.py` composes and sends a failure's full detail over SMTP, well-documented and ready, but nothing live calls it; the real "contact support" flow is a frontend `mailto:` link, with the backend only recording that the hand-off happened. A concrete lesson that a confident module isn't proof it's wired into anything.

4. **Some dead code was never tombstoned.** Most leftover prototype code is deliberately tombstoned, but `app/core/ws_manager.py` is genuinely dead, never converted, just quietly unreferenced after progress broadcasting moved to Redis Pub/Sub. A smaller version of the risk tombstoning exists to prevent.

5. **Duplicated, drifting stage labels.** `pipeline_stages.py` and `progress.py` both define near-identical stage labels with slightly different text, and only `progress.py`'s copy reaches the client. Known and deliberately unfixed, since consolidating them would change strings the frontend may depend on.

6. **Local CPU-only embeddings are a real throughput ceiling.** Avoids a second external dependency, but computation scales with the worker's own CPU, not a hosted service's throughput. A much larger library or upload volume would hit this ceiling.

7. **Real concurrency and integration test gaps.** The most concurrency-sensitive code, `run_generation` fencing, WebSocket ticket redemption, the Celery pipeline end to end, has no automated coverage; what exists is unit-level coverage of parsers, chunkers, and pure logic. A genuine risk area, not just a nice-to-have.

**Q: If forced to fix one before a second customer, which and why?**
A: Per-user access control, without much hesitation. It's the one limitation that isn't a missing nicety but an actual absent security boundary, and it becomes dangerous the moment this serves more than one company's tenders and evidence in one deployment, since right now any signed-in user, from any company sharing that deployment, can see and modify any other's data. The others are quality and maintainability issues, not a data-isolation failure.

---

## 11. Future Work: "If You Had More Time"

**Q: What would you build next with another month?**

1. **Real per-tenant or per-team access control**, extending `uploaded_by` attribution into an actual authorization check scoped by organization or team, preserving the shared-workspace model while letting the platform serve more than one company.

2. **Rotating refresh tokens with server-side revocation**, storing issued tokens (or their jti) server-side, invalidating the old one on reissue, and adding a "log out this device" or "revoke all sessions" action.

3. **A real integration suite against live Postgres with pgvector**, covering the HTTP/auth layer and specifically the concurrency-sensitive paths (`run_generation` fencing under simulated Cancel/Retry races, WebSocket ticket redemption), the areas most likely to hide a subtle bug unit tests on pure functions can't catch.

4. **Wire up or remove the orphaned support-email feature**, either actually calling `send_failure_report` from the failure path so an operator gets a real traceback automatically, or removing the module so a future reader isn't misled by a well-documented function that never runs.

5. **A real activity feed and dashboard-stats endpoint**, since several pages currently compose their view client-side from `listTenders`/`listDocuments` calls; a backend-driven log reusing the existing `AuditLog` table would be more efficient and accurate.

6. **Load and performance testing around embedding throughput**, deliberately measuring behavior under a realistically large library and concurrent uploads, to know the scaling ceiling ahead of time rather than discovering it in production.

---

## 12. Rapid-Fire Reference

- **What ORM is used?** SQLAlchemy 2, in async mode.
- **What manages schema changes?** Alembic migrations, never auto-created tables.
- **What runs background jobs?** Celery, with Redis as broker and result backend.
- **What are Redis's three jobs here?** Celery broker, progress cache (Pub/Sub plus a snapshot key), and short-lived single-use token storage.
- **How is a long-lived token kept out of the WebSocket URL?** A short-lived, single-use ticket minted over an authenticated HTTP call, passed in the URL instead of the real access token.
- **Why GETDEL for ticket redemption?** Reads and deletes the key atomically, closing the race window a separate GET-then-DELETE would leave for a retried or double-fired connection attempt.
- **What model handles high-volume extraction calls?** A cheaper, faster Claude model (Haiku tier), via `ANTHROPIC_EXTRACTION_MODEL`.
- **What model handles the grounded Ask feature?** A stronger Claude model (Sonnet tier), via `ANTHROPIC_MODEL`.
- **What library provides embeddings, and where does it run?** `fastembed`, locally and CPU-only inside the Celery worker, no external API call.
- **What's the embedding dimension, and why can't it just change?** 768; two `vector(768)` pgvector columns are already committed to it, so changing it means a migration plus re-embedding everything.
- **What vector search operator is used?** Cosine distance, via pgvector's `<=>` operator.
- **What are the three match confidence tiers?** Auto-matched at 0.85 or above, suggested between 0.60 and 0.84, otherwise missing.
- **What prevents a stale worker from corrupting a cancelled or retried run?** `run_generation`, checked atomically in every progress write's WHERE clause.
- **How many failed logins trigger a lockout, by default?** Five.
- **What does login return for a wrong password versus an unknown email?** The identical generic error message, to prevent email enumeration.
- **Is there per-user ownership on tenders and documents?** No, deliberately; it's a shared team workspace, not multi-tenant.
- **What frontend routing style is used?** Classic React Router `<Routes>`/`<Route>` with nested layouts, not the data-router loaders/actions API.
- **What state library is used, and for what?** Zustand, for the auth store and theme store only; everything else is local or server state via hooks.
- **What's the one file allowed to call fetch() directly?** `src/lib/apiClient.ts`.
- **How does the frontend show a private, authenticated PDF or image?** Fetch as a blob through the authenticated client, turn it into an object URL, revoke it when done.
- **What was the plan's original frontend framework versus what was built?** Next.js was specified; the actual build is Vite plus React 19 with classic React Router, a documented and reviewed deviation.
- **What does GET /health check?** A real SELECT 1 against Postgres, not just that the process is alive.
- **What does GET /api/health/llm check?** A live round trip through the exact Anthropic client configuration real extraction uses.
- **What happens if extraction yields zero requirements?** The run is raised as a hard failure, not presented as an empty success.
- **Is the support-email SMTP feature actually used?** No, fully implemented but never called; the real support flow is a frontend `mailto:` link.
