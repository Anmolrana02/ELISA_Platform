# trainer.py
"""
models/downscaler/trainer.py
─────────────────────────────
Training and inference pipeline for the RF spatial downscaler.

Changes from v1:
    - Chronological split: train ≤2022, val=2023 (was random split — leaked future)
    - season_flag: 3-class (0=Rabi, 1=Kharif, 2=Sugarcane)
    - Sugarcane in crop assignment
    - Satellite nulls filled via interpolation.fill_all() before training
    - apply_to_all_districts uses Sugarcane root depth
"""

from __future__ import annotations
from typing import Optional

import joblib
import numpy as np
import pandas as pd

from config.settings import agro, settings
from features.interpolation import fill_all as fill_satellite_nulls
from models.downscaler.rf_model import RF_FEATURES, TARGET, _build_feature_matrix, build, evaluate
from utils.dates import read_csv

_log = settings.get_logger(__name__)


def _season_flag(month_series: pd.Series) -> pd.Series:
    """
    3-class season flag:
        0 = Rabi      (Nov–Apr, Wheat dominant)
        1 = Kharif    (Jun–Oct, Rice dominant)
        2 = Sugarcane (May, year-round ratoon — used when Sugarcane is dominant)
    Since all 5 districts have Sugarcane year-round, we use:
        May → 2 (Sugarcane transition)
        Jun–Oct → 1 (Kharif / Sugarcane high-growth)
        Nov–Apr → 0 (Rabi / Sugarcane maturation)
    For the RF this gives better signal than a binary Kharif/Rabi flag.
    """
    return np.select(
        [(month_series == 5),
         (month_series >= 6) & (month_series <= 10)],
        [2, 1],
        default=0,
    ).astype(int)


def load_gee_data() -> Optional[pd.DataFrame]:
    """
    Loads all 5 district GEE extract CSVs, applies satellite null-filling,
    adds season_flag and crop columns.
    """
    frames = []
    for district in agro.districts.keys():
        path = settings.data_dir / "gee_extracts" / f"{district}_hyperlocal.csv"
        if not path.exists():
            _log.warning("  [%s] GEE extract not found. Run ingestion pipeline.", district)
            continue

        df = read_csv(path)

        # Fill satellite nulls before training
        _log.info("  [%s] Filling satellite nulls...", district)
        df = fill_satellite_nulls(df)

        frames.append(df)
        _log.info("  Loaded %s: %d rows.", district, len(df))

    if not frames:
        _log.error("No GEE extracts found. Run ingestion pipeline first.")
        return None

    combined = pd.concat(frames, ignore_index=True)

    # 3-class season flag
    month = combined["date"].dt.month
    combined["season_flag"] = _season_flag(month)

    # Crop label — Sugarcane year-round all districts
    combined["crop"] = "Sugarcane"

    _log.info(
        "Combined GEE data: %d rows, %d districts.",
        len(combined), combined["district"].nunique(),
    )
    return combined


def train(force: bool = False):
    """
    Trains the RF downscaler with chronological split.

    Chronological split:
        Train : date.year ≤ 2022
        Val   : date.year == 2023  (holdout year)

    Returns:
        Fitted RandomForestRegressor or None on failure.
    """
    ckpt = settings.downscaler_checkpoint
    if ckpt.exists() and not force:
        _log.info("RF checkpoint exists. Loading. Pass force=True to retrain.")
        return joblib.load(ckpt)

    _log.info("=" * 62)
    _log.info("Training RF Spatial Downscaler (chronological split)")
    _log.info("=" * 62)

    df = load_gee_data()
    if df is None:
        return None

    # Chronological split — prevents future data leakage
    train_df = df[df["date"].dt.year <= 2022].copy()
    val_df   = df[df["date"].dt.year == 2023].copy()
    _log.info("  Train: %d rows (≤2022) | Val: %d rows (2023)", len(train_df), len(val_df))

    if len(val_df) == 0:
        _log.warning("No 2023 data — falling back to last year of available data for val.")
        last_yr  = df["date"].dt.year.max()
        train_df = df[df["date"].dt.year < last_yr].copy()
        val_df   = df[df["date"].dt.year == last_yr].copy()
        _log.info("  Fallback: train=%d rows, val=%d rows", len(train_df), len(val_df))

    X_train, y_train, _, feat_cols = _build_feature_matrix(train_df, RF_FEATURES)
    X_val,   y_val,   val_clean, _ = _build_feature_matrix(val_df,   feat_cols)

    _log.info("  Training RF (200 trees, max_depth=15, oob=True)...")
    rf = build()
    rf.fit(X_train, y_train)
    rf.feature_names_ = feat_cols

    evaluate(rf, X_val, y_val, val_clean, feat_cols)

    ckpt.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(rf, ckpt)
    _log.info("RF model saved to '%s'.", ckpt)
    return rf


def apply_to_all_districts(rf=None):
    """
    Applies the trained RF to every district's GEE centroid data.
    Saves downscaled_sm_mm to data/downscaled/{district}_downscaled.csv.
    """
    if rf is None:
        ckpt = settings.downscaler_checkpoint
        if not ckpt.exists():
            _log.error("No RF checkpoint found. Run train() first.")
            return {}
        rf = joblib.load(ckpt)

    _log.info("Applying RF downscaler to all districts...")
    results   = {}
    feat_cols = getattr(rf, "feature_names_", RF_FEATURES)

    for district in agro.districts.keys():
        gee_path = settings.data_dir / "gee_extracts" / f"{district}_hyperlocal.csv"
        if not gee_path.exists():
            _log.warning("  [%s] No GEE extract — skipping.", district)
            continue

        df = read_csv(gee_path)

        # Fill nulls
        df = fill_satellite_nulls(df)

        # Use centroid point (grid_idx == 4) for district-level output
        if "grid_idx" in df.columns:
            df = df[df["grid_idx"] == 4].copy()

        month = df["date"].dt.month
        df["season_flag"] = _season_flag(month)
        df["crop"]        = "Sugarcane"

        avail  = [f for f in feat_cols if f in df.columns]
        clean  = df.dropna(subset=avail).copy()
        clean["downscaled_sm_m3m3"] = rf.predict(clean[avail].values)

        # Sugarcane root depth for all districts
        root_d = agro.crops["Sugarcane"].root_depth_mm
        clean["root_depth_mm"]    = root_d
        clean["downscaled_sm_mm"] = clean["downscaled_sm_m3m3"] * root_d

        out_path = settings.data_dir / "downscaled" / f"{district}_downscaled.csv"
        out_path.parent.mkdir(parents=True, exist_ok=True)

        save_cols = [
            "date", "district", "crop",
            "era5_sm_m3m3", "downscaled_sm_m3m3", "downscaled_sm_mm",
        ] + [c for c in ["VV", "VH", "delta_VV", "NDVI", "NDWI", "EVI", "TWI", "slope"]
             if c in clean.columns]
        clean[save_cols].to_csv(out_path, index=False)

        _log.info(
            "  [%s] %d rows → SM: %.1f–%.1f mm",
            district, len(clean),
            clean["downscaled_sm_mm"].min(),
            clean["downscaled_sm_mm"].max(),
        )
        results[district] = clean

    return results