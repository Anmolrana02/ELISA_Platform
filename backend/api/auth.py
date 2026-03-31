# Paste contents from the generated api/auth.py here
# backend/api/auth.py
"""
Auth routes — phone-based OTP authentication.

Flow:
    1. POST /auth/send-otp   { phone }
       → generates 6-digit OTP, delivers via Fast2SMS, stores in memory
    2. POST /auth/verify-otp { phone, otp }
       → verifies OTP, upserts user row, returns JWT
    3. GET  /auth/me
       → returns current user from JWT (no DB hit)

Phone normalisation:
    All routes accept 10-digit (9876543210), +91 prefixed (+919876543210),
    or bare 91 prefixed (919876543210). The OTP service normalises to
    +91XXXXXXXXXX before storage so both requests must use the same logical
    number.

Upsert on verify:
    If a user with this phone exists → update name if provided, return token.
    If not → create new user row with the name from the request body.
    This lets farmers re-register on a new device without losing farm data.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.security import UserTokenData, create_access_token, get_current_user
from db_models.user import User
from services.otp import OTPDeliveryError, has_pending_otp, send_otp, verify_otp

router = APIRouter(prefix="/auth", tags=["auth"])


# ── Request / response schemas ────────────────────────────────────────────────

class SendOTPRequest(BaseModel):
    phone: str = Field(..., examples=["+919876543210"])

    @field_validator("phone")
    @classmethod
    def normalise(cls, v: str) -> str:
        from services.otp import _sanitise_phone
        return _sanitise_phone(v)


class VerifyOTPRequest(BaseModel):
    phone: str = Field(..., examples=["+919876543210"])
    otp:   str = Field(..., min_length=6, max_length=6, examples=["123456"])
    name:  Optional[str] = Field(None, max_length=100, examples=["Ramesh Kumar"])
    language: Optional[str] = Field("hi", pattern="^(hi|en)$")

    @field_validator("phone")
    @classmethod
    def normalise(cls, v: str) -> str:
        from services.otp import _sanitise_phone
        return _sanitise_phone(v)


class SendOTPResponse(BaseModel):
    sent:               bool
    phone:              str
    expires_in_seconds: int
    message:            str
    dev_otp:            Optional[str] = None  # only present in dev mode


class TokenResponse(BaseModel):
    access_token: str
    token_type:   str = "bearer"
    user: dict


class MeResponse(BaseModel):
    id:              str
    name:            str
    phone:           str
    language:        str
    whatsapp_opt_in: bool


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post(
    "/send-otp",
    response_model=SendOTPResponse,
    status_code=status.HTTP_200_OK,
    summary="Send a 6-digit OTP to the farmer's phone via SMS",
)
async def send_otp_route(body: SendOTPRequest) -> SendOTPResponse:
    """
    Sends a one-time password to the given phone number via Fast2SMS.

    - If an OTP was already sent within the last 10 minutes, a new one
      is generated and replaces the old one (idempotent resend).
    - Returns `dev_otp` field in development mode (FAST2SMS_API_KEY not set).
      Remove from production response.
    """
    try:
        result = await send_otp(body.phone)
    except OTPDeliveryError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"SMS delivery failed: {exc}. Please try again.",
        )
    return SendOTPResponse(**result)


@router.post(
    "/verify-otp",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Verify OTP and receive a JWT access token",
)
async def verify_otp_route(
    body: VerifyOTPRequest,
    db:   AsyncSession = Depends(get_db),
) -> TokenResponse:
    """
    Verifies the submitted OTP.

    On success:
    - Upserts the user row (creates if first login, updates name if returning user).
    - Returns a JWT valid for 30 days.

    On failure:
    - 401 for invalid / expired OTP.
    - 429 for too many wrong attempts (OTP has been invalidated — resend required).
    """
    ok, reason = verify_otp(body.phone, body.otp)

    if not ok:
        if reason == "max_attempts":
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many incorrect attempts. Please request a new OTP.",
            )
        detail_map = {
            "not_found": "No OTP found for this number. Please request a new one.",
            "expired":   "OTP has expired. Please request a new one.",
            "invalid":   "Incorrect OTP. Please try again.",
        }
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail_map.get(reason, "OTP verification failed."),
        )

    # Upsert user
    result = await db.execute(select(User).where(User.phone == body.phone))
    user   = result.scalar_one_or_none()

    if user is None:
        # First login — require name
        if not body.name:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Name is required for first-time registration.",
            )
        user = User(
            name            = body.name,
            phone           = body.phone,
            language        = body.language or "hi",
            whatsapp_opt_in = True,
        )
        db.add(user)
        await db.flush()   # get user.id before commit
    else:
        # Returning user — optionally update name
        if body.name and body.name != user.name:
            user.name = body.name
        if body.language:
            user.language = body.language

    await db.commit()
    await db.refresh(user)

    token = create_access_token(user.id, user.name, user.phone)

    return TokenResponse(
        access_token=token,
        user={
            "id":              str(user.id),
            "name":            user.name,
            "phone":           user.phone,
            "language":        user.language,
            "whatsapp_opt_in": user.whatsapp_opt_in,
        },
    )


@router.get(
    "/me",
    response_model=MeResponse,
    status_code=status.HTTP_200_OK,
    summary="Return the current authenticated user (from JWT — no DB hit)",
)
async def me(current_user: UserTokenData = Depends(get_current_user)) -> MeResponse:
    """
    Returns the authenticated user's profile decoded from the JWT.
    No database query — fast and stateless.

    If the farmer's name or language was updated after token issue,
    the stale token will show old values until they re-authenticate.
    For a single-device, long-session use case this is acceptable.
    """
    return MeResponse(
        id              = str(current_user.id),
        name            = current_user.name,
        phone           = current_user.phone,
        language        = "hi",   # not stored in token — treated as default
        whatsapp_opt_in = True,
    )


@router.get(
    "/me/full",
    response_model=MeResponse,
    status_code=status.HTTP_200_OK,
    summary="Return current user from DB (includes latest language/opt-in settings)",
)
async def me_full(
    current_user: UserTokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MeResponse:
    """
    DB-backed version of /me — returns up-to-date language and opt-in settings.
    """
    result = await db.execute(select(User).where(User.id == current_user.id))
    user   = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    return MeResponse(
        id              = str(user.id),
        name            = user.name,
        phone           = user.phone,
        language        = user.language,
        whatsapp_opt_in = user.whatsapp_opt_in,
    )


@router.patch(
    "/me/preferences",
    status_code=status.HTTP_200_OK,
    summary="Update language and WhatsApp opt-in preferences",
)
async def update_preferences(
    language:        Optional[str]  = None,
    whatsapp_opt_in: Optional[bool] = None,
    current_user: UserTokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(select(User).where(User.id == current_user.id))
    user   = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    if language and language in ("hi", "en"):
        user.language = language
    if whatsapp_opt_in is not None:
        user.whatsapp_opt_in = whatsapp_opt_in

    await db.commit()
    return {"updated": True, "language": user.language, "whatsapp_opt_in": user.whatsapp_opt_in}