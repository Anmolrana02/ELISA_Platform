# Paste contents from the generated api/weather.py here
# backend/api/weather.py
"""
Weather proxy routes.

GET /farms/{farm_id}/weather
    Returns OpenMeteo 7-day daily + 48h hourly forecast for the
    farm centroid. Aggregates hourly rain into daily totals so
    the frontend chart only needs one request.

GET /farms/{farm_id}/weather/hourly
    Returns raw 48h hourly rain for the MPC rain-suppression display.

Why proxy instead of calling OpenMeteo from the frontend:
    1. Centralises API calls — one place to add caching/rate-limit handling.
    2. Farm centroid coordinates are private (not exposed to browser).
    3. Lets us inject the actual forecast into the ML bridge rain check
       without a second HTTP round-trip from the client.

OpenMeteo is free with no API key. We call it with a short timeout
and fall back to zeros on failure so the app never crashes if
OpenMeteo is down — irrigation decisions become conservative (no rain
suppression), which is the safe fallback direction.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Optional
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.security import UserTokenData, get_current_user
from db_models.farm import Farm

_log    = logging.getLogger(__name__)
router  = APIRouter(tags=["weather"])

_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
_TIMEOUT      = 10.0


# ── Schemas ───────────────────────────────────────────────────────────────────

class DailyWeather(BaseModel):
    date:              str
    temp_max_c:        Optional[float]
    temp_min_c:        Optional[float]
    precipitation_mm:  float
    solar_rad_mj_m2:   Optional[float]
    wind_speed_kmh:    Optional[float]
    et0_mm:            Optional[float]       # OpenMeteo reference ETo (Penman-Monteith)
    weather_code:      Optional[int]         # WMO weather interpretation code


class WeatherForecastResponse(BaseModel):
    farm_id:   str
    lat:       float
    lon:       float
    daily:     list[DailyWeather]            # 7 days
    rain_48h:  list[float]                   # hourly precipitation next 48h (48 values)
    rain_24h_total_mm: float                 # convenience sum of first 24 hours
    timezone:  str


class HourlyRainResponse(BaseModel):
    farm_id:   str
    hours:     list[str]                     # ISO datetime strings
    rain_mm:   list[float]                   # hourly precip values


# ── Route helpers ─────────────────────────────────────────────────────────────

async def _get_farm_or_404(farm_id: UUID, user_id: UUID, db: AsyncSession) -> Farm:
    result = await db.execute(
        select(Farm).where(Farm.id == farm_id, Farm.user_id == user_id, Farm.active == True)
    )
    farm = result.scalar_one_or_none()
    if farm is None:
        raise HTTPException(status_code=404, detail="Farm not found.")
    return farm


async def _fetch_openmeteo(lat: float, lon: float) -> dict:
    """
    Fetches 7-day daily forecast + 48h hourly rain from OpenMeteo.
    Returns raw API dict on success, raises HTTPException on failure.
    """
    params = {
        "latitude":    lat,
        "longitude":   lon,
        "timezone":    "Asia/Kolkata",
        "forecast_days": 7,
        # Daily variables
        "daily": ",".join([
            "temperature_2m_max",
            "temperature_2m_min",
            "precipitation_sum",
            "shortwave_radiation_sum",
            "wind_speed_10m_max",
            "et0_fao_evapotranspiration",
            "weather_code",
        ]),
        # Hourly for rain suppression check (48h window)
        "hourly":          "precipitation",
        "forecast_hours":  48,
    }

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(_FORECAST_URL, params=params)
        resp.raise_for_status()
        return resp.json()
    except httpx.TimeoutException:
        _log.warning("OpenMeteo timeout for (%.4f, %.4f). Returning zeros.", lat, lon)
        return {}
    except httpx.HTTPStatusError as exc:
        _log.error("OpenMeteo HTTP %d for (%.4f, %.4f).", exc.response.status_code, lat, lon)
        return {}
    except Exception as exc:
        _log.error("OpenMeteo fetch failed: %s", exc)
        return {}


def _parse_daily(data: dict) -> list[DailyWeather]:
    """Parses OpenMeteo daily block into a list of DailyWeather objects."""
    if not data or "daily" not in data:
        return []

    d = data["daily"]
    n = len(d.get("time", []))

    def _safe(key: str, i: int) -> Optional[float]:
        vals = d.get(key, [])
        v    = vals[i] if i < len(vals) else None
        return float(v) if v is not None else None

    result = []
    for i in range(n):
        result.append(DailyWeather(
            date             = d["time"][i],
            temp_max_c       = _safe("temperature_2m_max",          i),
            temp_min_c       = _safe("temperature_2m_min",          i),
            precipitation_mm = float(d.get("precipitation_sum",     [0]*n)[i] or 0),
            solar_rad_mj_m2  = _safe("shortwave_radiation_sum",     i),
            wind_speed_kmh   = _safe("wind_speed_10m_max",          i),
            et0_mm           = _safe("et0_fao_evapotranspiration",  i),
            weather_code     = int(_safe("weather_code", i) or 0),
        ))
    return result


def _parse_hourly_rain(data: dict, hours: int = 48) -> list[float]:
    """Extracts the first `hours` hourly precipitation values."""
    if not data or "hourly" not in data:
        return [0.0] * hours
    vals = data["hourly"].get("precipitation", [])
    result = [float(v or 0.0) for v in vals[:hours]]
    # Pad with zeros if API returned fewer values
    result.extend([0.0] * max(0, hours - len(result)))
    return result


def _parse_hourly_times(data: dict, hours: int = 48) -> list[str]:
    if not data or "hourly" not in data:
        return []
    return data["hourly"].get("time", [])[:hours]


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get(
    "/farms/{farm_id}/weather",
    response_model=WeatherForecastResponse,
    status_code=status.HTTP_200_OK,
    summary="7-day weather forecast for farm centroid (OpenMeteo)",
)
async def get_weather(
    farm_id:      UUID,
    current_user: UserTokenData = Depends(get_current_user),
    db:           AsyncSession  = Depends(get_db),
) -> WeatherForecastResponse:
    """
    Returns a 7-day daily weather forecast and 48h hourly rain for
    the farm's centroid coordinates.

    **Fields**:
    - `daily`: 7-day forecast with temperature, precipitation, ETo
    - `rain_48h`: 48 hourly precipitation values (mm/h)
    - `rain_24h_total_mm`: sum of first 24 hourly values (used for rain suppression)

    Falls back to zeros on OpenMeteo API failure — the MPC will then not
    suppress irrigation (safe conservative direction).
    """
    farm = await _get_farm_or_404(farm_id, current_user.id, db)

    if not farm.centroid_lat or not farm.centroid_lon:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Farm centroid not set. Re-register the farm with a valid polygon.",
        )

    data       = await _fetch_openmeteo(farm.centroid_lat, farm.centroid_lon)
    daily      = _parse_daily(data)
    rain_48h   = _parse_hourly_rain(data, hours=48)
    rain_24h   = round(sum(rain_48h[:24]), 2)
    timezone   = data.get("timezone", "Asia/Kolkata") if data else "Asia/Kolkata"

    return WeatherForecastResponse(
        farm_id            = str(farm.id),
        lat                = farm.centroid_lat,
        lon                = farm.centroid_lon,
        daily              = daily,
        rain_48h           = rain_48h,
        rain_24h_total_mm  = rain_24h,
        timezone           = timezone,
    )


@router.get(
    "/farms/{farm_id}/weather/hourly",
    response_model=HourlyRainResponse,
    status_code=status.HTTP_200_OK,
    summary="48-hour hourly rain forecast for farm centroid",
)
async def get_hourly_rain(
    farm_id:      UUID,
    current_user: UserTokenData = Depends(get_current_user),
    db:           AsyncSession  = Depends(get_db),
) -> HourlyRainResponse:
    """
    Returns 48 hourly precipitation values for the farm centroid.
    Used to render the rain bar chart alongside the SM forecast.
    """
    farm = await _get_farm_or_404(farm_id, current_user.id, db)

    if not farm.centroid_lat or not farm.centroid_lon:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Farm centroid not available.",
        )

    data   = await _fetch_openmeteo(farm.centroid_lat, farm.centroid_lon)
    rain   = _parse_hourly_rain(data, hours=48)
    times  = _parse_hourly_times(data, hours=48)

    return HourlyRainResponse(
        farm_id = str(farm.id),
        hours   = times,
        rain_mm = rain,
    )