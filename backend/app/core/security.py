"""
Task 1.2.2 (JWT issuance), 1.2.3 (refresh), 1.2.5 (bcrypt hashing)
Linked requirements: AUTH-02, AUTH-03, AUTH-05

Two things live here on purpose, kept separate from the DB/endpoint code:
  1. Password hashing (bcrypt via passlib) - AUTH-05
  2. JWT create/decode (python-jose) - AUTH-02/03

Nothing in this file touches the database or FastAPI request objects, so it
can be unit-tested in isolation and reused by any endpoint that needs it.
"""
import uuid
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Optional

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import get_settings

settings = get_settings()

# --- Password hashing (AUTH-05) ---
# bcrypt has a hard 72-byte input limit; passlib's bcrypt scheme enforces
# this for us and raises a clear error instead of silently truncating.
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain_password: str) -> str:
    return pwd_context.hash(plain_password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    return pwd_context.verify(plain_password, password_hash)


# --- JWT (AUTH-02 login issuance, AUTH-03 refresh) ---
class TokenType(str, Enum):
    ACCESS = "access"
    REFRESH = "refresh"


# Refresh tokens deliberately outlive access tokens (7 days vs the 24h
# access token from settings.ACCESS_TOKEN_EXPIRE_MINUTES) so a user doesn't
# have to log in again every single day on a local laptop session.
REFRESH_TOKEN_EXPIRE_DAYS = 7


def _create_token(user_id: uuid.UUID, role: str, token_type: TokenType, expires_delta: timedelta) -> str:
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "role": role,
        "type": token_type.value,
        "iat": now,
        "exp": now + expires_delta,
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_access_token(user_id: uuid.UUID, role: str) -> str:
    return _create_token(
        user_id, role, TokenType.ACCESS, timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )


def create_refresh_token(user_id: uuid.UUID, role: str) -> str:
    return _create_token(user_id, role, TokenType.REFRESH, timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS))


def decode_token(token: str) -> Optional[dict]:
    """Returns the decoded payload, or None if the token is invalid/expired.

    Callers check payload["type"] themselves - this function only proves the
    signature and expiry are valid, not which kind of token it is. That
    matters because an access token must never be accepted where a refresh
    token is expected, or vice versa (see AUTH-03).
    """
    try:
        return jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except JWTError:
        return None
