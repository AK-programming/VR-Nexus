"""FastAPI entrypoint — the single backend for this project.

There used to be two: a flat Evidence-Library-only app, and the full tender
system with the real database. This is the merged one, and it is the only one
that should ever be run. Everything the frontend calls lives behind it:

    /api/auth/*              register, login, refresh, me
    /api/tenders/*           tender CRUD and the analysis pipeline
    /api/library/*           Evidence Library (Section 6)
    /ws/tenders/{id}/progress    tender pipeline progress
    /ws/library/{job_id}         indexing progress
    /health                  liveness + a real Postgres round-trip
    /demo                    the static tender console, when present

Two deliberate additions over the source copy of this module:

1. CORS. The source ran the API and its demo console from the same origin, so it
   needed none. This project's frontend is a Vite dev server on :5173, which is
   a different origin, and every request would fail preflight without this. The
   allowed origins come from settings so they can be tightened in production
   rather than hardcoded here. `Content-Disposition` is exposed because
   GET /api/library/documents/{id}/file sends the original filename in it and
   the viewer reads it off the response.

2. A path-safe static mount. The source mounted StaticFiles(directory="static"),
   which resolves against the process working directory — so `uvicorn
   app.main:app` from anywhere other than backend/ raised at import time and the
   whole API failed to boot over a demo page. Resolved relative to this file
   instead, and skipped entirely when the directory is absent.
"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.api.routes.auth import router as auth_router
from app.api.routes.library import router as library_router
from app.api.routes.library_ws import router as library_ws_router
from app.api.routes.tenders import router as tenders_router
from app.api.routes.ws import router as ws_router
from app.core.config import get_settings
from app.core.database import engine

logger = logging.getLogger(__name__)

settings = get_settings()

app = FastAPI(title="VR-Nexus Tender Analysis System", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)

_STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
if _STATIC_DIR.is_dir():
    app.mount("/demo", StaticFiles(directory=str(_STATIC_DIR), html=True), name="demo")
else:
    logger.info("No static/ directory at %s; /demo is not mounted.", _STATIC_DIR)

app.include_router(auth_router)
app.include_router(tenders_router)
app.include_router(ws_router)
app.include_router(library_router)
app.include_router(library_ws_router)


@app.get("/health")
def health_check():
    """Confirms the API process is up and can reach Postgres."""
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"status": "ok", "database": "connected"}
