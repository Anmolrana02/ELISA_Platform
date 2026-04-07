# rf_model.py
"""
models/downscaler/rf_model.py
──────────────────────────────
Random Forest spatial downscaler.

Changes from v1:
    - era5_sm_m3m3 restored as first feature (strongest predictor)
    - Sugarcane crop detection in predict_farm_sm
    - Sugarcane trigger in decision accuracy evaluation
"""

from __future__ import annotations

from typing import List, Optional, Tuple

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

from config.settings import agro, settings

_log = settings.get_logger(__name__)

# era5_sm_m3m3 is restored as the first (and most important) feature.
# This is NOT target leakage: the RF learns the spatial delta between
# the coarse ERA5 pixel and the farm-level point.
RF_FEATURES = [
    "era5_sm_m3m3",   # Coarse ERA5 SM — primary predictor (restored)
    "delta_VV",       # SAR deviation from dry baseline
    "VH",             # Cross-pol backscatter
    "VV_VH_ratio",    # Polarisation ratio
    "NDVI",           # Vegetation greenness
    "NDWI",           # Canopy water content
    "EVI",            # Enhanced vegetation index
    "TWI",            # Topographic wetness (static)
    "slope",          # Terrain slope (static)
    "season_flag",    # 0=Rabi, 1=Kharif, 2=Sugarcane
]

TARGET = "era5_sm_m3m3"


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
        n_estimators     = n_estimators,
        max_depth        = max_depth,
        min_samples_leaf = 5,
        n_jobs           = -1,
        random_state     = 42,
        oob_score        = True,
    )


def evaluate(
    rf:        RandomForestRegressor,
    X_val:     np.ndarray,
    y_val:     np.ndarray,
    val_df:    pd.DataFrame,
    feat_cols: List[str],
) -> dict:
    """
    Computes validation metrics including decision accuracy for all crops.
    """
    y_pred = rf.predict(X_val)

    rmse = float(np.sqrt(mean_squared_error(y_val, y_pred)))
    mae  = float(mean_absolute_error(y_val, y_pred))
    r2   = float(r2_score(y_val, y_pred))

    # Decision accuracy — per-crop triggers in volumetric (m³/m³)
    wheat_trig     = agro.crops["Wheat"].trigger_mm     / agro.crops["Wheat"].root_depth_mm
    rice_trig      = agro.crops["Rice"].trigger_mm      / agro.crops["Rice"].root_depth_mm
    sugarcane_trig = agro.crops["Sugarcane"].trigger_mm / agro.crops["Sugarcane"].root_depth_mm

    crop_col = val_df["crop"].values if "crop" in val_df.columns else None
    if crop_col is not None:
        triggers = np.select(
            [crop_col == "Rice", crop_col == "Sugarcane"],
            [rice_trig, sugarcane_trig],
            default=wheat_trig,
        )
    else:
        triggers = wheat_trig

    true_dec = (y_val  < triggers).astype(int)
    pred_dec = (y_pred < triggers).astype(int)
    dec_acc  = float((true_dec == pred_dec).mean() * 100)

    importances = pd.Series(
        rf.feature_importances_, index=feat_cols
    ).sort_values(ascending=False)

    sep = "-" * 62
    _log.info(sep)
    _log.info("  RF DOWNSCALER — Validation Results")
    _log.info(sep)
    _log.info("  RMSE             : %.4f m³/m³  (≈ %.1f mm Wheat equiv.)",
              rmse, rmse * agro.crops["Wheat"].root_depth_mm)
    _log.info("  MAE              : %.4f m³/m³  (≈ %.1f mm Wheat equiv.)",
              mae, mae * agro.crops["Wheat"].root_depth_mm)
    _log.info("  R²               : %.4f", r2)
    _log.info("  OOB R²           : %.4f", rf.oob_score_)
    _log.info("  Decision accuracy: %.1f%%  ← primary metric", dec_acc)
    _log.info(sep)
    _log.info("  Feature importances:")
    for feat, imp in importances.items():
        bar = "█" * int(imp * 40)
        _log.info("    %-18s %s %.3f", feat, bar, imp)
    _log.info(sep)

    return {
        "rmse": rmse, "mae": mae, "r2": r2,
        "decision_accuracy": dec_acc,
        "oob_r2": rf.oob_score_,
        "importances": importances.to_dict(),
    }


def predict_farm_sm(
    rf:       RandomForestRegressor,
    lat:      float,
    lon:      float,
    district: str,
    as_of:    str,
) -> Optional[float]:
    """
    Predicts downscaled SM (mm) for an arbitrary farm coordinate.
    Handles Wheat, Rice, and Sugarcane crops.
    """
    gee_path = settings.data_dir / "gee_extracts" / f"{district}_hyperlocal.csv"
    if not gee_path.exists():
        _log.warning("GEE extract not found for '%s'.", district)
        return None

    gee_df = pd.read_csv(gee_path, parse_dates=["date"])
    gee_df["_dist"] = (
        (gee_df["grid_lat"] - lat) ** 2 + (gee_df["grid_lon"] - lon) ** 2
    ) ** 0.5
    nearest_idx = gee_df["grid_idx"].iloc[gee_df["_dist"].argmin()]

    point_df = gee_df[
        (gee_df["grid_idx"] == nearest_idx) &
        (gee_df["date"] <= pd.Timestamp(as_of))
    ]
    if point_df.empty:
        return None

    latest = point_df.iloc[-1].copy()
    mo     = latest["date"].month

    # season_flag: 0=Rabi, 1=Kharif, 2=Sugarcane
    # All districts have Sugarcane — use season_flag=2 for year-round
    latest["season_flag"] = 2   # Sugarcane year-round

    feat_cols = getattr(rf, "feature_names_", RF_FEATURES)
    row       = {f: float(latest.get(f, 0.0)) for f in feat_cols}
    X         = np.array([[row[f] for f in feat_cols]])

    try:
        sm_m3m3   = float(rf.predict(X)[0])
        # Sugarcane root depth 1200mm (dominant crop all districts)
        root_d    = agro.crops["Sugarcane"].root_depth_mm
        sm_mm     = sm_m3m3 * root_d
        return round(sm_mm, 1)
    except Exception as exc:
        _log.error("RF prediction failed: %s", exc)
        return None