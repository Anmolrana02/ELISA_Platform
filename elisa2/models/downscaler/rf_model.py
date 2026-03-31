# rf_model.py
"""
models/downscaler/rf_model.py
──────────────────────────────
Random Forest spatial downscaler.

Input  : ERA5 coarse SM + Sentinel SAR/optical + terrain features
Output : Farm-level SM prediction (same ERA5 pixel, but at 100m resolution)

The 3×3 grid design (from gee_extractor.py) is why this works:
    Each of the 9 points in the pixel has:
        - The SAME era5_sm_m3m3  (ERA5 pixel is spatially uniform)
        - DIFFERENT VV, NDVI, TWI, slope (real spatial variation)
    The RF learns: given these satellite/terrain values, what is the
    actual SM at THIS specific location within the ERA5 pixel?

Primary metric: Decision Accuracy (%)
    ±20mm absolute error is expected and acceptable.
    What matters is: does the downscaled SM give the same
    irrigation decision as if we had ground-truth SM?
"""

from __future__ import annotations

from typing import List, Optional, Tuple

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

from config.settings import agro, settings

_log = settings.get_logger(__name__)

# Ordered by expected importance (era5 coarse SM is always the dominant predictor)
RF_FEATURES = [
    #"era5_sm_m3m3",   # Coarse ERA5 SM — primary predictor
    "delta_VV",       # SAR deviation from dry baseline — key soil moisture proxy
    "VH",             # Cross-pol backscatter — vegetation volume scattering
    "VV_VH_ratio",    # Polarisation ratio — crop/soil structure
    "NDVI",           # Vegetation greenness
    "NDWI",           # Canopy water content
    "EVI",            # Enhanced vegetation index
    "TWI",            # Topographic wetness (static)
    "slope",          # Terrain slope (static)
    "season_flag",    # 0=Rabi, 1=Kharif
]

TARGET = "era5_sm_m3m3"   # Training target = ERA5 coarse SM
                           # (RF learns spatial correction from centroid)


def _build_feature_matrix(
    df:           pd.DataFrame,
    feature_cols: List[str],
) -> Tuple[np.ndarray, np.ndarray, pd.DataFrame, List[str]]:
    """Builds X, y arrays after dropping NaN rows."""
    available = [f for f in feature_cols if f in df.columns]
    missing   = [f for f in feature_cols if f not in df.columns]
    if missing:
        _log.warning("  RF features missing (skipped): %s", missing)

    clean = df.dropna(subset=available + [TARGET]).copy()
    _log.info("  Feature matrix: %d rows × %d features.", len(clean), len(available))
    return clean[available].values, clean[TARGET].values, clean, available


def build(n_estimators: int = 200, max_depth: int = 15) -> RandomForestRegressor:
    """Constructs an unfitted RF with recommended hyperparameters."""
    return RandomForestRegressor(
        n_estimators  = n_estimators,
        max_depth     = max_depth,
        min_samples_leaf = 5,
        n_jobs        = -1,
        random_state  = 42,
        oob_score     = True,
    )


def evaluate(
    rf:         RandomForestRegressor,
    X_val:      np.ndarray,
    y_val:      np.ndarray,
    val_df:     pd.DataFrame,
    feat_cols:  List[str],
) -> dict:
    """
    Computes validation metrics including decision accuracy.

    Decision accuracy: fraction of days where the downscaled SM gives
    the same irrigation decision (irrigate/skip) as the ERA5 truth.
    This is the primary metric for an irrigation system.
    """
    y_pred = rf.predict(X_val)

    rmse = float(np.sqrt(mean_squared_error(y_val, y_pred)))
    mae  = float(mean_absolute_error(y_val, y_pred))
    r2   = float(r2_score(y_val, y_pred))

    # Decision accuracy
    wheat_trig = agro.crops["Wheat"].trigger_mm / agro.crops["Wheat"].root_depth_mm
    rice_trig  = agro.crops["Rice"].trigger_mm  / agro.crops["Rice"].root_depth_mm
    crop_col   = val_df["crop"].values if "crop" in val_df.columns else None
    triggers   = (
        np.where(crop_col == "Rice", rice_trig, wheat_trig)
        if crop_col is not None else wheat_trig
    )
    true_dec = (y_val  < triggers).astype(int)
    pred_dec = (y_pred < triggers).astype(int)
    dec_acc  = float((true_dec == pred_dec).mean() * 100)

    # Feature importances
    importances = pd.Series(
        rf.feature_importances_, index=feat_cols
    ).sort_values(ascending=False)

    sep = "-" * 58
    _log.info(sep)
    _log.info("  RF DOWNSCALER — Validation Results (2023 holdout)")
    _log.info(sep)
    _log.info("  RMSE             : %.4f m³/m³  (≈ %.1f mm)", rmse, rmse * agro.crops["Wheat"].root_depth_mm)
    _log.info("  MAE              : %.4f m³/m³  (≈ %.1f mm)", mae,  mae  * agro.crops["Wheat"].root_depth_mm)
    _log.info("  R²               : %.4f", r2)
    _log.info("  OOB R²           : %.4f", rf.oob_score_)
    _log.info("  Decision accuracy: %.1f%%  ← primary metric", dec_acc)
    _log.info(sep)
    _log.info("  Feature importances:")
    for feat, imp in importances.items():
        bar = "█" * int(imp * 40)
        _log.info("    %-18s %s %.3f", feat, bar, imp)
    _log.info(sep)

    return {"rmse": rmse, "mae": mae, "r2": r2, "decision_accuracy": dec_acc,
            "oob_r2": rf.oob_score_, "importances": importances.to_dict()}


def predict_farm_sm(
    rf:       RandomForestRegressor,
    lat:      float,
    lon:      float,
    district: str,
    as_of:    str,
) -> Optional[float]:
    """
    Predicts downscaled SM (mm) for an arbitrary farm coordinate.
    Finds the nearest GEE grid point and extracts its features.

    Returns SM in mm, or None if data unavailable.
    """
    gee_path = settings.data_dir / "gee_extracts" / f"{district}_hyperlocal.csv"
    if not gee_path.exists():
        _log.warning("GEE extract not found for '%s'.", district)
        return None

    gee_df = pd.read_csv(gee_path, parse_dates=["date"])
    gee_df["_dist"] = ((gee_df["grid_lat"] - lat) ** 2 + (gee_df["grid_lon"] - lon) ** 2) ** 0.5
    nearest_idx = gee_df["grid_idx"].iloc[gee_df["_dist"].argmin()]

    point_df = gee_df[
        (gee_df["grid_idx"] == nearest_idx) &
        (gee_df["date"] <= pd.Timestamp(as_of))
    ]
    if point_df.empty:
        return None

    latest = point_df.iloc[-1].copy()
    mo     = latest["date"].month
    latest["season_flag"] = int(6 <= mo <= 10)

    feat_cols = getattr(rf, "feature_names_", RF_FEATURES)
    row = {f: float(latest.get(f, 0.0)) for f in feat_cols}
    X   = np.array([[row[f] for f in feat_cols]])

    try:
        sm_m3m3 = float(rf.predict(X)[0])
        crop    = "Wheat" if (mo <= 4 or mo >= 11) else "Rice"
        root_d  = agro.crops[crop].root_depth_mm
        sm_mm   = sm_m3m3 * root_d
        return round(sm_mm, 1)
    except Exception as exc:
        _log.error("RF prediction failed: %s", exc)
        return None
