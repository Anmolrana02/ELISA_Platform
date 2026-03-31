# Paste contents from the generated core/security.py here
# backend/core/security.py
"""
JWT helpers and FastAPI current-user dependency.

Token format:
    sub  : str(user.id)   — UUID
    name : user.name
    phone: user.phone
    exp  : unix timestamp

Usage in route:
    from core.security import get_current_user, UserTokenData

    @router.get("/me")
    async def me(user: UserTokenData = Depends(get_current_user)):
        return {"id": user.id, "name": user.name}
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import ExpiredSignatureError, JWTError, jwt
from pydantic import BaseModel

from core.config import get_settings

_bearer = HTTPBearer(auto_error=True)


# ── Token payload schema ──────────────────────────────────────────────────────

class UserTokenData(BaseModel):
    """Decoded JWT payload, injected via Depends(get_current_user)."""
    id:    UUID
    name:  str
    phone: str


# ── Token creation ────────────────────────────────────────────────────────────

def create_access_token(user_id: UUID, name: str, phone: str) -> str:
    cfg = get_settings()
    payload = {
        "sub":   str(user_id),
        "name":  name,
        "phone": phone,
        "exp":   datetime.now(timezone.utc) + timedelta(days=cfg.jwt_expire_days),
        "iat":   datetime.now(timezone.utc),
    }
    return jwt.encode(payload, cfg.jwt_secret, algorithm=cfg.jwt_algorithm)


# ── Token verification ────────────────────────────────────────────────────────

def decode_access_token(token: str) -> UserTokenData:
    cfg = get_settings()
    try:
        payload = jwt.decode(token, cfg.jwt_secret, algorithms=[cfg.jwt_algorithm])
    except ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired. Please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    sub = payload.get("sub")
    if not sub:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload.")

    return UserTokenData(id=UUID(sub), name=payload["name"], phone=payload["phone"])


# ── FastAPI dependency ────────────────────────────────────────────────────────

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> UserTokenData:
    """
    FastAPI dependency that decodes the Bearer token from the
    Authorization header and returns the token payload.

    Use: current_user: UserTokenData = Depends(get_current_user)
    """
    return decode_access_token(credentials.credentials)