"""
SQLAlchemy engine + session factory, and the FastAPI dependency every
endpoint uses to get a request-scoped DB session.
"""
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings

settings = get_settings()

engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,  # avoids "server closed the connection unexpectedly" on idle laptops
    future=True,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, future=True)


def get_db() -> Generator:
    """FastAPI dependency: yields a DB session and always closes it after the request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
