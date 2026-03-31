# Paste contents from the generated services/whatsapp.py here
# backend/services/whatsapp.py
"""
WhatsApp notification service — Meta Cloud API (direct).

Template names (must be pre-approved in Meta Business Manager):
    elisa_irrigation_alert_hi  — Hindi
    elisa_irrigation_alert_en  — English

Template variables (1-indexed as Meta requires):
    {{1}}  farmer name
    {{2}}  farm name
    {{3}}  pump start hour  (e.g. "00")
    {{4}}  pump end hour    (e.g. "02")
    {{5}}  tariff slot      (e.g. "Low")
    {{6}}  cost INR         (e.g. "21.24")
    {{7}}  day-1 SM forecast mm  (e.g. "142")
    {{8}}  24h rain forecast mm  (e.g. "3.2")

Delivery tracking:
    Every message attempt is logged to Python logger.
    The caller (scheduler.py / irrigation.py) is responsible for
    updating the predictions.whatsapp_sent column on success.

Error handling:
    Meta API returns 200 even for "accepted" (not yet delivered) messages.
    Non-200 responses are logged and raise WhatsAppDeliveryError.
    Callers should catch this and mark whatsapp_sent=False rather than
    crashing the entire daily job.

Rate limits:
    Free Meta tier: 1,000 conversations/month per phone number.
    Each 24-hour window = 1 conversation. So 1,000 unique farmers/month.
    No artificial rate limiting here — the caller (scheduler) runs once/day.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import httpx

_log = logging.getLogger(__name__)

# Language → Meta template name mapping
_TEMPLATES = {
    "hi": "elisa_irrigation_alert_hi",
    "en": "elisa_irrigation_alert_en",
}

# Language → Meta language code
_LANG_CODES = {
    "hi": "hi",
    "en": "en_US",
}


class WhatsAppDeliveryError(Exception):
    """Raised when Meta API returns a non-success response."""
    def __init__(self, status_code: int, body: str):
        super().__init__(f"WhatsApp API error {status_code}: {body}")
        self.status_code = status_code
        self.body        = body


@dataclass
class AlertPayload:
    """All data needed to send one irrigation alert."""
    farmer_name:    str
    farm_name:      str
    phone:          str          # +91XXXXXXXXXX
    language:       str          # 'hi' or 'en'
    pump_start_h:   int          # 0–23
    pump_end_h:     int          # 0–23
    tariff_slot:    str          # 'Low', 'Medium', 'Peak'
    cost_inr:       float
    sm_day1_mm:     float
    rain_24h_mm:    float


# ── Core sender ───────────────────────────────────────────────────────────────

async def send_irrigation_alert(payload: AlertPayload) -> dict:
    """
    Sends an irrigation alert via Meta Cloud API using a pre-approved template.

    Args:
        payload: AlertPayload dataclass with all template variables.

    Returns:
        Meta API response dict on success.

    Raises:
        WhatsAppDeliveryError on non-200 response.
        httpx.RequestError on network failure.
    """
    from core.config import get_settings
    cfg = get_settings()

    if not cfg.whatsapp_token or not cfg.whatsapp_phone_number_id:
        _log.warning(
            "WhatsApp credentials not configured. Alert for %s NOT sent.",
            payload.phone,
        )
        return {"skipped": True, "reason": "credentials_not_configured"}

    lang     = payload.language if payload.language in _TEMPLATES else "hi"
    template = _TEMPLATES[lang]
    lang_code = _LANG_CODES[lang]

    # Format display values
    start_str   = f"{payload.pump_start_h:02d}"
    end_str     = f"{payload.pump_end_h:02d}"
    cost_str    = f"{payload.cost_inr:.2f}"
    sm_str      = f"{payload.sm_day1_mm:.0f}"
    rain_str    = f"{payload.rain_24h_mm:.1f}"
    tariff_str  = _localise_tariff(payload.tariff_slot, lang)

    body = _build_request_body(
        to=payload.phone,
        template=template,
        lang_code=lang_code,
        params=[
            payload.farmer_name,  # {{1}}
            payload.farm_name,    # {{2}}
            start_str,            # {{3}}
            end_str,              # {{4}}
            tariff_str,           # {{5}}
            cost_str,             # {{6}}
            sm_str,               # {{7}}
            rain_str,             # {{8}}
        ],
    )

    _log.info(
        "Sending WhatsApp alert: phone=%s farm=%r template=%s",
        payload.phone, payload.farm_name, template,
    )

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            cfg.whatsapp_api_url,
            headers={
                "Authorization": f"Bearer {cfg.whatsapp_token}",
                "Content-Type":  "application/json",
            },
            json=body,
        )

    if resp.status_code not in (200, 201):
        _log.error(
            "WhatsApp delivery failed: phone=%s status=%d body=%s",
            payload.phone, resp.status_code, resp.text[:500],
        )
        raise WhatsAppDeliveryError(resp.status_code, resp.text)

    response_data = resp.json()
    message_id = (
        response_data.get("messages", [{}])[0].get("id", "unknown")
        if "messages" in response_data else "unknown"
    )
    _log.info(
        "WhatsApp alert sent: phone=%s message_id=%s",
        payload.phone, message_id,
    )
    return response_data


# ── "No irrigation" notification (optional, weekly summary) ──────────────────

async def send_status_update(
    phone:        str,
    farmer_name:  str,
    farm_name:    str,
    sm_mm:        float,
    language:     str = "hi",
) -> dict:
    """
    Sends a plain text message (not a template) when no irrigation is needed.
    Uses the free-form message type — only valid within 24h of a user message.

    NOTE: In production, pre-approve a separate status template instead.
    For now this uses the text type as a developer test message.
    This will NOT work outside the 24-hour customer-initiated window on
    production phone numbers. Kept here for completeness / dev testing.
    """
    from core.config import get_settings
    cfg = get_settings()

    if not cfg.whatsapp_token:
        return {"skipped": True, "reason": "credentials_not_configured"}

    if language == "hi":
        text = (
            f"Namaskar {farmer_name} ji! "
            f"Aapke *{farm_name}* mein aaj sinchai ki zaroorat nahi. "
            f"Maati ki nami: {sm_mm:.0f}mm. — ELISA"
        )
    else:
        text = (
            f"Hello {farmer_name}! "
            f"No irrigation needed today for *{farm_name}*. "
            f"Soil moisture: {sm_mm:.0f}mm. — ELISA"
        )

    body = {
        "messaging_product": "whatsapp",
        "to":   phone,
        "type": "text",
        "text": {"body": text},
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            cfg.whatsapp_api_url,
            headers={
                "Authorization": f"Bearer {cfg.whatsapp_token}",
                "Content-Type":  "application/json",
            },
            json=body,
        )

    if resp.status_code not in (200, 201):
        raise WhatsAppDeliveryError(resp.status_code, resp.text)

    return resp.json()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _build_request_body(
    to:        str,
    template:  str,
    lang_code: str,
    params:    list[str],
) -> dict:
    """Builds the Meta Cloud API request body for a template message."""
    return {
        "messaging_product": "whatsapp",
        "to":   to,
        "type": "template",
        "template": {
            "name":     template,
            "language": {"code": lang_code},
            "components": [
                {
                    "type":       "body",
                    "parameters": [
                        {"type": "text", "text": str(p)}
                        for p in params
                    ],
                }
            ],
        },
    }


def _localise_tariff(slot: str, lang: str) -> str:
    """Translates tariff slot names for the WhatsApp message."""
    _SLOT_HI = {"low": "सस्ता (रात)", "medium": "सामान्य", "peak": "महंगा (शाम)"}
    _SLOT_EN = {"low": "Low (night)", "medium": "Medium",   "peak": "Peak (evening)"}
    table = _SLOT_HI if lang == "hi" else _SLOT_EN
    return table.get(slot.lower(), slot)


def build_alert_payload_from_prediction(
    prediction: dict,
    user_name:  str,
    farm_name:  str,
    phone:      str,
    language:   str,
) -> Optional[AlertPayload]:
    """
    Convenience factory that builds an AlertPayload from a prediction dict
    as returned by ml_bridge.get_prediction().

    Returns None if the prediction says no irrigation needed
    (caller should check irrigate before sending alert).
    """
    if not prediction.get("irrigate"):
        return None

    return AlertPayload(
        farmer_name  = user_name,
        farm_name    = farm_name,
        phone        = phone,
        language     = language,
        pump_start_h = prediction.get("pump_start_hour") or 0,
        pump_end_h   = prediction.get("pump_end_hour")   or 2,
        tariff_slot  = prediction.get("tariff_slot")     or "low",
        cost_inr     = float(prediction.get("cost_inr")  or 0.0),
        sm_day1_mm   = float(
            prediction["sm_forecast"][0]
            if prediction.get("sm_forecast") else 0.0
        ),
        rain_24h_mm  = float(prediction.get("rain_24h_mm") or 0.0),
    )