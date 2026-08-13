/* Evidence Library test UI (WBS Section 6).
 *
 * No framework and no build step on purpose: this harness exists to demonstrate
 * the Section 6 backend, and Section 8 builds the production Next.js frontend.
 * Editing a file here means refreshing the browser, nothing more.
 *
 * Five views behind hash routes. Splitting them matters beyond tidiness — the
 * document list, the training queue and the search results each want the full
 * width of the page, and stacking them forced every one of them to be small.
 */

const API = "/api/library";

// LIB-UI-05 — the fixed stage sequence, in order.
const STAGES = [
    { value: "parsing",   label: "Parsing" },
    { value: "tagging",   label: "Tagging" },
    { value: "embedding", label: "Embedding" },
    { value: "complete",  label: "Complete" },
];

const CATEGORY_LABELS = {
    case_study: "Case Study",
    methodology: "Methodology",
    company_document: "Company Document",
};

// Retrieval knobs. `/search` returns chunks because that is the unit an
// embedding covers, but a reader wants the document — so over-fetch passages,
// group them, and cap the number of *documents* shown. At limit=10 a single
// strong case study can own every row and push the rest off the page entirely.
const MIN_SIMILARITY = 0.5;
const CHUNK_LIMIT = 40;
const DOCUMENT_LIMIT = 8;
const PASSAGES_SHOWN = 3;

const EXAMPLE_QUESTIONS = [
    "What did DPL build for iApartments?",
    "Which projects involved IoT hardware?",
    "How do farmers pay for solar pumps?",
];

const state = {
    view: "overview",
    docCategory: "case_study",
    uploadCategory: "case_study",
    searchCategory: "",
    pending: [],      // uploaded, not yet trained
    sockets: new Map(),
    stats: null,
};

const $ = (id) => document.getElementById(id);

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function escapeHtml(value) {
    const div = document.createElement("div");
    div.textContent = value == null ? "" : String(value);
    return div.innerHTML;
}

const pct = (value) => `${(value * 100).toFixed(1)}%`;
const label = (category) => CATEGORY_LABELS[category] || category;

function formatSize(bytes) {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
    return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function toast(message, kind = "") {
    const el = document.createElement("div");
    el.className = `toast ${kind}`;
    el.textContent = message;
    $("toast-stack").appendChild(el);
    setTimeout(() => el.remove(), 5000);
}

function loading(text) {
    return `<div class="loading"><span class="spinner"></span>${escapeHtml(text)}</div>`;
}

function empty(title, detail) {
    return `<div class="empty"><strong>${escapeHtml(title)}</strong>${escapeHtml(detail || "")}</div>`;
}

async function api(path, options = {}) {
    const response = await fetch(`${API}${path}`, options);
    if (!response.ok) {
        let detail = `${response.status} ${response.statusText}`;
        try {
            const body = await response.json();
            if (typeof body.detail === "string") detail = body.detail;
            else if (body.detail && body.detail.message) detail = body.detail.message;
        } catch (_) { /* non-JSON error body */ }
        throw new Error(detail);
    }
    return response.status === 204 ? null : response.json();
}

/* Wire a segmented control. Returns nothing; the callback owns the reaction. */
function segmented(containerId, onChange) {
    const container = $(containerId);
    if (!container) return;
    container.querySelectorAll("button").forEach((button) => {
        button.addEventListener("click", () => {
            container.querySelectorAll("button").forEach((b) => b.classList.remove("active"));
            button.classList.add("active");
            onChange(button.dataset.category);
        });
    });
}

// ---------------------------------------------------------------------------
// Routing
// ---------------------------------------------------------------------------

const VIEWS = ["overview", "documents", "upload", "search", "ask"];

function route() {
    const name = (location.hash.replace("#/", "") || "overview").split("?")[0];
    const view = VIEWS.includes(name) ? name : "overview";
    state.view = view;

    VIEWS.forEach((v) => $(`view-${v}`).classList.toggle("hidden", v !== view));
    document.querySelectorAll(".nav-item").forEach((item) => {
        item.classList.toggle("active", item.dataset.view === view);
    });
    window.scrollTo(0, 0);

    // Load on entry rather than up front: the overview is the only view that is
    // guaranteed to be seen, and a search page has nothing to show until asked.
    if (view === "overview") loadOverview();
    if (view === "documents") loadDocuments();
}

window.addEventListener("hashchange", route);

// ---------------------------------------------------------------------------
// Overview
// ---------------------------------------------------------------------------

async function loadStats() {
    try {
        const stats = await api("/stats");
        state.stats = stats;

        const total = Object.values(stats.categories).reduce((sum, c) => sum + c.total, 0);
        $("nav-doc-count").textContent = total || "";

        document.querySelectorAll("[data-count]").forEach((el) => {
            const counts = stats.categories[el.dataset.count];
            el.textContent = counts && counts.total ? counts.total : "";
        });

        return stats;
    } catch (_) {
        return null;
    }
}

async function loadOverview() {
    const stats = await loadStats();
    if (!stats) {
        $("stat-grid").innerHTML = empty("Backend unreachable", "Is the stack running? docker compose up -d");
        return;
    }

    const categories = Object.entries(stats.categories);
    const total = categories.reduce((sum, [, c]) => sum + c.total, 0);
    const indexed = categories.reduce((sum, [, c]) => sum + c.indexed, 0);
    const failed = categories.reduce((sum, [, c]) => sum + c.failed, 0);
    const inFlight = categories.reduce(
        (sum, [, c]) => sum + c.queued + c.parsing + c.tagging + c.embedding, 0
    );

    $("stat-grid").innerHTML = `
        <div class="stat">
            <div class="stat-label">Documents</div>
            <div class="stat-value">${total}</div>
            <div class="stat-note">across three categories</div>
        </div>
        <div class="stat">
            <div class="stat-label">Indexed</div>
            <div class="stat-value">${indexed}</div>
            <div class="stat-note">${inFlight ? `${inFlight} in progress` : "searchable now"}</div>
        </div>
        <div class="stat">
            <div class="stat-label">Chunks</div>
            <div class="stat-value">${stats.chunk_count}</div>
            <div class="stat-note">embedded passages</div>
        </div>
        <div class="stat">
            <div class="stat-label">Failed</div>
            <div class="stat-value">${failed}</div>
            <div class="stat-note">${failed ? "see Documents" : "none"}</div>
        </div>
    `;

    // A stacked bar per category reads faster than four numbers in a row: the
    // question here is "is anything stuck", and that is a shape, not a count.
    $("category-breakdown").innerHTML = categories.map(([name, counts]) => {
        const rows = [
            { key: "indexed", cls: "pill-indexed", n: counts.indexed },
            { key: "queued", cls: "pill-queued", n: counts.queued },
            { key: "parsing", cls: "pill-parsing", n: counts.parsing + counts.tagging + counts.embedding },
            { key: "failed", cls: "pill-failed", n: counts.failed },
        ].filter((r) => r.n > 0);

        return `
            <div style="padding:11px 0;border-bottom:1px solid var(--border)">
                <div style="display:flex;justify-content:space-between;align-items:center;gap:12px">
                    <span style="font-weight:500">${escapeHtml(label(name))}</span>
                    <span style="color:var(--text-dim);font-size:13px">${counts.total} document${counts.total === 1 ? "" : "s"}</span>
                </div>
                ${rows.length
                    ? `<div class="tags" style="margin-top:7px">${rows.map((r) =>
                        `<span class="pill ${r.cls}">${r.n} ${r.key === "parsing" ? "in progress" : r.key}</span>`).join("")}</div>`
                    : `<div style="font-size:12.5px;color:var(--text-faint);margin-top:4px">Nothing uploaded yet</div>`}
            </div>
        `;
    }).join("");

    $("system-info").innerHTML = `
        <dt>Embedding model</dt><dd>${escapeHtml(stats.embedding_model)}</dd>
        <dt>Dimensions</dt><dd>${stats.embedding_dim} <span style="color:var(--text-faint)">· matches WBS 1.1.3</span></dd>
        <dt>Answer generation</dt><dd>${stats.llm_available
            ? `<span style="color:var(--success)">Available</span>`
            : `<span style="color:var(--warning)">Off — retrieval still works</span>`}</dd>
        <dt>Retrieval threshold</dt><dd>${pct(MIN_SIMILARITY)} minimum similarity</dd>
    `;
}

async function loadHealth() {
    try {
        const response = await fetch("/health");
        const health = await response.json();
        const ok = health.status === "ok";
        $("health-dot").className = `dot ${ok ? "ok" : "down"}`;
        $("health-text").textContent = ok ? "All systems normal" : "Degraded";
        $("health-detail").textContent = `${health.embedding_dim}-dim · LLM ${health.llm_available ? "on" : "off"}`;
    } catch (_) {
        $("health-dot").className = "dot down";
        $("health-text").textContent = "Backend unreachable";
        $("health-detail").textContent = "";
    }
}

// ---------------------------------------------------------------------------
// Documents
// ---------------------------------------------------------------------------

segmented("doc-categories", (category) => {
    state.docCategory = category;
    loadDocuments();
});

$("refresh-docs").addEventListener("click", () => { loadDocuments(); loadStats(); });

async function loadDocuments() {
    const container = $("doc-list");
    container.innerHTML = loading("Loading documents…");

    try {
        const documents = await api(`/documents?category=${state.docCategory}&limit=100`);
        loadStats();

        if (!documents.length) {
            container.innerHTML = empty(
                "No documents in this category",
                "Upload one from Upload & Train to get started."
            );
            return;
        }

        container.innerHTML = documents.map(renderDocument).join("");
        container.querySelectorAll("[data-retrain]").forEach((b) =>
            b.addEventListener("click", () => retrain(b.dataset.retrain)));
        container.querySelectorAll("[data-delete]").forEach((b) =>
            b.addEventListener("click", () => remove(b.dataset.delete)));
    } catch (error) {
        container.innerHTML = empty("Could not load documents", error.message);
    }
}

function renderDocument(doc) {
    const auto = new Set(doc.auto_tagged_fields || []);
    const tag = (field, value) => {
        if (!value) return "";
        const marker = auto.has(field) ? `<span class="auto">auto</span>` : "";
        return `<span class="tag">${escapeHtml(value)}${marker}</span>`;
    };

    const tags = [
        tag("client", doc.client),
        tag("sector", doc.sector),
        tag("service_line", doc.service_line),
        tag("geography", doc.geography),
        tag("doc_type", doc.doc_type),
    ].filter(Boolean);

    const meta = [
        escapeHtml(doc.original_filename),
        doc.training_status === "indexed" ? `${doc.chunk_count} chunks · ${doc.page_count} pages` : "",
        new Date(doc.created_at).toLocaleDateString(),
    ].filter(Boolean).join(" · ");

    return `
        <div class="doc">
            <div class="doc-head">
                <div style="flex:1;min-width:0">
                    <div class="doc-title">${escapeHtml(doc.title || doc.original_filename)}</div>
                    <div class="doc-meta">${meta}</div>
                </div>
                <span class="pill pill-${doc.training_status}">${escapeHtml(doc.training_status)}</span>
            </div>
            ${tags.length ? `<div class="tags">${tags.join("")}</div>` : ""}
            ${doc.keywords && doc.keywords.length
                ? `<div class="doc-meta">Keywords: ${escapeHtml(doc.keywords.join(", "))}</div>` : ""}
            ${doc.training_error
                ? `<div class="banner banner-danger" style="margin-top:10px">${escapeHtml(doc.training_error)}</div>` : ""}
            <div class="doc-actions">
                <button class="btn btn-secondary btn-sm" data-retrain="${doc.id}">Re-index</button>
                <button class="btn btn-secondary btn-sm btn-danger" data-delete="${doc.id}">Delete</button>
            </div>
        </div>
    `;
}

async function retrain(documentId) {
    try {
        const job = await api(`/documents/${documentId}/retrain`, { method: "POST" });
        location.hash = "#/upload";
        $("progress-section").classList.remove("hidden");
        startTracking(job);
        toast("Re-indexing started");
    } catch (error) {
        toast(error.message, "error");
    }
}

async function remove(documentId) {
    if (!confirm("Delete this document and all of its chunks?")) return;
    try {
        await api(`/documents/${documentId}`, { method: "DELETE" });
        toast("Deleted", "success");
        loadDocuments();
    } catch (error) {
        toast(error.message, "error");
    }
}

// ---------------------------------------------------------------------------
// Upload (LIB-UI-01, 02, 03, 06)
// ---------------------------------------------------------------------------

segmented("upload-categories", (category) => { state.uploadCategory = category; });

const dropzone = $("dropzone");
const fileInput = $("file-input");

dropzone.addEventListener("click", () => fileInput.click());

["dragenter", "dragover"].forEach((event) =>
    dropzone.addEventListener(event, (e) => { e.preventDefault(); dropzone.classList.add("dragover"); }));
["dragleave", "drop"].forEach((event) =>
    dropzone.addEventListener(event, (e) => { e.preventDefault(); dropzone.classList.remove("dragover"); }));

dropzone.addEventListener("drop", (e) => handleFiles(e.dataTransfer.files));
fileInput.addEventListener("change", (e) => {
    handleFiles(e.target.files);
    // Reset so re-selecting the same file still fires a change event.
    e.target.value = "";
});

async function handleFiles(fileList) {
    const files = Array.from(fileList || []);
    if (!files.length) return;

    $("metadata-section").classList.remove("hidden");
    $("queue-section").classList.remove("hidden");

    for (const file of files) await uploadFile(file);

    renderQueue();
    loadStats();
}

async function uploadFile(file) {
    const form = new FormData();
    form.append("file", file);
    form.append("title", $("meta-title").value);
    form.append("client", $("meta-client").value);
    form.append("sector", $("meta-sector").value);
    form.append("service_line", $("meta-service").value);
    form.append("geography", $("meta-geography").value);
    form.append("keywords", $("meta-keywords").value);

    try {
        const result = await api(`/${state.uploadCategory}/upload`, { method: "POST", body: form });
        state.pending.push({ ...result.document, size: file.size });

        // LIB-UI-06 — a semantic near-match is advisory, so the upload stands
        // and the user decides whether to train it.
        if (result.duplicate_warning && result.duplicate_warning.near_matches.length) {
            showDuplicateWarning(file.name, result.duplicate_warning.near_matches);
        } else {
            toast(`Uploaded ${file.name}`, "success");
        }
    } catch (error) {
        // An exact hash match comes back 409 and is a hard block.
        toast(`${file.name}: ${error.message}`, "error");
    }
}

function showDuplicateWarning(filename, matches) {
    const summary = matches
        .map((m) => `${escapeHtml(m.title || m.original_filename)} (${pct(m.similarity)} similar)`)
        .join(", ");
    $("duplicate-message").innerHTML =
        `<strong>${escapeHtml(filename)}</strong> closely resembles ${summary}. Training it anyway indexes both copies.`;
    $("duplicate-warning").classList.remove("hidden");
}

$("dismiss-warning").addEventListener("click", () => $("duplicate-warning").classList.add("hidden"));

function renderQueue() {
    $("upload-queue").innerHTML = state.pending.length
        ? state.pending.map((doc) => `
            <div class="queue-item">
                <span class="pill pill-queued">queued</span>
                <span class="queue-name">${escapeHtml(doc.original_filename)}</span>
                <span class="queue-size">${doc.size ? formatSize(doc.size) : ""}</span>
            </div>`).join("")
        : `<div style="color:var(--text-dim);font-size:13px">Nothing queued.</div>`;

    $("train-btn").disabled = !state.pending.length;
}

$("train-btn").addEventListener("click", async () => {
    const ids = state.pending.map((d) => d.id);
    $("train-btn").disabled = true;

    try {
        const result = await api("/train", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ document_ids: ids }),
        });

        if (!result.jobs.length) {
            toast("Nothing to train — all selected documents are already indexed.");
            $("train-btn").disabled = false;
            return;
        }

        $("progress-section").classList.remove("hidden");
        $("job-list").innerHTML = "";
        result.jobs.forEach(startTracking);

        state.pending = [];
        renderQueue();

        if (result.skipped.length) toast(`${result.skipped.length} already-indexed document(s) skipped.`);
    } catch (error) {
        toast(error.message, "error");
        $("train-btn").disabled = false;
    }
});

$("clear-btn").addEventListener("click", () => {
    state.pending = [];
    renderQueue();
    $("metadata-section").classList.add("hidden");
    $("queue-section").classList.add("hidden");
    $("duplicate-warning").classList.add("hidden");
    ["meta-title", "meta-client", "meta-sector", "meta-service", "meta-geography", "meta-keywords"]
        .forEach((id) => { $(id).value = ""; });
});

// ---------------------------------------------------------------------------
// LIB-UI-05 — live progress over WebSocket, polling as the fallback
// ---------------------------------------------------------------------------

function startTracking(job) {
    renderJob(job.id, {
        stage: job.stage,
        label: "Queued",
        progress: 0,
        message: job.message || "Waiting for a worker",
    });

    const protocol = location.protocol === "https:" ? "wss:" : "ws:";
    const socket = new WebSocket(`${protocol}//${location.host}/ws/library/${job.id}`);
    state.sockets.set(job.id, socket);

    socket.onmessage = (event) => {
        const data = JSON.parse(event.data);
        if (data.type === "ping") return;
        if (data.error) {
            renderJob(job.id, { stage: "failed", label: "Failed", progress: 0, message: data.error });
            return;
        }

        renderJob(job.id, data);

        if (data.stage === "complete" || data.stage === "failed") {
            socket.close();
            state.sockets.delete(job.id);
            loadStats();
            if (state.view === "documents") loadDocuments();
        }
    };

    socket.onerror = () => pollJob(job.id);
    socket.onclose = () => state.sockets.delete(job.id);
}

async function pollJob(jobId) {
    try {
        const job = await api(`/jobs/${jobId}`);
        renderJob(jobId, { stage: job.stage, label: job.stage, progress: job.progress, message: job.message });
        if (job.stage !== "complete" && job.stage !== "failed") {
            setTimeout(() => pollJob(jobId), 2000);
        } else {
            loadStats();
        }
    } catch (_) { /* job gone; stop polling */ }
}

function renderJob(jobId, data) {
    let el = $(`job-${jobId}`);
    if (!el) {
        el = document.createElement("div");
        el.className = "job";
        el.id = `job-${jobId}`;
        $("job-list").appendChild(el);
    }

    const failed = data.stage === "failed";
    const complete = data.stage === "complete";
    const currentIndex = STAGES.findIndex((s) => s.value === data.stage);

    const track = STAGES.map((stage, index) => {
        let cls = "stage-step";
        if (complete || (currentIndex > -1 && index < currentIndex)) cls += " done";
        else if (index === currentIndex) cls += " active";
        return `<span class="${cls}">${stage.label}</span>`;
    }).join("");

    el.innerHTML = `
        <div class="job-head">
            <span class="job-stage">${escapeHtml(data.label || data.stage)}</span>
            <span class="job-percent">${data.progress}%</span>
        </div>
        <div class="progress-bar">
            <div class="progress-fill ${failed ? "failed" : complete ? "complete" : ""}" style="width:${data.progress}%"></div>
        </div>
        ${data.message ? `<div class="job-message">${escapeHtml(data.message)}</div>` : ""}
        <div class="stage-track">${track}</div>
    `;
}

// ---------------------------------------------------------------------------
// Search (LIB-UI-07)
// ---------------------------------------------------------------------------

segmented("search-categories", (category) => {
    state.searchCategory = category;
    if ($("search-input").value.trim().length >= 2) runSearch();
});

/* Collapse chunk hits into one entry per document.
 *
 * The document's score is its best passage, not the mean: a long case study
 * with one exact match and twenty unrelated sections is a good result, and
 * averaging would bury it under a short document that matches weakly overall.
 */
function groupByDocument(hits) {
    const byDocument = new Map();

    for (const hit of hits) {
        let group = byDocument.get(hit.document_id);
        if (!group) {
            group = {
                id: hit.document_id,
                title: hit.title || hit.original_filename,
                filename: hit.original_filename,
                category: hit.category,
                passages: [],
            };
            byDocument.set(hit.document_id, group);
        }
        group.passages.push(hit);
    }

    // The API already orders by similarity, but sorting here rather than
    // relying on that keeps the score right if the ordering ever changes.
    for (const group of byDocument.values()) {
        group.passages.sort((a, b) => b.similarity - a.similarity);
        group.score = group.passages[0].similarity;
    }

    return [...byDocument.values()].sort((a, b) => b.score - a.score);
}

function renderPassage(hit) {
    const where = [hit.section_name, hit.phase, hit.page_number ? `p.${hit.page_number}` : ""]
        .filter(Boolean).join(" · ") || "Passage";
    const images = (hit.image_paths || []).length
        ? `<div class="passage-images">${hit.image_paths.length} linked image(s)</div>` : "";

    return `
        <div class="passage">
            <div class="passage-head">
                <span>${escapeHtml(where)}</span>
                <span class="passage-score">${pct(hit.similarity)}</span>
            </div>
            <div class="passage-body">${escapeHtml(hit.content.slice(0, 300))}${hit.content.length > 300 ? "…" : ""}</div>
            ${images}
        </div>
    `;
}

function renderDocumentMatch(group) {
    const shown = group.passages.slice(0, PASSAGES_SHOWN);
    const hidden = group.passages.slice(PASSAGES_SHOWN);
    const count = group.passages.length;

    // <details> rather than a click handler: the extra passages are already in
    // the DOM, so there is no state to wire up and nothing to re-render.
    const more = hidden.length
        ? `<details class="passage-more">
               <summary>${hidden.length} more matching passage${hidden.length === 1 ? "" : "s"}</summary>
               ${hidden.map(renderPassage).join("")}
           </details>`
        : "";

    return `
        <div class="hit-doc">
            <div class="hit-doc-head">
                <span class="hit-doc-title">${escapeHtml(group.title)}</span>
                <span class="hit-doc-score">${pct(group.score)}</span>
            </div>
            <div class="hit-doc-meta">
                ${escapeHtml(label(group.category))} · ${escapeHtml(group.filename)} ·
                ${count} matching passage${count === 1 ? "" : "s"}
            </div>
            <div class="meter"><div class="meter-fill" style="width:${(group.score * 100).toFixed(1)}%"></div></div>
            ${shown.map(renderPassage).join("")}
            ${more}
        </div>
    `;
}

async function runSearch() {
    const query = $("search-input").value.trim();
    const container = $("search-results");

    if (query.length < 2) {
        container.innerHTML = empty("Enter at least two characters", "");
        return;
    }

    container.innerHTML = loading("Searching…");

    try {
        const categoryParam = state.searchCategory ? `&category=${state.searchCategory}` : "";
        const result = await api(
            `/search?q=${encodeURIComponent(query)}&limit=${CHUNK_LIMIT}` +
            `&min_similarity=${MIN_SIMILARITY}${categoryParam}`
        );

        if (!result.hits.length) {
            container.innerHTML = empty(
                `Nothing above ${pct(MIN_SIMILARITY)}`,
                "Only indexed documents are searchable. Try broader wording."
            );
            return;
        }

        const groups = groupByDocument(result.hits);
        const visible = groups.slice(0, DOCUMENT_LIMIT);
        const passages = visible.reduce((total, g) => total + g.passages.length, 0);

        container.innerHTML =
            `<div class="result-summary">${visible.length} document${visible.length === 1 ? "" : "s"} · ` +
            `${passages} passage${passages === 1 ? "" : "s"} above ${pct(MIN_SIMILARITY)}` +
            (groups.length > visible.length ? ` · ${groups.length - visible.length} more hidden` : "") +
            `</div>` + visible.map(renderDocumentMatch).join("");
    } catch (error) {
        container.innerHTML = empty("Search failed", error.message);
    }
}

$("search-btn").addEventListener("click", runSearch);
$("search-input").addEventListener("keydown", (e) => { if (e.key === "Enter") runSearch(); });

// ---------------------------------------------------------------------------
// Ask (RAG)
// ---------------------------------------------------------------------------

$("ask-examples").innerHTML = EXAMPLE_QUESTIONS
    .map((q) => `<button class="chip">${escapeHtml(q)}</button>`).join("");

$("ask-examples").querySelectorAll(".chip").forEach((chip) => {
    chip.addEventListener("click", () => {
        $("ask-input").value = chip.textContent;
        runAsk();
    });
});

/* Turn the model's [n] markers into anchors that scroll to the source.
 *
 * Escaped first, then the markers are replaced — doing it the other way round
 * would let the answer text inject markup through the anchors we insert.
 */
function linkCitations(answer) {
    return escapeHtml(answer).replace(/\[(\d+(?:\s*,\s*\d+)*)\]/g, (match, group) =>
        group.split(",")
            .map((n) => `<a class="cite" href="#source-${n.trim()}">${n.trim()}</a>`)
            .join(""));
}

async function runAsk() {
    const question = $("ask-input").value.trim();
    const container = $("ask-result");

    if (question.length < 3) {
        container.innerHTML = empty("Ask a longer question", "At least three characters.");
        return;
    }

    $("ask-btn").disabled = true;
    container.innerHTML = loading("Retrieving passages and generating an answer…");

    try {
        const result = await api("/ask", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ question, limit: 6 }),
        });

        const badge = result.grounded
            ? `<span class="badge badge-grounded">Grounded</span>`
            : `<span class="badge badge-ungrounded">Not grounded</span>`;

        const sources = result.sources.length
            ? `<section style="margin-top:18px">
                   <h2 class="section-title">Sources</h2>
                   <div class="panel">${result.sources.map((s, i) => `
                       <div class="source ${s.cited ? "used" : ""}" id="source-${i + 1}">
                           <div class="source-n">${i + 1}</div>
                           <div class="source-main">
                               <div class="source-title">${escapeHtml(s.title || s.original_filename)}</div>
                               <div class="source-meta">
                                   ${escapeHtml(label(s.category))}
                                   ${s.section_name ? ` · ${escapeHtml(s.section_name)}` : ""}
                                   ${s.page_number ? ` · p.${s.page_number}` : ""}
                                   · ${pct(s.similarity)}
                                   ${s.cited ? ` · <span style="color:var(--accent)">cited</span>` : ""}
                               </div>
                               <div class="source-text">${escapeHtml(s.content.slice(0, 260))}${s.content.length > 260 ? "…" : ""}</div>
                           </div>
                       </div>`).join("")}
                   </div>
               </section>`
            : "";

        container.innerHTML = `
            <section style="margin-top:18px">
                <div class="answer">
                    <div class="answer-head"><h3>Answer</h3>${badge}</div>
                    <div class="answer-body">${linkCitations(result.answer)}</div>
                </div>
            </section>
            ${sources}
            ${!result.grounded && result.sources.length
                ? `<div class="banner banner-info" style="margin-top:10px">
                       The library did not support an answer to this question. The passages above are the
                       closest matches — this refusal is the intended behaviour, not a failure.
                   </div>` : ""}
        `;
    } catch (error) {
        container.innerHTML = empty("Could not answer", error.message);
    } finally {
        $("ask-btn").disabled = false;
    }
}

$("ask-btn").addEventListener("click", runAsk);
$("ask-input").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) runAsk();
});

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------

renderQueue();
route();
loadHealth();
setInterval(loadHealth, 30000);
