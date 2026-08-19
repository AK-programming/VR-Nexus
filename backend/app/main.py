"""
FastAPI entrypoint. Task 1.1 added the /health check; Task 1.2 the auth
router; Task 7 the tender progress WebSocket; Task 2.1 the tender upload
endpoint; Section 6 (merged) the Evidence Library + its own progress
WebSocket.
"""
from fastapi import FastAPI
from sqlalchemy import text

from app.api.routes.auth import router as auth_router
from app.api.routes.library import router as library_router
from app.api.routes.library_ws import router as library_ws_router
from app.api.routes.tender import router as tender_upload_router
from app.api.routes.tenders import router as tenders_router
from app.api.routes.ws import router as ws_router
from app.core.database import engine
from fastapi.staticfiles import StaticFiles


app = FastAPI(title="Tender Analysis System", version="0.1.0")

app.mount("/demo", StaticFiles(directory="static", html=True), name="demo")
app.include_router(auth_router)
app.include_router(tenders_router)
app.include_router(ws_router)
app.include_router(tender_upload_router)
app.include_router(library_router)
app.include_router(library_ws_router)


@app.get("/health")
def health_check():
    """Confirms the API process is up and can reach Postgres."""
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"status": "ok", "database": "connected"}
