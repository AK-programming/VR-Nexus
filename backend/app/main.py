"""
FastAPI entrypoint. Task 1.1 added the /health check; Task 1.2 adds the
auth router (register/login/refresh/me). Future tasks (tender workflow,
library endpoints) will register their own routers here the same way.
"""
from fastapi import FastAPI
from sqlalchemy import text

from app.api.routes.auth import router as auth_router
from app.core.database import engine

app = FastAPI(title="Tender Analysis System", version="0.1.0")

app.include_router(auth_router)


@app.get("/health")
def health_check():
    """Confirms the API process is up and can reach Postgres."""
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"status": "ok", "database": "connected"}
