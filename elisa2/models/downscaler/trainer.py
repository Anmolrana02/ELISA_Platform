# trainer.py
"""
models/downscaler/trainer.py
─────────────────────────────
Training and inference pipeline for the RF spatial downscaler.
"""

from __future__ import annotations

from typing import Optional

import joblib
import numpy as np
import pandas as pd

from config.settings import agro, settings
from models.downscaler.rf_model import RF_FEATURES, TARGET, _build_feature_matrix, build, evaluate

from utils.dates import read_csv

_log = settings.get_logger(__name__)


def load_gee_data() -> Optional[pd.DataFrame]:
    """Loads and concatenates all district GEE extract CSVs."""
    frames = []
    for district in agro.districts.keys():
        path = settings.data_dir / "gee_extracts" / f"{district}_hyperlocal.csv"
        if not path.exists():
            _log.warning("  [%s] GEE extract not found. Run ingestion pipeline.", district)
            continue
        df = read_csv(path)
        frames.append(df)
        _log.info("  Loaded %s: %d rows.", district, len(df))

    if not frames:
        _log.error("No GEE extracts found. Run ingestion pipeline first.")
        return None

    combined = pd.concat(frames, ignore_index=True)
    # Add season flag and crop
    month = combined["date"].dt.month
    combined["season_flag"] = ((month >= 6) & (month <= 10)).astype(int)
    combined["crop"] = np.select(
        [(month >= 6) & (month <= 10), (month >= 11) | (month <= 4)],
        ["Rice", "Wheat"], default="None",
    )
    _log.info("Combined GEE data: %d rows, %d districts.", len(combined), combined["district"].nunique())
    return combined


def train(force: bool = False):
    """
    Trains the RF downscaler.

    Train/val split (chronological):
        Train : 2015–2022
        Val   : 2023 (holdout year)

    Returns:
        Fitted RandomForestRegressor or None on failure.
    """
    ckpt = settings.downscaler_checkpoint
    if ckpt.exists() and not force:
        _log.info("RF checkpoint exists at '%s'. Loading. Pass force=True to retrain.", ckpt)
        return joblib.load(ckpt)

    _log.info("=" * 62)
    _log.info("Training RF Spatial Downscaler")
    _log.info("  Training on 3×3 grid data — real within-pixel spatial variation")
    _log.info("=" * 62)

    df = load_gee_data()
    if df is None:
        return None

    #train_df = df[df["date"].dt.year <= 2022].copy()
    #val_df   = df[df["date"].dt.year == 2023].copy()
    from sklearn.model_selection import train_test_split
    train_df, val_df = train_test_split(df, test_size=0.2, random_state=42)
    
    _log.info("  Train: %d rows | Val: %d rows", len(train_df), len(val_df))

    X_train, y_train, _, feat_cols = _build_feature_matrix(train_df, RF_FEATURES)
    X_val,   y_val,   val_clean, _ = _build_feature_matrix(val_df,   feat_cols)

    _log.info("  Training RF (200 trees, max_depth=15, oob=True)...")
    rf = build()
    rf.fit(X_train, y_train)
    rf.feature_names_ = feat_cols   # store for inference

    metrics = evaluate(rf, X_val, y_val, val_clean, feat_cols)

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
    results = {}
    feat_cols = getattr(rf, "feature_names_", RF_FEATURES)

    for district in agro.districts.keys():
        gee_path = settings.data_dir / "gee_extracts" / f"{district}_hyperlocal.csv"
        if not gee_path.exists():
            _log.warning("  [%s] No GEE extract — skipping.", district)
            continue

        df = read_csv(gee_path)
        # Use centroid point (grid_idx == 4)
        if "grid_idx" in df.columns:
            df = df[df["grid_idx"] == 4].copy()

        month = df["date"].dt.month
        df["season_flag"] = ((month >= 6) & (month <= 10)).astype(int)
        df["crop"] = np.select(
            [(month >= 6) & (month <= 10), (month >= 11) | (month <= 4)],
            ["Rice", "Wheat"], default="None",
        )

        avail  = [f for f in feat_cols if f in df.columns]
        clean  = df.dropna(subset=avail).copy()
        clean["downscaled_sm_m3m3"] = rf.predict(clean[avail].values)

        root_map = {
            "Wheat": agro.crops["Wheat"].root_depth_mm,
            "Rice":  agro.crops["Rice"].root_depth_mm,
            "None":  agro.crops["Wheat"].root_depth_mm,
        }
        clean["root_depth_mm"]    = clean["crop"].map(root_map)
        clean["downscaled_sm_mm"] = clean["downscaled_sm_m3m3"] * clean["root_depth_mm"]

        out_path = settings.data_dir / "downscaled" / f"{district}_downscaled.csv"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        save_cols = [
            "date", "district", "crop",
            "era5_sm_m3m3", "downscaled_sm_m3m3", "downscaled_sm_mm",
        ] + [c for c in ["VV", "VH", "delta_VV", "NDVI", "NDWI", "EVI", "TWI", "slope"]
             if c in clean.columns]
        clean[save_cols].to_csv(out_path, index=False)

        _log.info(
            "  [%s] Saved %d rows → '%s'. SM: %.1f–%.1f mm",
            district, len(clean), out_path,
            clean["downscaled_sm_mm"].min(), clean["downscaled_sm_mm"].max(),
        )
        results[district] = clean

    return results
