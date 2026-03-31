# Paste contents from the generated api/savings.py here
# backend/api/savings.py
"""
Savings report routes.

GET /farms/{farm_id}/savings
    Current-season savings vs blind farmer baseline.
    Reads from savings_log table (pre-computed by scheduler or on
    confirm-irrigation). If no row exists yet, computes on demand
    and stores it.

GET /farms/{farm_id}/savings/history
    Last N seasons of savings data — for the history chart.

PUT /farms/{farm_id}/savings/recompute
    Force re-run of savings_engine for the current season.
    Called by the scheduler after each confirmed irrigation event.

Design:
    Savings are compared against the Blind farmer simulation:
        Blind = irrigate every 10 days, 80mm, regardless of anything.
    This is the default practice in Western UP and the comparison
    baseline used in the ELISA 2.0 paper.

    The `water_saved_mm` and `cost_saved_inr` fields in the response
    are the headline numbers shown on the Savings page of the app.
    These are also the numbers that go into the M.Tech thesis figures.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.security import UserTokenData, get_current_user
from db_models.farm import Farm
from db_models.savings import SavingsLog
from services.savings_engine import (
    compute_all_seasons,
    compute_savings,
    current_season,
)

_log   = logging.getLogger(__name__)
router = APIRouter(tags=["savings"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class SavingsResponse(BaseModel):
    farm_id:                str
    season:                 str
    district:               str
    crop:                   str
    # Event counts
    actual_events:          int
    blind_baseline_events:  int
    # Water
    actual_water_mm:        float
    blind_water_mm:         float
    water_saved_mm:         float
    # Energy & cost
    actual_energy_kwh:      float
    blind_energy_kwh:       float
    actual_cost_inr:        float
    blind_cost_inr:         float
    cost_saved_inr:         float
    # Percentages
    savings_pct_water:      float
    savings_pct_cost:       float
    # Stress
    stress_days:            int
    # Meta
    computed_at:            str


class SavingsHistoryResponse(BaseModel):
    farm_id:  str
    seasons:  list[SavingsResponse]


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _get_farm_or_404(farm_id: UUID, user_id: UUID, db: AsyncSession) -> Farm:
    result = await db.execute(
        select(Farm).where(Farm.id == farm_id, Farm.user_id == user_id, Farm.active == True)
    )
    farm = result.scalar_one_or_none()
    if farm is None:
        raise HTTPException(status_code=404, detail="Farm not found.")
    return farm


def _engine_result_to_response(farm_id: str, d: dict) -> SavingsResponse:
    return SavingsResponse(
        farm_id               = farm_id,
        season                = d["season"],
        district              = d["district"],
        crop                  = d["crop"],
        actual_events         = d["actual_events"],
        blind_baseline_events = d["blind_baseline_events"],
        actual_water_mm       = d["actual_water_mm"],
        blind_water_mm        = d["blind_water_mm"],
        water_saved_mm        = d["water_saved_mm"],
        actual_energy_kwh     = d["actual_energy_kwh"],
        blind_energy_kwh      = d["blind_energy_kwh"],
        actual_cost_inr       = d["actual_cost_inr"],
        blind_cost_inr        = d["blind_cost_inr"],
        cost_saved_inr        = d["cost_saved_inr"],
        savings_pct_water     = d["savings_pct_water"],
        savings_pct_cost      = d["savings_pct_cost"],
        stress_days           = d.get("stress_days", 0),
        computed_at           = d["computed_at"],
    )


async def _upsert_savings_log(farm_id: UUID, result: dict, db: AsyncSession) -> None:
    """
    Upserts the savings_log row for (farm_id, season).
    Uses PostgreSQL ON CONFLICT DO UPDATE so concurrent requests don't race.
    """
    stmt = (
        pg_insert(SavingsLog)
        .values(
            farm_id                = farm_id,
            season                 = result["season"],
            water_saved_mm         = result["water_saved_mm"],
            cost_saved_inr         = result["cost_saved_inr"],
            actual_events          = result["actual_events"],
            blind_baseline_events  = result["blind_baseline_events"],
            stress_days            = result.get("stress_days", 0),
            computed_at            = datetime.now(timezone.utc),
        )
        .on_conflict_do_update(
            constraint="uq_savings_farm_season",
            set_={
                "water_saved_mm":        result["water_saved_mm"],
                "cost_saved_inr":        result["cost_saved_inr"],
                "actual_events":         result["actual_events"],
                "blind_baseline_events": result["blind_baseline_events"],
                "stress_days":           result.get("stress_days", 0),
                "computed_at":           datetime.now(timezone.utc),
            },
        )
    )
    await db.execute(stmt)
    await db.commit()


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get(
    "/farms/{farm_id}/savings",
    response_model=SavingsResponse,
    status_code=status.HTTP_200_OK,
    summary="Current-season water and cost savings vs blind farmer baseline",
)
async def get_savings(
    farm_id:      UUID,
    season:       Optional[str] = None,
    current_user: UserTokenData = Depends(get_current_user),
    db:           AsyncSession  = Depends(get_db),
) -> SavingsResponse:
    """
    Returns savings for the current season (or a specified season label
    like `Rabi-2025` or `Kharif-2025`).

    **Headline numbers** (shown prominently in the app):
    - `water_saved_mm`: litres per hectare the farmer saved vs traditional practice
    - `cost_saved_inr`: ₹ saved on pump electricity
    - `savings_pct_water` / `savings_pct_cost`: percentage savings

    **Baseline**: the simulated Blind farmer who irrigates every 10 days
    regardless of soil moisture or rain forecast.

    **Cache**: result is stored in savings_log. Re-computed on every
    confirmed irrigation event. Call `/savings/recompute` to force refresh.
    """
    farm = await _get_farm_or_404(farm_id, current_user.id, db)
    target_season = season or current_season()

    # Check cache first
    cached = await db.execute(
        select(SavingsLog).where(
            SavingsLog.farm_id == farm.id,
            SavingsLog.season  == target_season,
        )
    )
    cached_row = cached.scalar_one_or_none()

    if cached_row is not None:
        # Return cached row enriched with full engine details
        # (DB row only stores headline numbers; recompute for full breakdown)
        result = compute_savings(
            farm_id  = str(farm.id),
            district = farm.district or "Meerut",
            crop     = farm.crop,
            season   = target_season,
        )
    else:
        # Compute and cache
        result = compute_savings(
            farm_id  = str(farm.id),
            district = farm.district or "Meerut",
            crop     = farm.crop,
            season   = target_season,
        )
        await _upsert_savings_log(farm.id, result, db)

    return _engine_result_to_response(str(farm.id), result)


@router.get(
    "/farms/{farm_id}/savings/history",
    response_model=SavingsHistoryResponse,
    status_code=status.HTTP_200_OK,
    summary="Savings history across the last N seasons",
)
async def get_savings_history(
    farm_id:      UUID,
    n_seasons:    int          = 4,
    current_user: UserTokenData = Depends(get_current_user),
    db:           AsyncSession  = Depends(get_db),
) -> SavingsHistoryResponse:
    """
    Returns savings breakdowns for the last `n_seasons` seasons.
    `n_seasons=4` covers approximately 2 years (2 Rabi + 2 Kharif).

    Used to populate the savings history bar chart in the frontend.
    """
    farm = await _get_farm_or_404(farm_id, current_user.id, db)

    seasons = compute_all_seasons(
        farm_id   = str(farm.id),
        district  = farm.district or "Meerut",
        crop      = farm.crop,
        n_seasons = n_seasons,
    )

    return SavingsHistoryResponse(
        farm_id = str(farm.id),
        seasons = [_engine_result_to_response(str(farm.id), s) for s in seasons],
    )


@router.put(
    "/farms/{farm_id}/savings/recompute",
    response_model=SavingsResponse,
    status_code=status.HTTP_200_OK,
    summary="Force re-computation of savings for the current season",
)
async def recompute_savings(
    farm_id:      UUID,
    season:       Optional[str] = None,
    current_user: UserTokenData = Depends(get_current_user),
    db:           AsyncSession  = Depends(get_db),
) -> SavingsResponse:
    """
    Re-runs the savings engine and updates the savings_log table.
    Called automatically by the scheduler after each confirmed irrigation event.
    Can also be triggered manually from the frontend.
    """
    farm = await _get_farm_or_404(farm_id, current_user.id, db)
    target_season = season or current_season()

    _log.info("Recomputing savings: farm=%s season=%s", farm_id, target_season)

    result = compute_savings(
        farm_id  = str(farm.id),
        district = farm.district or "Meerut",
        crop     = farm.crop,
        season   = target_season,
    )
    await _upsert_savings_log(farm.id, result, db)

    return _engine_result_to_response(str(farm.id), result)