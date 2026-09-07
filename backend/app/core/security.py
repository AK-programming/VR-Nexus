"""
Task 1.2.2 (JWT issuance), 1.2.3 (refresh), 1.2.5 (bcrypt hashing)
Linked requirements: AUTH-02, AUTH-03, AUTH-05

Two things live here on purpose, kept separate from the DB/endpoint code:
  1. Password hashing (bcrypt via passlib) - AUTH-05
  2. JWT create/decode (python-jose) - AUTH-02/03

Nothing in this file touches the database or FastAPI request objects, so it
can be unit-tested in isolation and reused by any endpoint that needs it.
"""
import secrets
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
    PASSWORD_RESET = "password_reset"


# Refresh tokens deliberately outlive access tokens (7 days vs the 24h
# access token from settings.ACCESS_TOKEN_EXPIRE_MINUTES) so a user doesn't
# have to log in again every single day on a local laptop session.
REFRESH_TOKEN_EXPIRE_DAYS = 7

# Short-lived on purpose: this token travels in plain text inside an email, a
# channel this app does not control the security of. 30 minutes is enough to
# open an inbox and click a link, not enough to matter much if that email
# sits unread for a week.
PASSWORD_RESET_TOKEN_EXPIRE_MINUTES = 30


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


def create_password_reset_token(user_id: uuid.UUID) -> str:
    """No role claim - a password reset doesn't need one, and baking the
    role in would mean a token minted before a role change carried the old
    one. `decode_token` + a check that `type == PASSWORD_RESET` is exactly as
    strong a proof of "this is a legitimate reset for this user" as the
    access/refresh tokens are proof of a session, for the same reason: it is
    signed with JWT_SECRET_KEY, which only this server holds.

    Carries a random `jti` so the reset route (app/api/routes/auth.py) can mark
    this specific token redeemed in app.services.password_reset_tokens after
    first use. Without it a still-valid copy sitting in an inbox, a "Sent"
    folder, or a mail scanner would stay usable for the rest of its 30-minute
    life even after the password was already changed with it once.
    """
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "role": "",
        "type": TokenType.PASSWORD_RESET.value,
        "jti": secrets.token_urlsafe(16),
        "iat": now,
        "exp": now + timedelta(minutes=PASSWORD_RESET_TOKEN_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


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
