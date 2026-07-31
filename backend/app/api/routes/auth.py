"""
Task 1.2.1 - Register endpoint
Task 1.2.2 - Login endpoint + JWT issuance
Task 1.2.3 - Token refresh endpoint
Task 1.2.6 - Account lockout after failed attempts
Linked requirements: AUTH-01, AUTH-02, AUTH-03, AUTH-06
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import (
    TokenType,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.models.user import User
from app.schemas.auth import LoginRequest, RefreshRequest, RegisterRequest, TokenResponse, UserOut

router = APIRouter(prefix="/api/auth", tags=["auth"])
settings = get_settings()


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(data: RegisterRequest, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.email == data.email).first()
    if existing is not None:
        # Same error whether the email exists or is malformed in some other
        # way would be nicer for security, but for an internal sales-team
        # tool, a clear "already registered" message is more useful than
        # ambiguity - there's no public sign-up flow being probed here.
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email is already registered")

    # New accounts are always USER. There is deliberately no "role" field on
    # this request - if the public register endpoint could also mint admins,
    # anyone with API access could hand themselves admin. Promote a user to
    # ADMIN manually in the database (or via a future admin-only endpoint in
    # Task 1.2.4's follow-on work) instead.
    user = User(name=data.name, email=data.email, password_hash=hash_password(data.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/login", response_model=TokenResponse)
def login(data: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == data.email).first()

    # Same generic error for "no such user" and "wrong password" - AUTH-02
    # shouldn't let a caller enumerate which emails exist in the system.
    invalid_credentials = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password"
    )

    if user is None:
        raise invalid_credentials

    # --- AUTH-06: is this account currently locked? ---
    now = datetime.now(timezone.utc)
    if user.locked_until is not None and user.locked_until > now:
        remaining_minutes = int((user.locked_until - now).total_seconds() // 60) + 1
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail=f"Account locked due to too many failed attempts. Try again in {remaining_minutes} minute(s).",
        )

    if not verify_password(data.password, user.password_hash):
        user.failed_login_attempts += 1
        if user.failed_login_attempts >= settings.FAILED_LOGIN_LOCKOUT_THRESHOLD:
            user.locked_until = now + timedelta(minutes=settings.FAILED_LOGIN_LOCKOUT_MINUTES)
        db.commit()
        raise invalid_credentials

    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This account has been disabled")

    # Successful login - reset the lockout counter and record the login time.
    user.failed_login_attempts = 0
    user.locked_until = None
    user.last_login_at = now
    db.commit()
    db.refresh(user)

    return TokenResponse(
        access_token=create_access_token(user.id, user.role.value),
        refresh_token=create_refresh_token(user.id, user.role.value),
        user=user,
    )


@router.post("/refresh", response_model=TokenResponse)
def refresh(data: RefreshRequest, db: Session = Depends(get_db)):
    invalid_refresh = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired refresh token"
    )

    payload = decode_token(data.refresh_token)
    if payload is None or payload.get("type") != TokenType.REFRESH.value:
        # Rejects expired/tampered tokens AND rejects someone passing an
        # access token here instead of a refresh token.
        raise invalid_refresh

    user = db.get(User, payload.get("sub"))
    if user is None or not user.is_active:
        raise invalid_refresh

    return TokenResponse(
        access_token=create_access_token(user.id, user.role.value),
        refresh_token=create_refresh_token(user.id, user.role.value),
        user=user,
    )


@router.get("/me", response_model=UserOut)
def get_me(current_user: User = Depends(get_current_user)):
    return current_user
