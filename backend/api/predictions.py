# Paste contents from the generated api/predictions.py here
# backend/api/predictions.py
"""
Prediction routes.

GET /farms/{farm_id}/predict
    Runs PatchTST 7-day SM forecast + MPC optimizer for today.
    Caches result in the predictions table (one row per farm per day).
    On subsequent calls for the same farm+date, returns the cached row
    without re-running the model (expensive GPU/CPU op).
    Pass ?force=true to bypass cache and re-run.

GET /farms/{farm_id}/predict/history
    Returns the last N prediction rows for a farm — used to draw
    the forecast history chart in the frontend.

Cache strategy:
    We store predictions keyed by (farm_id, date).
    The daily scheduler pre-populates at 05:00 IST, so most daytime
    requests hit the cache. A farmer checking at 06:00 gets sub-100ms
    response; the scheduler's 05:00 run absorbs the 3–10s ML inference.

    If the scheduler hasn't run yet (first deploy, new farm registered
    mid-day) the endpoint runs inference on demand and stores the result.

SM forecast format:
    sm_forecast is a 7-element list of floats in mm.
    [day1_mm, day2_mm, ..., day7_mm]
    Stored as PostgreSQL ARRAY(FLOAT) in the predictions table.
"""

from __future__ import annotations

from datetime import date, timedelta
from sqlalchemy.exc import IntegrityError
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.security import UserTokenData, get_current_user
from db_models.farm import Farm
from db_models.prediction import Prediction
from services.ml_bridge import get_prediction, get_rain_forecast

router = APIRouter(tags=["predictions"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class PredictionResponse(BaseModel):
    farm_id:          str
    date:             str
    irrigate:         bool
    reason:           str
    sm_forecast:      Optional[list[float]]   # 7 values in mm
    pump_start_hour:  Optional[int]
    pump_end_hour:    Optional[int]
    energy_kwh:       Optional[float]
    cost_inr:         Optional[float]
    tariff_slot:      Optional[str]
    rain_24h_mm:      Optional[float]
    whatsapp_sent:    bool
    from_cache:       bool
    created_at:       str


class PredictionHistoryResponse(BaseModel):
    farm_id:     str
    predictions: list[PredictionResponse]


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _get_farm_or_404(farm_id: UUID, user_id: UUID, db: AsyncSession) -> Farm:
    result = await db.execute(
        select(Farm).where(Farm.id == farm_id, Farm.user_id == user_id, Farm.active == True)
    )
    farm = result.scalar_one_or_none()
    if farm is None:
        raise HTTPException(status_code=404, detail="Farm not found.")
    return farm


def _row_to_response(row: Prediction, from_cache: bool) -> PredictionResponse:
    return PredictionResponse(
        farm_id         = str(row.farm_id),
        date            = row.date.isoformat(),
        irrigate        = row.irrigate,
        reason          = row.reason or "",
        sm_forecast     = list(row.sm_forecast) if row.sm_forecast else None,
        pump_start_hour = row.pump_start_hour,
        pump_end_hour   = row.pump_end_hour,
        energy_kwh      = row.energy_kwh,
        cost_inr        = row.cost_inr,
        tariff_slot     = None,  # not persisted; re-derived from start_hour if needed
        rain_24h_mm     = row.rain_24h_mm,
        whatsapp_sent   = row.whatsapp_sent,
        from_cache      = from_cache,
        created_at      = row.created_at.isoformat(),
    )


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get(
    "/farms/{farm_id}/predict",
    response_model=PredictionResponse,
    status_code=status.HTTP_200_OK,
    summary="Get 7-day soil moisture forecast and irrigation decision",
)
async def predict(
    farm_id:      UUID,
    force:        bool         = Query(False, description="Bypass cache and re-run ML inference"),
    current_user: UserTokenData = Depends(get_current_user),
    db:           AsyncSession  = Depends(get_db),
) -> PredictionResponse:
    """
    Runs PatchTST + MPC for today and returns the result.

    **Cached**: subsequent calls return the stored prediction for today
    without re-running the model. Use `?force=true` to refresh.

    Response includes:
    - `sm_forecast`: 7-element list [day1_mm … day7_mm]
    - `irrigate`: boolean MPC decision
    - `reason`: plain-text explanation (shown in WhatsApp message)
    - `pump_start_hour` / `pump_end_hour`: cheapest tariff window
    - `cost_inr`: estimated pump energy cost for one event
    - `rain_24h_mm`: 24h rain forecast used in C2 suppression check
    """
    farm = await _get_farm_or_404(farm_id, current_user.id, db)
    today = date.today()

    # ── Check cache ───────────────────────────────────────────────────────────
    if not force:
        cached = await db.execute(
            select(Prediction).where(
                Prediction.farm_id == farm.id,
                Prediction.date    == today,
            )
        )
        row = cached.scalar_one_or_none()
        if row is not None:
            return _row_to_response(row, from_cache=True)

    # ── Run ML inference ──────────────────────────────────────────────────────
    ml_result = await get_prediction(
        farm_id  = str(farm.id),
        district = farm.district or "Meerut",
        crop     = farm.crop,
        on_date  = today,
    )

    if "error" in ml_result:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=ml_result["error"],
        )

    # Fetch rain alongside so it's stored with the prediction
    if farm.centroid_lat and farm.centroid_lon:
        rain_hourly = await get_rain_forecast(farm.centroid_lat, farm.centroid_lon, days=2)
        rain_24h    = round(sum(rain_hourly[:24]), 2)
    else:
        rain_24h = 0.0

    # ── Upsert into predictions table ─────────────────────────────────────────
    # Delete any existing row for today (handles force=true re-run)
    existing = await db.execute(
        select(Prediction).where(
            Prediction.farm_id == farm.id,
            Prediction.date    == today,
        )
    )
    old_row = existing.scalar_one_or_none()
    if old_row is not None:
        await db.delete(old_row)
        await db.flush()

    new_row = Prediction(
        farm_id         = farm.id,
        date            = today,
        sm_forecast     = ml_result.get("sm_forecast"),
        irrigate        = bool(ml_result.get("irrigate", False)),
        pump_start_hour = ml_result.get("pump_start_hour"),
        pump_end_hour   = ml_result.get("pump_end_hour"),
        energy_kwh      = ml_result.get("energy_kwh"),
        cost_inr        = ml_result.get("cost_inr"),
        rain_24h_mm     = rain_24h,
        reason          = ml_result.get("reason", ""),
        whatsapp_sent   = False,
    )
    db.add(new_row)
    await db.commit()
    await db.refresh(new_row)

    # Add tariff_slot from ml_result for this response (not persisted)
    response = _row_to_response(new_row, from_cache=False)
    response.tariff_slot = ml_result.get("tariff_slot")
    return response


@router.get(
    "/farms/{farm_id}/predict/history",
    response_model=PredictionHistoryResponse,
    status_code=status.HTTP_200_OK,
    summary="Get the last N days of prediction history for a farm",
)
async def prediction_history(
    farm_id:      UUID,
    days:         int          = Query(14, ge=1, le=90, description="How many days back to fetch"),
    current_user: UserTokenData = Depends(get_current_user),
    db:           AsyncSession  = Depends(get_db),
) -> PredictionHistoryResponse:
    """
    Returns daily predictions in reverse-chronological order.
    Used by the frontend SM history chart and decision log.
    """
    farm = await _get_farm_or_404(farm_id, current_user.id, db)
    cutoff = date.today() - timedelta(days=days)

    result = await db.execute(
        select(Prediction)
        .where(Prediction.farm_id == farm.id, Prediction.date >= cutoff)
        .order_by(Prediction.date.desc())
    )
    rows = result.scalars().all()

    return PredictionHistoryResponse(
        farm_id     = str(farm.id),
        predictions = [_row_to_response(r, from_cache=True) for r in rows],
    )