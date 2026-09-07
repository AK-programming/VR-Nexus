"""
Task 1.2.1 - Register endpoint
Task 1.2.2 - Login endpoint + JWT issuance
Task 1.2.3 - Token refresh endpoint
Task 1.2.6 - Account lockout after failed attempts
Forgot/reset password - request a reset link by email, then redeem it
Linked requirements: AUTH-01, AUTH-02, AUTH-03, AUTH-06
"""
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import (
    PASSWORD_RESET_TOKEN_EXPIRE_MINUTES,
    TokenType,
    create_access_token,
    create_password_reset_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.services.password_reset_tokens import redeem as redeem_password_reset_token
from app.models.user import User
from app.schemas.auth import (
    ForgotPasswordRequest,
    LoginRequest,
    MessageOut,
    RefreshRequest,
    RegisterRequest,
    ResetPasswordRequest,
    TokenResponse,
    UserOut,
)
from app.services.account_email import (
    AccountEmailFailed,
    AccountEmailNotConfigured,
    send_password_reset_email,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])
settings = get_settings()
logger = logging.getLogger(__name__)


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
    user = User(
        name=data.name,
        email=data.email,
        password_hash=hash_password(data.password),
        phone_number=data.phone_number,
        company=data.company,
    )
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


@router.post("/forgot-password", response_model=MessageOut)
async def forgot_password(data: ForgotPasswordRequest, db: Session = Depends(get_db)):
    """Email a reset link when the address is registered.

    Deliberately explicit about "no such account" rather than the usual
    non-committal "if this email exists, we've sent a link" wording. That
    ambiguity exists to stop a stranger from probing a public sign-up service
    for which emails are registered; this is an internal sales-team tool with
    a small, known roster, not a public one, and a rep who mistyped their
    email (or never registered) needs to be told that plainly, not left
    staring at a vague success message wondering if it worked.
    """
    user = db.query(User).filter(User.email == data.email).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No account is registered with that email. Please register first.",
        )

    token = create_password_reset_token(user.id)
    reset_url = f"{settings.PASSWORD_RESET_URL_BASE}/reset-password?token={token}"

    try:
        await send_password_reset_email(user.email, user.name, reset_url)
    except AccountEmailNotConfigured as exc:
        # Configuration problem, not the user's fault - 503, not 400/404.
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except AccountEmailFailed as exc:
        logger.warning("Password reset email failed for %s: %s", user.email, exc)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    return MessageOut(message="A password reset link has been sent to your email.")


@router.post("/reset-password", response_model=MessageOut)
def reset_password(data: ResetPasswordRequest, db: Session = Depends(get_db)):
    """Redeem a reset token minted by /forgot-password for a new password.

    Single-use: `jti` is claimed in Redis (app.services.password_reset_tokens)
    before anything else happens, so a token that has already changed one
    password - whether redeemed by the account holder or replayed by whoever
    else saw the email - cannot change it a second time, even though the JWT
    itself would otherwise still verify for the rest of its 30-minute life.
    """
    invalid_token = HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="This reset link is invalid or has expired. Request a new one.",
    )

    payload = decode_token(data.token)
    if payload is None or payload.get("type") != TokenType.PASSWORD_RESET.value:
        raise invalid_token

    jti = payload.get("jti")
    if not jti or not redeem_password_reset_token(jti, PASSWORD_RESET_TOKEN_EXPIRE_MINUTES * 60):
        # Missing jti: a token minted before this check existed - treat it the
        # same as already-used rather than trusting a token this server can no
        # longer prove was only used once. Already claimed: a genuine replay.
        raise invalid_token

    user = db.get(User, payload.get("sub"))
    if user is None:
        raise invalid_token

    user.password_hash = hash_password(data.new_password)
    # A forgotten password is often WHY the account got locked out in the
    # first place (repeated guesses before giving up and resetting) - clear
    # the lockout along with it, or the successful reset would still leave
    # them unable to sign in for the rest of the lockout window.
    user.failed_login_attempts = 0
    user.locked_until = None
    db.commit()

    return MessageOut(message="Your password has been reset. Sign in with your new password.")
