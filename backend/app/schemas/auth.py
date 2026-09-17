"""
Request/response shapes for the auth endpoints (Task 1.2).
Linked requirements: AUTH-01, AUTH-02, AUTH-03
"""
import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field

from app.models.enums import UserRole


class RegisterRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)  # 72 = bcrypt's hard input limit
    phone_number: Optional[str] = Field(default=None, max_length=32)
    company: Optional[str] = Field(default=None, max_length=255)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(min_length=8, max_length=72)  # 72 = bcrypt's hard input limit


class VerifyEmailRequest(BaseModel):
    token: str


class ResendVerificationRequest(BaseModel):
    email: EmailStr


class MessageOut(BaseModel):
    message: str


class UserOut(BaseModel):
    id: uuid.UUID
    name: str
    email: str
    phone_number: Optional[str] = None
    company: Optional[str] = None
    role: UserRole
    is_active: bool
    last_login_at: Optional[datetime] = None
    # Which optional sections this account can see - empty for a fresh USER,
    # ignored for ADMIN (the frontend already treats role == admin as full
    # access, this just rides along on login/me/register/refresh so a USER's
    # sidebar knows what to show without a second request).
    feature_access: list[str] = []

    model_config = {"from_attributes": True}


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserOut
