# state_manager.py
"""
decision/state_manager.py
──────────────────────────
Irrigation feedback loop — closes the gap between what the farmer
DID today and what the model PREDICTS tomorrow.

Problem solved:
    If a farmer irrigates (+70 mm) on Jan 1, the ERA5/satellite data
    won't reflect this for days. Without this module, PatchTST sees
    the same dry SM on Jan 2 and recommends irrigating again — waste.

    With this module:
        Jan 1 evening: farmer logs "I irrigated" in dashboard
        Jan 1 night:   run_nightly_update() runs physics correction
                       SM_new = SM_old + 70mm + rain - ETo = 214 mm
        Jan 2 morning: inject_into_window() puts 214mm in the last
                       row before building the 30-day input sequence
        Jan 2 result:  model says "no irrigation needed" ✓

Storage:
    Events  : data/farm_states/{farm_id}_events.csv
    State   : data/farm_states/{farm_id}_state.json
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import requests

from config.settings import agro, settings

from utils.dates import read_csv

_log     = settings.get_logger(__name__)
_DIR     = settings.data_dir / "farm_states"
_TARGET  = "real_soil_moisture_mm"


# ── Event logging ─────────────────────────────────────────────────────────────

def log_irrigation(farm_id: str, on_date: date, mm: float) -> None:
    """
    Records that a farmer irrigated on a specific date.
    Called from dashboard when the farmer clicks "I irrigated today".
    """
    _DIR.mkdir(parents=True, exist_ok=True)
    path    = _DIR / f"{farm_id}_events.csv"
    new_row = pd.DataFrame([{
        "date":          on_date.isoformat(),
        "irrigation_mm": mm,
        "source":        "farmer_confirmed",
    }])
    if path.exists():
        pd.concat([read_csv(path), new_row], ignore_index=True).to_csv(path, index=False)
    else:
        new_row.to_csv(path, index=False)
    _log.info("Logged %.1f mm irrigation for '%s' on %s.", mm, farm_id, on_date)


def get_irrigation_on(farm_id: str, on_date: date) -> float:
    """Returns total irrigation logged for farm_id on on_date (mm)."""
    path = _DIR / f"{farm_id}_events.csv"
    if not path.exists():
        return 0.0
    df = read_csv(path)
    return float(df[df["date"].dt.date == on_date]["irrigation_mm"].sum())


def get_irrigation_history(farm_id: str, days: int = 30) -> pd.DataFrame:
    """Returns last N days of irrigation events for a farm."""
    path = _DIR / f"{farm_id}_events.csv"
    if not path.exists():
        return pd.DataFrame(columns=["date", "irrigation_mm", "source"])
    df = read_csv(path)
    cutoff = pd.Timestamp.today() - pd.Timedelta(days=days)
    return df[df["date"] >= cutoff].sort_values("date", ascending=False).reset_index(drop=True)


# ── Actual precipitation ──────────────────────────────────────────────────────

def fetch_actual_precip(district: str, on_date: date) -> float:
    """
    Fetches observed precipitation for on_date from OpenMeteo archive.
    Falls back to stored NASA POWER value if API is unreachable.
    """
    lat, lon = agro.districts[district]
    try:
        resp = requests.get(
            settings.openmeteo_archive_url,
            params={
                "latitude":   lat,
                "longitude":  lon,
                "start_date": on_date.isoformat(),
                "end_date":   on_date.isoformat(),
                "daily":      "precipitation_sum",
                "timezone":   "Asia/Kolkata",
            },
            timeout=8,
        )
        resp.raise_for_status()
        return float(resp.json()["daily"]["precipitation_sum"][0] or 0.0)
    except requests.exceptions.ConnectionError:
        _log.warning("OpenMeteo archive unreachable. Falling back to NASA POWER value.")
    except Exception as exc:
        _log.warning("Precip fetch failed (%s). Using stored NASA value.", exc)

    # Fallback
    try:
        df  = read_csv(settings.raw_weather_csv)
        row = df[(df["district"] == district) & (df["date"] == pd.Timestamp(on_date))]
        if not row.empty:
            return float(row["precip_mm"].iloc[0])
    except Exception:
        pass
    return 0.0


# ── Nightly state update ──────────────────────────────────────────────────────

def update_state(farm_id: str, district: str, on_date: date) -> dict:
    """
    FAO-56 water balance update for one farm on one day.

        SM_new = SM_yesterday + actual_precip + irrigation_logged - ETo

    Clamps result to [PWP, FC] for the active crop.
    Saves state JSON to data/farm_states/{farm_id}_state.json.

    Returns:
        State dict with sm_mm, date, components.
    """
    state_path = _DIR / f"{farm_id}_state.json"
    _DIR.mkdir(parents=True, exist_ok=True)

    # Load yesterday's SM (or seed from ERA5 on first run)
    if state_path.exists():
        with open(state_path) as f:
            prev = json.load(f)
        sm_yesterday = float(prev["sm_mm"])
    else:
        _log.info("No prior state for '%s'. Seeding from ERA5 dataset.", farm_id)
        try:
            df = read_csv(settings.real_soil_dataset)
            recent = df[
                (df["district"] == district) &
                (df["date"] <= pd.Timestamp(on_date))
            ]
            sm_yesterday = float(recent.iloc[-1][_TARGET]) if not recent.empty \
                           else agro.crops["Wheat"].fc_mm
        except Exception:
            sm_yesterday = agro.crops["Wheat"].fc_mm

    # Components
    irrigation   = get_irrigation_on(farm_id, on_date)
    actual_precip = fetch_actual_precip(district, on_date)

    try:
        df  = read_csv(settings.real_soil_dataset)
        row = df[(df["district"] == district) & (df["date"] == pd.Timestamp(on_date))]
        eto  = float(row["ETo_mm"].iloc[0])  if not row.empty else 4.0
        crop = str(row["crop"].iloc[0])      if not row.empty else "Wheat"
    except Exception:
        eto  = 4.0
        crop = "Wheat"

    # FAO-56 balance
    crop_profile = agro.get_crop(crop)
    sm_new       = sm_yesterday + actual_precip + irrigation - eto
    sm_new       = float(np.clip(sm_new, crop_profile.pwp_mm, crop_profile.fc_mm))

    state = {
        "farm_id":             farm_id,
        "district":            district,
        "date":                on_date.isoformat(),
        "sm_mm":               sm_new,
        "sm_yesterday_mm":     sm_yesterday,
        "irrigation_mm":       irrigation,
        "precip_mm":           actual_precip,
        "eto_mm":              eto,
        "crop":                crop,
    }
    with open(state_path, "w") as f:
        json.dump(state, f, indent=2)

    _log.info(
        "[%s] %s: SM %.1f→%.1f mm  (+%.1f irr, +%.1f rain, -%.1f ETo)",
        farm_id, on_date, sm_yesterday, sm_new, irrigation, actual_precip, eto,
    )
    return state


def get_state(farm_id: str) -> Optional[dict]:
    """Returns the most recently saved state dict, or None."""
    path = _DIR / f"{farm_id}_state.json"
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


# ── PatchTST input injection ───────────────────────────────────────────────────

def inject_into_window(
    farm_id:    str,
    district:   str,
    window_df:  pd.DataFrame,
) -> pd.DataFrame:
    """
    Replaces the most recent row's SM with the physics-corrected value.

    Called inside models/patchtst/trainer.py :: predict()
    BEFORE building the 30-day input sequence.

    This is the single injection point that makes irrigation on Jan 1
    visible to Jan 2's prediction.

    Returns window_df unchanged if no saved state exists (graceful fallback).
    """
    state = get_state(farm_id)
    if state is None:
        return window_df

    state_date = pd.Timestamp(state["date"])
    mask = (window_df["district"] == district) & (window_df["date"] == state_date)

    if mask.any():
        window_df = window_df.copy()
        old_sm    = float(window_df.loc[mask, _TARGET].iloc[0])
        new_sm    = float(state["sm_mm"])
        window_df.loc[mask, _TARGET] = new_sm
        _log.info(
            "Feedback injected for '%s': SM %.1f→%.1f mm on %s",
            farm_id, old_sm, new_sm, state_date.date(),
        )
    return window_df


# ── Nightly batch runner ───────────────────────────────────────────────────────

def run_nightly_update(on_date: Optional[date] = None) -> None:
    """
    Updates state for every registered farm.
    Schedule this as a cron job at 23:55 or call from pipelines/run.py.
    """
    from farm.manager import list_farms
    on_date = on_date or date.today()
    farms   = list_farms()

    if not farms:
        _log.info("No farms registered. Nightly update skipped.")
        return

    _log.info("Nightly state update for %d farms on %s.", len(farms), on_date)
    for farm in farms:
        try:
            s = update_state(
                farm_id  = farm["farm_id"],
                district = farm["nearest_district"],
                on_date  = on_date,
            )
            _log.info("  [%s] %s: SM=%.1f mm", farm["farm_id"], farm["name"], s["sm_mm"])
        except Exception as exc:
            _log.error("  [%s] Update failed: %s", farm["farm_id"], exc)
