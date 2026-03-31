# builder.py
"""
features/builder.py
────────────────────
Full feature engineering pipeline.

Chains: raw weather → crop labels → ETo → soil balance → final CSV

Also handles conversion of ERA5 volumetric SM (m³/m³) → root-zone
depth (mm) for the real-soil dataset path.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import pandas as pd

from config.settings import agro, settings
from features import crop_calendar, eto, soil_balance
from utils.dates import read_csv

_log = settings.get_logger(__name__)

_BASE_COLS = [
    "date", "district", "crop",
    "temperature_C", "precip_mm", "wind_m_s", "solar_rad_MJ_m2",
    "ETo_mm", "real_soil_moisture_mm",
]

_GEE_COLS = ["VV", "VH", "delta_VV", "NDVI", "NDWI", "EVI", "TWI", "slope"]


# ── Simulated dataset (no ERA5 needed) ────────────────────────────────────────

def build_simulated(force: bool = False) -> Optional[pd.DataFrame]:
    """
    Builds the simulated training dataset from NASA POWER weather.
    Uses FAO-56 water balance to generate synthetic soil moisture labels.

    Does NOT require ERA5 .nc files.
    """
    out = settings.simulated_dataset
    if out.exists() and not force:
        _log.info("Simulated dataset exists. Loading. Pass force=True to recompute.")
        return read_csv(out)
    
    _log.info("=" * 60)
    _log.info("Building simulated dataset (crop + ETo + water balance)")
    _log.info("=" * 60)

    raw = settings.raw_weather_csv
    if not raw.exists():
        _log.error("Raw weather CSV not found. Run ingestion pipeline first.")
        return None

    df = pd.read_csv(raw)
    df["date"] = pd.to_datetime(df["date"], dayfirst=True)
    df = crop_calendar.assign(df)
    df = eto.calculate(df)
    df = soil_balance.simulate_all(df)

    final_cols = _BASE_COLS + ["generated_irrigated"]
    df_out     = df[[c for c in final_cols if c in df.columns]].dropna()
    df_out     = df_out.sort_values(["district", "date"]).reset_index(drop=True)

    out.parent.mkdir(parents=True, exist_ok=True)
    df_out.to_csv(out, index=False)
    _log.info(
        "Saved %d rows. SM: mean=%.1f min=%.1f max=%.1f mm",
        len(df_out),
        df_out["real_soil_moisture_mm"].mean(),
        df_out["real_soil_moisture_mm"].min(),
        df_out["real_soil_moisture_mm"].max(),
    )
    return df_out


# ── Real-soil dataset (ERA5 required) ─────────────────────────────────────────

def _volumetric_to_mm(df: pd.DataFrame) -> pd.DataFrame:
    """
    Converts ERA5 volumetric SM (m³/m³) to root-zone depth (mm).
        SM_mm = SM_m3m3 × root_depth_mm

    Root depths (from agronomy.yaml):
        Wheat : 900 mm
        Rice  : 300 mm
    """
    root_map = {
        "Wheat": agro.crops["Wheat"].root_depth_mm,
        "Rice":  agro.crops["Rice"].root_depth_mm,
        "None":  agro.crops["Wheat"].root_depth_mm,
    }
    df = df.copy()
    df["root_depth_mm"]          = df["crop"].map(root_map).fillna(agro.crops["Wheat"].root_depth_mm)
    df["real_soil_moisture_mm"]  = df["sm_rootzone_m3m3"] * df["root_depth_mm"]
    return df


def build_real_soil(
    raw_soil_df: pd.DataFrame,
    gee_features: Optional[dict] = None,
    force: bool = False,
) -> Optional[pd.DataFrame]:
    """
    Builds the real-soil dataset by merging:
        - NASA POWER weather
        - ERA5 root-zone SM (converted from m³/m³ to mm)
        - GEE satellite features (if available — adds VV, NDVI, TWI, etc.)

    Args:
        raw_soil_df  : Output of ingestion.pipeline.build_real_soil_dataset()
        gee_features : Dict district → DataFrame from ingestion.pipeline.build_gee_extracts()
        force        : Recompute even if output exists.

    Returns:
        Final DataFrame saved to data/dataset_real_soil.csv
    """
    out = settings.real_soil_dataset
    if out.exists() and not force:
        # Only skip if the file actually has real_soil_moisture_mm column
        existing = read_csv(out)
        if "real_soil_moisture_mm" in existing.columns:
            _log.info("Real soil dataset exists with correct columns. Loading.")
            return existing
        _log.warning("Real soil dataset missing real_soil_moisture_mm — reprocessing.")

    _log.info("=" * 60)
    _log.info("Building real-soil dataset")
    _log.info("=" * 60)

    df = raw_soil_df.copy()
    df = crop_calendar.assign(df)
    df = eto.calculate(df)
    df = _volumetric_to_mm(df)

    # Optionally merge GEE satellite features (centroid point, grid_idx==4)
    if gee_features:
        merged_dfs = []
        for district in df["district"].unique():
            d_df = df[df["district"] == district].copy()
            if district in gee_features:
                gee_df = gee_features[district]
                # Use centroid point only
                if "grid_idx" in gee_df.columns:
                    gee_df = gee_df[gee_df["grid_idx"] == 4]
                gee_cols  = [c for c in _GEE_COLS if c in gee_df.columns]
                gee_slice = gee_df[["date"] + gee_cols].copy()
                d_df      = pd.merge(d_df, gee_slice, on="date", how="left")
                _log.info("  [%s] Merged GEE features: %s", district, gee_cols)
            merged_dfs.append(d_df)
        df = pd.concat(merged_dfs, ignore_index=True)

    # Final column selection
    final_cols = _BASE_COLS + [c for c in _GEE_COLS if c in df.columns]
    df_out     = df[[c for c in final_cols if c in df.columns]].dropna(subset=["real_soil_moisture_mm"])
    df_out     = df_out.sort_values(["district", "date"]).reset_index(drop=True)

    out.parent.mkdir(parents=True, exist_ok=True)
    df_out.to_csv(out, index=False)
    _log.info(
        "Saved %d rows. SM: mean=%.1f min=%.1f max=%.1f mm",
        len(df_out),
        df_out["real_soil_moisture_mm"].mean(),
        df_out["real_soil_moisture_mm"].min(),
        df_out["real_soil_moisture_mm"].max(),
    )
    return df_out
