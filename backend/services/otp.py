# Paste contents from the generated services/otp.py here
# backend/services/otp.py
"""
OTP service — generates, delivers, and verifies 6-digit one-time passwords.

Delivery: Fast2SMS DLT-approved route (India, ₹0.13/SMS, no credit card needed).
Storage:  In-memory dict with TTL expiry (no Redis dependency on free tier).
          For production scale (>1,000 farms), swap _store for Redis with EXPIRE.

Security decisions:
    - 6-digit numeric OTP (1,000,000 combinations)
    - 10-minute expiry (configurable in settings)
    - Max 3 attempts per OTP before invalidation (brute-force guard)
    - Constant-time comparison to prevent timing attacks
    - Old OTP invalidated on every new send (no accumulation)

Fast2SMS API:
    Endpoint : https://www.fast2sms.com/dev/bulkV2
    Auth     : Authorization: <api_key> header
    Route    : 'dlt' for transactional (requires DLT registration)
               'q'   for quick transactional (no DLT, higher cost/lower reliability)
    We default to 'dlt' — change FAST2SMS_ROUTE in .env if needed.

DLT (Distributed Ledger Technology) registration:
    Required by TRAI for transactional SMS in India.
    Register sender ID and template at https://www.vilpower.in
    Template: "Your ELISA verification code is {#var#}. Valid for 10 minutes."
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import random
import time
from dataclasses import dataclass, field
from threading import Lock
from typing import Optional

import httpx

_log = logging.getLogger(__name__)

# Fast2SMS API endpoint
_FAST2SMS_URL = "https://www.fast2sms.com/dev/bulkV2"

# Default OTP route — 'dlt' for registered transactional, 'q' for quick
_DEFAULT_ROUTE = "dlt"

# DLT template variable name as registered with TRAI/VILPower
# Matches the template: "Your ELISA verification code is {#var#}."
_DLT_TEMPLATE_ID = "your_dlt_template_id_here"   # replace with actual ID after DLT registration


# ── In-memory OTP store ───────────────────────────────────────────────────────

@dataclass
class _OTPRecord:
    """One stored OTP with expiry and attempt counter."""
    otp_hash:   bytes      # HMAC-SHA256 of the OTP so raw value is never stored
    expires_at: float      # unix timestamp
    attempts:   int = 0
    max_attempts: int = 3


class _OTPStore:
    """
    Thread-safe in-memory OTP store.
    Automatically cleans up expired records on every write.
    Replace with Redis for multi-process / multi-server deployments.
    """

    def __init__(self) -> None:
        self._data: dict[str, _OTPRecord] = {}
        self._lock = Lock()

    def _hmac(self, phone: str, otp: str) -> bytes:
        """Keyed hash of phone+otp so we never store the raw OTP."""
        from core.config import get_settings
        key = get_settings().jwt_secret.encode()
        return hmac.new(key, f"{phone}:{otp}".encode(), hashlib.sha256).digest()

    def put(self, phone: str, otp: str, ttl_seconds: int) -> None:
        with self._lock:
            self._purge_expired()
            self._data[phone] = _OTPRecord(
                otp_hash   = self._hmac(phone, otp),
                expires_at = time.time() + ttl_seconds,
            )

    def verify(self, phone: str, otp: str) -> tuple[bool, str]:
        """
        Returns (success, reason).
        Possible reasons: 'ok', 'not_found', 'expired', 'invalid', 'max_attempts'
        """
        with self._lock:
            record = self._data.get(phone)
            if record is None:
                return False, "not_found"

            if time.time() > record.expires_at:
                del self._data[phone]
                return False, "expired"

            record.attempts += 1
            if record.attempts > record.max_attempts:
                del self._data[phone]
                return False, "max_attempts"

            expected = self._hmac(phone, otp)
            if not hmac.compare_digest(expected, record.otp_hash):
                return False, "invalid"

            # Valid — consume
            del self._data[phone]
            return True, "ok"

    def _purge_expired(self) -> None:
        now = time.time()
        expired = [k for k, v in self._data.items() if now > v.expires_at]
        for k in expired:
            del self._data[k]

    def has_pending(self, phone: str) -> bool:
        with self._lock:
            record = self._data.get(phone)
            return record is not None and time.time() <= record.expires_at


# Module-level singleton store
_store = _OTPStore()


# ── OTP generation ────────────────────────────────────────────────────────────

def _generate_otp() -> str:
    """Generates a cryptographically random 6-digit OTP."""
    return f"{random.SystemRandom().randint(0, 999_999):06d}"


# ── SMS delivery ───────────────────────────────────────────────────────────────

async def send_otp(phone: str) -> dict:
    """
    Generates a new OTP, stores it, and delivers it via Fast2SMS.

    Args:
        phone: Phone number in +91XXXXXXXXXX or 10-digit format.

    Returns:
        {
            "sent": bool,
            "phone": str,             # sanitised number
            "expires_in_seconds": int,
            "message": str,           # human-readable status
        }

    Raises:
        OTPDeliveryError on Fast2SMS API failure.
    """
    from core.config import get_settings
    cfg = get_settings()

    phone = _sanitise_phone(phone)
    otp   = _generate_otp()
    ttl   = cfg.otp_expire_minutes * 60

    # Store before sending — if send fails we can still tell user to retry
    _store.put(phone, otp, ttl_seconds=ttl)

    if not cfg.fast2sms_api_key:
        # Dev mode — log OTP, don't send SMS
        _log.warning(
            "FAST2SMS_API_KEY not set. Dev mode: OTP for %s is %s",
            phone, otp,
        )
        return {
            "sent":                True,
            "phone":               phone,
            "expires_in_seconds":  ttl,
            "message":             f"[DEV] OTP logged to server (not SMS): {otp}",
            "dev_otp":             otp,   # REMOVE in production
        }

    await _deliver_sms(phone, otp, cfg.fast2sms_api_key)

    _log.info("OTP sent to %s (expires in %ds).", phone, ttl)
    return {
        "sent":               True,
        "phone":              phone,
        "expires_in_seconds": ttl,
        "message":            "OTP sent successfully.",
    }


async def _deliver_sms(phone: str, otp: str, api_key: str) -> None:
    """
    Sends OTP via Fast2SMS.
    10-digit phone (no country code) required by Fast2SMS.
    """
    phone_10 = phone.lstrip("+91").lstrip("91")[-10:]

    params = {
        "authorization": api_key,
        "route":         _DEFAULT_ROUTE,
        "numbers":       phone_10,
        "variables_values": otp,
        "flash":         "0",
    }
    if _DEFAULT_ROUTE == "dlt":
        params["sender_id"]   = "ELISAIO"          # match your DLT sender ID
        params["message"]     = _DLT_TEMPLATE_ID

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(_FAST2SMS_URL, params=params)

    if resp.status_code != 200:
        _log.error("Fast2SMS HTTP %d: %s", resp.status_code, resp.text[:300])
        raise OTPDeliveryError(f"Fast2SMS returned HTTP {resp.status_code}")

    body = resp.json()
    if not body.get("return", False):
        _log.error("Fast2SMS rejected: %s", body)
        raise OTPDeliveryError(f"Fast2SMS rejected: {body.get('message', 'unknown')}")

    _log.info("Fast2SMS accepted for %s. Request ID: %s", phone_10, body.get("request_id"))


# ── OTP verification ───────────────────────────────────────────────────────────

def verify_otp(phone: str, otp: str) -> tuple[bool, str]:
    """
    Verifies a submitted OTP.

    Returns:
        (True, "ok")           — valid, OTP consumed
        (False, "not_found")   — no pending OTP for this phone
        (False, "expired")     — OTP window elapsed
        (False, "invalid")     — wrong code
        (False, "max_attempts") — too many wrong guesses, OTP invalidated
    """
    phone = _sanitise_phone(phone)
    ok, reason = _store.verify(phone, otp)

    if ok:
        _log.info("OTP verified for %s.", phone)
    else:
        _log.warning("OTP verification failed for %s: %s.", phone, reason)

    return ok, reason


# ── Helpers ───────────────────────────────────────────────────────────────────

def _sanitise_phone(phone: str) -> str:
    """
    Normalises to +91XXXXXXXXXX.
    Accepts: 9876543210, 919876543210, +919876543210
    """
    digits = "".join(c for c in phone if c.isdigit())
    if len(digits) == 10:
        return f"+91{digits}"
    if len(digits) == 12 and digits.startswith("91"):
        return f"+{digits}"
    if len(digits) == 13 and digits.startswith("091"):
        return f"+91{digits[3:]}"
    # Already correct or unrecognised — return as-is with + prefix
    if phone.startswith("+"):
        return phone
    return f"+{phone}"


def has_pending_otp(phone: str) -> bool:
    """Returns True if there's an unexpired OTP for this phone number."""
    return _store.has_pending(_sanitise_phone(phone))


class OTPDeliveryError(Exception):
    """Raised when Fast2SMS fails to accept the OTP for delivery."""
    pass