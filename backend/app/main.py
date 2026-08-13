"""FastAPI application entrypoint — Evidence Library Management Subsystem (WBS 6)."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.api import library, ws
from app.config import settings
from app.db import engine

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        "Evidence Library API starting — embeddings=%s (%d-dim), LLM=%s",
        settings.EMBEDDING_MODEL,
        settings.EMBEDDING_DIM,
        "enabled" if settings.llm_available else "disabled",
    )
    if not settings.llm_available:
        logger.info(
            "LLM fallback is off (no OPENAI_API_KEY). Parsing and tagging will use "
            "heuristics only."
        )
    yield


app = FastAPI(
    title="Evidence Library API",
    description=(
        "RAG indexing and retrieval for tender evidence assets — case studies, "
        "methodology documents and company documents (WBS Section 6)."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(library.router)
app.include_router(ws.router)


@app.get("/health")
def health() -> dict:
    """Liveness plus a real database round-trip.

    Reports degraded rather than raising: a failing health check that returns
    502 tells you less than one that names which dependency is down.
    """
    db_ok = True
    db_error = ""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:
        db_ok = False
        db_error = str(exc)

    return {
        "status": "ok" if db_ok else "degraded",
        "database": "ok" if db_ok else db_error,
        "embedding_model": settings.EMBEDDING_MODEL,
        "embedding_dim": settings.EMBEDDING_DIM,
        "llm_available": settings.llm_available,
    }


# The test UI (WBS 6.2 exercised end to end). Mounted only if present so the
# API image stays usable without it.
# Two candidates because the layout differs: in the container `backend/` is
# flattened to `/app`, so the UI sits at /app/frontend; running from a host
# checkout it is a sibling of `backend/`.
_here = Path(__file__).resolve()
_frontend = next(
    (p for p in (_here.parents[1] / "frontend", _here.parents[2] / "frontend") if p.is_dir()),
    None,
)
if _frontend is not None:
    app.mount("/ui", StaticFiles(directory=str(_frontend), html=True), name="ui")

    @app.get("/", include_in_schema=False)
    def index() -> RedirectResponse:
        return RedirectResponse("/ui/")

else:  # pragma: no cover

    @app.get("/", include_in_schema=False)
    def index() -> RedirectResponse:
        return RedirectResponse("/docs")
