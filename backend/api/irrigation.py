# Paste contents from the generated api/irrigation.py here
# backend/api/irrigation.py
"""
Irrigation confirmation route — closes the feedback loop.

POST /farms/{farm_id}/confirm-irrigation
    Farmer taps "I irrigated today" in the app.
    Records the event, runs a FAO-56 physics correction on the SM state,
    recomputes savings, and returns the updated SM for display.

The feedback loop explained:
    Without this: PatchTST sees yesterday's dry SM reading and recommends
    irrigating again tomorrow even though the farmer just irrigated.

    With this:
        1. Event is logged to data/farm_states/{farm_id}_events.csv
        2. update_state() runs FAO-56 water balance:
               SM_new = SM_yesterday + precip + irrigation - ETo
           and clamps to [PWP, FC].
        3. The corrected SM is written to {farm_id}_state.json.
        4. Tomorrow, _get_forecast() calls inject_into_window() which
           replaces the last row's SM with the corrected value before
           building the 30-day PatchTST input sequence.
        5. Model sees correct SM → recommends correctly.

    This is step 3 of the MPC loop:
        Observe → Decide → Actuate (irrigate) → Confirm → Observe again.

GET /farms/{farm_id}/confirm-irrigation/history
    Returns the last 60 days of confirmed irrigation events.
    Shown in the "Log" tab of the farmer dashboard.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.security import UserTokenData, get_current_user
from db_models.farm import Farm
from db_models.prediction import Prediction
from services.ml_bridge import confirm_irrigation, get_farm_irrigation_history
from services.savings_engine import compute_savings, current_season

_log   = logging.getLogger(__name__)
router = APIRouter(tags=["irrigation"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class ConfirmIrrigationRequest(BaseModel):
    irrigation_date: date = Field(
        default_factory=date.today,
        description="Date of irrigation event (defaults to today)",
        examples=["2025-02-14"],
    )
    mm: float = Field(
        ...,
        ge=10.0,
        le=200.0,
        description="Water applied in mm (typical: 70mm Wheat, 50mm Rice)",
        examples=[70.0],
    )
    notes: Optional[str] = Field(
        None,
        max_length=200,
        description="Optional farmer note (e.g. 'pump ran 2.5 hours')",
    )

    @field_validator("irrigation_date", mode="before")
    @classmethod
    def parse_date(cls, v):
        if isinstance(v, str):
            return date.fromisoformat(v)
        return v


class ConfirmIrrigationResponse(BaseModel):
    confirmed:        bool
    farm_id:          str
    date:             str
    mm:               float
    # Updated SM state
    sm_mm:            float
    sm_yesterday_mm:  float
    precip_mm:        float
    eto_mm:           float
    crop:             str
    # Savings snapshot
    water_saved_mm:   float
    cost_saved_inr:   float
    season:           str
    # WhatsApp confirmation flag
    prediction_marked: bool


class IrrigationEventRow(BaseModel):
    date:           str
    irrigation_mm:  float
    source:         str


class IrrigationHistoryResponse(BaseModel):
    farm_id: str
    events:  list[IrrigationEventRow]
    total:   int


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _get_farm_or_404(farm_id: UUID, user_id: UUID, db: AsyncSession) -> Farm:
    result = await db.execute(
        select(Farm).where(Farm.id == farm_id, Farm.user_id == user_id, Farm.active == True)
    )
    farm = result.scalar_one_or_none()
    if farm is None:
        raise HTTPException(status_code=404, detail="Farm not found.")
    return farm


async def _mark_prediction_confirmed(farm_id: UUID, on_date: date, db: AsyncSession) -> bool:
    """
    Sets whatsapp_sent=True on the prediction row for this date —
    repurposed as a 'farmer confirmed' flag to close the alert loop.
    Returns True if a row was found and updated.
    """
    result = await db.execute(
        select(Prediction).where(
            Prediction.farm_id == farm_id,
            Prediction.date    == on_date,
        )
    )
    row = result.scalar_one_or_none()
    if row and not row.whatsapp_sent:
        row.whatsapp_sent = True
        await db.commit()
        return True
    return False


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post(
    "/farms/{farm_id}/confirm-irrigation",
    response_model=ConfirmIrrigationResponse,
    status_code=status.HTTP_200_OK,
    summary="Record a confirmed irrigation event and update SM state",
)
async def confirm_irrigation_route(
    farm_id:      UUID,
    body:         ConfirmIrrigationRequest,
    current_user: UserTokenData = Depends(get_current_user),
    db:           AsyncSession  = Depends(get_db),
) -> ConfirmIrrigationResponse:
    """
    Records a farmer's irrigation event and closes the ML feedback loop.

    **Effect on tomorrow's prediction**:
    After calling this endpoint, the next call to `/predict` will account
    for the irrigation event — the model will see the corrected soil
    moisture level instead of the pre-irrigation value from ERA5.

    **Body**:
    - `date`: date of irrigation (ISO format, defaults to today)
    - `mm`: water applied in mm (10–200mm range)

    **Returns** updated soil moisture state and a savings snapshot.
    """
    farm = await _get_farm_or_404(farm_id, current_user.id, db)

    _log.info(
        "Irrigation confirmed: farm=%s district=%s date=%s mm=%.1f",
        farm_id, farm.district, body.irrigation_date, body.mm,
    )

    # ── 1. Log event + run FAO-56 water balance correction ────────────────────
    try:
        state = confirm_irrigation(
            farm_id  = str(farm.id),
            district = farm.district or "Meerut",
            on_date  = body.irrigation_date,
            mm       = body.mm,
        )
    except Exception as exc:
        _log.error("confirm_irrigation failed for farm %s: %s", farm_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update farm state: {exc}",
        )

    # ── 2. Mark today's prediction row as farmer-confirmed ────────────────────
    prediction_marked = await _mark_prediction_confirmed(farm.id, body.irrigation_date, db)

    # ── 3. Recompute savings (incremental — fast) ─────────────────────────────
    season = current_season(body.irrigation_date)
    try:
        savings = compute_savings(
            farm_id  = str(farm.id),
            district = farm.district or "Meerut",
            crop     = farm.crop,
            season   = season,
        )
        water_saved = savings["water_saved_mm"]
        cost_saved  = savings["cost_saved_inr"]
    except Exception as exc:
        _log.warning("Savings recompute failed (non-fatal): %s", exc)
        water_saved = 0.0
        cost_saved  = 0.0

    _log.info(
        "Feedback loop closed: farm=%s new_sm=%.1fmm water_saved=%.1fmm",
        farm_id, state["sm_mm"], water_saved,
    )

    return ConfirmIrrigationResponse(
        confirmed         = True,
        farm_id           = str(farm.id),
        date              = body.irrigation_date.isoformat(),
        mm                = body.mm,
        # Updated SM
        sm_mm             = round(state["sm_mm"],           1),
        sm_yesterday_mm   = round(state["sm_yesterday_mm"], 1),
        precip_mm         = round(state["precip_mm"],       1),
        eto_mm            = round(state["eto_mm"],          1),
        crop              = state["crop"],
        # Savings
        water_saved_mm    = water_saved,
        cost_saved_inr    = cost_saved,
        season            = season,
        # Loop status
        prediction_marked = prediction_marked,
    )


@router.get(
    "/farms/{farm_id}/confirm-irrigation/history",
    response_model=IrrigationHistoryResponse,
    status_code=status.HTTP_200_OK,
    summary="Get the last 60 days of confirmed irrigation events for a farm",
)
async def irrigation_history(
    farm_id:      UUID,
    days:         int          = 60,
    current_user: UserTokenData = Depends(get_current_user),
    db:           AsyncSession  = Depends(get_db),
) -> IrrigationHistoryResponse:
    """
    Returns the irrigation event log — shown in the "Log" tab of the
    farmer dashboard. Ordered most-recent first.
    """
    farm = await _get_farm_or_404(farm_id, current_user.id, db)

    hist_df = get_farm_irrigation_history(str(farm.id), days=days)

    if hist_df.empty:
        return IrrigationHistoryResponse(
            farm_id = str(farm.id),
            events  = [],
            total   = 0,
        )

    events = [
        IrrigationEventRow(
            date          = str(row["date"].date()) if hasattr(row["date"], "date") else str(row["date"]),
            irrigation_mm = float(row["irrigation_mm"]),
            source        = str(row.get("source", "farmer_confirmed")),
        )
        for _, row in hist_df.iterrows()
    ]

    return IrrigationHistoryResponse(
        farm_id = str(farm.id),
        events  = events,
        total   = len(events),
    )