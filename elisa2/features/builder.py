# builder.py
"""
features/builder.py
────────────────────
Full feature engineering pipeline.

Chains:
    raw weather → crop labels → ETo → soil balance → final CSV
    + ERA5 3-layer SM → root-zone depth conversion
    + GEE satellite features → interpolation → merge
    + Cyclic month features (sin/cos) for PatchTST
    + Integer crop feature for PatchTST
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from config.settings import agro, settings
from features import crop_calendar, eto, soil_balance
from features.interpolation import fill_all as fill_satellite_nulls
from utils.dates import read_csv

_log = settings.get_logger(__name__)

_BASE_COLS = [
    "date", "district", "crop", "crop_int",
    "temperature_C", "precip_mm", "wind_m_s", "solar_rad_MJ_m2",
    "ETo_mm", "real_soil_moisture_mm",
    "month_sin", "month_cos",   # cyclic month features for PatchTST
]

_GEE_COLS = ["VV", "VH", "VV_VH_ratio", "delta_VV", "NDVI", "NDWI", "EVI", "TWI", "slope"]


def _add_cyclic_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Adds sin/cos encoding of month for PatchTST.
    month_sin = sin(2π × month / 12)
    month_cos = cos(2π × month / 12)
    This gives the model explicit seasonality without relying solely
    on the DOY embedding.
    """
    df = df.copy()
    month = df["date"].dt.month
    df["month_sin"] = np.sin(2 * np.pi * month / 12)
    df["month_cos"] = np.cos(2 * np.pi * month / 12)
    return df


def _add_crop_int(df: pd.DataFrame) -> pd.DataFrame:
    """
    Adds integer crop encoding: Wheat=0, Rice=1, Sugarcane=2, None=-1.
    Used as a feature in PatchTST so the model can distinguish crop behaviour.
    """
    df = df.copy()
    df["crop_int"] = df["crop"].map(
        {"Wheat": 0, "Rice": 1, "Sugarcane": 2, "None": -1}
    ).fillna(-1).astype(int)
    return df


# ── Simulated dataset (no ERA5 needed) ────────────────────────────────────────

def build_simulated(force: bool = False) -> Optional[pd.DataFrame]:
    """
    Builds the simulated training dataset from NASA POWER weather.
    Uses FAO-56 water balance to generate synthetic soil moisture labels.
    Includes Sugarcane, cyclic month features, and crop integer encoding.
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
    df = _add_cyclic_features(df)
    df = _add_crop_int(df)

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
    _log.info("Crop distribution:\n%s", df_out["crop"].value_counts().to_string())
    return df_out


# ── Real-soil dataset (ERA5 required) ─────────────────────────────────────────

def _volumetric_to_mm(df: pd.DataFrame) -> pd.DataFrame:
    """
    Converts ERA5 volumetric SM (m³/m³) → root-zone depth (mm).
        SM_mm = SM_m3m3 × root_depth_mm

    Root depths (from agronomy.yaml):
        Wheat     : 900 mm
        Rice      : 300 mm
        Sugarcane : 1200 mm
        None      : 900 mm (Wheat fallback for transition months)
    """
    root_map = {
        "Wheat":     agro.crops["Wheat"].root_depth_mm,
        "Rice":      agro.crops["Rice"].root_depth_mm,
        "Sugarcane": agro.crops["Sugarcane"].root_depth_mm,
        "None":      agro.crops["Wheat"].root_depth_mm,
    }
    df = df.copy()
    df["root_depth_mm"] = (
        df["crop"].map(root_map)
        .fillna(agro.crops["Wheat"].root_depth_mm)   # fallback for any unknowns
    )
    df["real_soil_moisture_mm"] = df["sm_rootzone_m3m3"] * df["root_depth_mm"]
    return df


def build_real_soil(
    raw_soil_df:  pd.DataFrame,
    gee_features: Optional[dict] = None,
    force:        bool           = False,
) -> Optional[pd.DataFrame]:
    """
    Builds the real-soil dataset by merging:
        - NASA POWER weather
        - ERA5 3-layer root-zone SM (converted to mm per crop)
        - GEE satellite features (with ERA5-guided + SG interpolation)
        - Cyclic month features
        - Integer crop feature

    Args:
        raw_soil_df  : Output of ingestion.pipeline.build_real_soil_dataset()
        gee_features : Dict district → raw DataFrame from gee_extractor
        force        : Recompute even if output exists.
    """
    out = settings.real_soil_dataset
    if out.exists() and not force:
        existing = read_csv(out)
        if "real_soil_moisture_mm" in existing.columns:
            _log.info("Real soil dataset exists. Loading. Pass force=True to recompute.")
            return existing
        _log.warning("Real soil dataset missing real_soil_moisture_mm — reprocessing.")

    _log.info("=" * 60)
    _log.info("Building real-soil dataset")
    _log.info("=" * 60)

    df = raw_soil_df.copy()
    df = crop_calendar.assign(df)
    df = eto.calculate(df)
    df = _volumetric_to_mm(df)
    df = _add_cyclic_features(df)
    df = _add_crop_int(df)

    # Merge GEE satellite features
    if gee_features:
        merged_dfs = []
        for district in df["district"].unique():
            d_df = df[df["district"] == district].copy()

            if district in gee_features:
                gee_df = gee_features[district].copy()

                # Fill satellite nulls before merging
                _log.info("  [%s] Filling satellite nulls...", district)
                gee_df = fill_satellite_nulls(gee_df)

                # Use centroid grid point (grid_idx == 4) for the district-level merge
                if "grid_idx" in gee_df.columns:
                    gee_df = gee_df[gee_df["grid_idx"] == 4]

                gee_cols  = [c for c in _GEE_COLS if c in gee_df.columns]
                gee_slice = gee_df[["date"] + gee_cols].copy()
                d_df      = pd.merge(d_df, gee_slice, on="date", how="left")
                _log.info(
                    "  [%s] Merged GEE features: %s", district, gee_cols
                )

            merged_dfs.append(d_df)
        df = pd.concat(merged_dfs, ignore_index=True)

    # Final column selection — include all available GEE cols
    final_cols = _BASE_COLS + [c for c in _GEE_COLS if c in df.columns]
    df_out     = df[
        [c for c in final_cols if c in df.columns]
    ].dropna(subset=["real_soil_moisture_mm"])
    df_out = df_out.sort_values(["district", "date"]).reset_index(drop=True)

    out.parent.mkdir(parents=True, exist_ok=True)
    df_out.to_csv(out, index=False)
    _log.info(
        "Saved %d rows. SM: mean=%.1f min=%.1f max=%.1f mm",
        len(df_out),
        df_out["real_soil_moisture_mm"].mean(),
        df_out["real_soil_moisture_mm"].min(),
        df_out["real_soil_moisture_mm"].max(),
    )
    _log.info("Crop distribution:\n%s", df_out["crop"].value_counts().to_string())
    return df_out