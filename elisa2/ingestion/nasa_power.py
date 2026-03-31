# nasa_power.py
"""
ingestion/nasa_power.py
───────────────────────
Fetches daily meteorological data for all study districts
from the NASA POWER API (free, no key required).

Parameters fetched:
    T2M           → 2m air temperature (°C)
    PRECTOTCORR   → bias-corrected precipitation (mm/day)
    WS2M          → wind speed at 2m (m/s)
    ALLSKY_SFC_SW_DWN → surface downwelling shortwave radiation (MJ/m²/day)

Output columns:
    date, district, latitude, temperature_C, precip_mm, wind_m_s, solar_rad_MJ_m2
"""

from __future__ import annotations

import time
from typing import Optional

import numpy as np
import pandas as pd
import requests

from config.settings import agro, settings
from utils.dates import read_csv

_log = settings.get_logger(__name__)

_PARAMS   = "T2M,PRECTOTCORR,WS2M,ALLSKY_SFC_SW_DWN"
_SENTINEL = -999.0   # NASA POWER missing-data placeholder


# ── Single district fetch ─────────────────────────────────────────────────────

def fetch_district(
    district: str,
    lat: float,
    lon: float,
    start: str,
    end: str,
    retries: int = 3,
    backoff_s: float = 5.0,
) -> Optional[pd.DataFrame]:
    """
    Fetches daily weather for one district.

    Returns a DataFrame or None on complete failure.
    -999 missing values are replaced via linear interpolation.
    """
    params = {
        "parameters": _PARAMS,
        "community":  "AG",
        "longitude":  lon,
        "latitude":   lat,
        "start":      start.replace("-", ""),
        "end":        end.replace("-", ""),
        "format":     "JSON",
    }
    _log.info("  Fetching %-15s (%.2f, %.2f)...", district, lat, lon)

    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(
                settings.nasa_power_url, params=params, timeout=60
            )
            resp.raise_for_status()
            data = resp.json()["properties"]["parameter"]

            if not isinstance(data.get("T2M"), dict) or not data["T2M"]:
                _log.warning("  [%s] No valid T2M data in response.", district)
                return None

            df = pd.DataFrame({
                "date":             pd.to_datetime(list(data["T2M"].keys()), format="%Y%m%d"),
                "temperature_C":    list(data["T2M"].values()),
                "precip_mm":        list(data["PRECTOTCORR"].values()),
                "wind_m_s":         list(data["WS2M"].values()),
                "solar_rad_MJ_m2":  list(data["ALLSKY_SFC_SW_DWN"].values()),
            })
            df["district"] = district
            df["latitude"]  = lat

            n_bad = (df[["temperature_C", "precip_mm", "wind_m_s", "solar_rad_MJ_m2"]] == _SENTINEL).sum().sum()
            df.replace(_SENTINEL, np.nan, inplace=True)
            df.interpolate(method="linear", inplace=True)
            if n_bad:
                _log.debug("  [%s] Replaced %d sentinel values.", district, n_bad)

            _log.info("  [%s] OK — %d rows.", district, len(df))
            return df

        except requests.exceptions.Timeout:
            _log.warning("  [%s] Attempt %d/%d timed out.", district, attempt, retries)
        except requests.exceptions.HTTPError as exc:
            _log.error("  [%s] HTTP %s.", district, exc.response.status_code)
            return None
        except requests.exceptions.RequestException as exc:
            _log.warning("  [%s] Attempt %d/%d — %s", district, attempt, retries, exc)
        except (KeyError, ValueError) as exc:
            _log.error("  [%s] Unexpected JSON: %s", district, exc)
            return None

        if attempt < retries:
            _log.info("  Retrying in %.0f s...", backoff_s)
            time.sleep(backoff_s)

    _log.error("  [%s] All %d attempts failed.", district, retries)
    return None


# ── All districts ─────────────────────────────────────────────────────────────

def fetch_all(force: bool = False) -> Optional[pd.DataFrame]:
    """
    Fetches weather for every district configured in agronomy.yaml.

    Args:
        force: Re-fetch even if output CSV already exists.

    Returns:
        Combined DataFrame or None on complete failure.
    """
    out = settings.raw_weather_csv
    if out.exists() and not force:
        _log.info("Raw weather exists at '%s'. Loading. Pass force=True to re-fetch.", out)
        return read_csv(out)

    _log.info("=" * 60)
    _log.info("NASA POWER fetch | %s → %s", settings.nasa_start_date, settings.nasa_end_date)
    _log.info("Districts: %s", agro.districts.keys())
    _log.info("=" * 60)

    frames = []
    for district, (lat, lon) in agro.districts.items():
        df = fetch_district(
            district=district, lat=lat, lon=lon,
            start=settings.nasa_start_date,
            end=settings.nasa_end_date,
        )
        if df is not None:
            frames.append(df)

    if not frames:
        _log.error("No data fetched for any district.")
        return None

    combined = (
        pd.concat(frames, ignore_index=True)
        .sort_values(["district", "date"])
        .reset_index(drop=True)
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(out, index=False)
    _log.info("Saved %d rows to '%s'.", len(combined), out)
    return combined
