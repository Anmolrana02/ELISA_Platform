# pipeline.py
"""
ingestion/pipeline.py
──────────────────────
Unified data ingestion pipeline.

Orchestrates:
    1. nasa_power    → raw weather CSV
    2. era5_loader   → 3-layer weighted root-zone SM from NetCDF
    3. gee_extractor → Sentinel SAR/optical + terrain (3×3 grid)

Entry point for the entire ingestion layer.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import pandas as pd

from config.settings import agro, settings
from ingestion import era5_loader, gee_extractor, nasa_power
from utils.dates import parse_dates, read_csv

_log = settings.get_logger(__name__)
_RAW_SOIL_MERGED = settings.data_dir / "raw_soil_merged.csv"


def build_raw_weather(force: bool = False) -> Optional[pd.DataFrame]:
    """Step 1 — NASA POWER weather data."""
    return nasa_power.fetch_all(force=force)


def build_real_soil_dataset(
    soil_dir: Optional[Path] = None,
    force: bool = False,
) -> Optional[pd.DataFrame]:
    """
    Step 2 — Merges NASA POWER weather + ERA5-Land 3-layer SM
    into the real-soil training dataset.

    Output columns:
        date, district, latitude, temperature_C, precip_mm, wind_m_s,
        solar_rad_MJ_m2, sm_rootzone_m3m3
    """
    out = _RAW_SOIL_MERGED
    if out.exists() and not force:
        _log.info("Raw soil merged file exists. Loading.")
        return read_csv(out)

    _log.info("=" * 60)
    _log.info("Building real-soil dataset")
    _log.info("=" * 60)

    # Weather
    weather = build_raw_weather(force=False)
    weather = parse_dates(weather)
    if weather is None:
        _log.error("Weather data unavailable. Run build_raw_weather first.")
        return None

    # ERA5 NetCDF
    ds = era5_loader.load(soil_dir)
    if ds is None:
        return None

    # Per-district extraction and merge
    merged_dfs = []
    for district, (lat, lon) in agro.districts.items():
        sm_df = era5_loader.extract_district_series(ds, district, lat, lon)
        if sm_df is None:
            continue
        w_df  = weather[weather["district"] == district].copy()
        m     = pd.merge(w_df, sm_df, on="date", how="inner")
        if m.empty:
            _log.warning("  [%s] Merge produced 0 rows — check ERA5 date coverage.", district)
            continue
        merged_dfs.append(m)
        _log.info("  [%s] Merged %d rows.", district, len(m))

    if not merged_dfs:
        _log.error("No districts merged. Aborting.")
        return None

    df = pd.concat(merged_dfs, ignore_index=True)
    df = df.sort_values(["district", "date"]).reset_index(drop=True)
    df.to_csv(out, index=False)
    _log.info("Saved %d rows to '%s'.", len(df), out)
    return df


def build_gee_extracts(district_filter: Optional[str] = None, force: bool = False) -> dict:
    """Step 3 — GEE extraction (3×3 grid per district)."""
    return gee_extractor.extract_all(district_filter=district_filter, force=force)
