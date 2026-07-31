"""
Minimal FastAPI entrypoint. Right now it only exists so Task 1.1 can be
verified end-to-end (env -> DB connection -> tables). Auth endpoints
(Task 1.2), the tender workflow, and the library endpoints get added to
this app in later tasks.
"""
from fastapi import FastAPI
from sqlalchemy import text

from app.core.database import engine

app = FastAPI(title="Tender Analysis System", version="0.1.0")


@app.get("/health")
def health_check():
    """Confirms the API process is up and can reach Postgres."""
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"status": "ok", "database": "connected"}
