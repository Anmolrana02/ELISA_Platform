# dataset.py
"""
models/patchtst/dataset.py
───────────────────────────
PyTorch Dataset for multi-step PatchTST forecasting.

Changes from v1:
    - seq_len=60, patch_size=6 → 10 patches of 6 days (weekly cycle)
    - crop_int added as a feature (0=Wheat, 1=Rice, 2=Sugarcane)
    - month_sin / month_cos added as cyclic seasonality features
    - season flag now 3-class: 0=Rabi, 1=Kharif, 2=Sugarcane year-round
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from sklearn.preprocessing import MinMaxScaler

from config.settings import settings

TARGET = "real_soil_moisture_mm"


class ELISADataset:
    """
    Holds all processed sequences for training/evaluation.
    Not a torch.Dataset subclass — numpy arrays converted in trainer.
    """

    def __init__(
        self,
        X:       np.ndarray,
        y:       np.ndarray,
        doy:     np.ndarray,
        season:  np.ndarray,
        feature_cols: List[str],
        scalers: Dict[str, MinMaxScaler],
    ):
        self.X            = X
        self.y            = y
        self.doy          = doy
        self.season       = season
        self.feature_cols = feature_cols
        self.scalers      = scalers
        self.n_features   = X.shape[2] if X.ndim == 3 else 0

    def __len__(self) -> int:
        return len(self.X)

    def inverse_transform_target(self, district: str, scaled: np.ndarray) -> np.ndarray:
        scaler = self.scalers.get(f"{district}_target")
        if scaler is None:
            return scaled
        return scaler.inverse_transform(scaled.reshape(-1, 1)).ravel()


def build(
    df:           pd.DataFrame,
    seq_len:      int,
    horizon:      int,
    feature_cols: Optional[List[str]] = None,
) -> Optional[ELISADataset]:
    """
    Builds overlapping (X, y) windows from the full dataset.

    Per-district processing prevents sequence bleeding across boundaries.
    Features include crop_int and month_sin/cos for improved seasonality.
    """
    if feature_cols is None:
        feature_cols = _default_features(df)

    all_X, all_y, all_doy, all_season = [], [], [], []
    scalers: Dict[str, MinMaxScaler] = {}

    for district in df["district"].unique():
        d_df  = df[df["district"] == district].sort_values("date").reset_index(drop=True)
        avail = [c for c in feature_cols if c in d_df.columns]
        d_df  = d_df.dropna(subset=avail + [TARGET])

        min_len = seq_len + horizon + 10
        if len(d_df) < min_len:
            continue

        # Scale features
        feat_scaler = MinMaxScaler()
        feat_scaled = feat_scaler.fit_transform(d_df[avail])
        scalers[district] = feat_scaler

        # Scale target separately (for inverse transform at inference)
        tgt_scaler = MinMaxScaler()
        tgt_scaled = tgt_scaler.fit_transform(d_df[[TARGET]]).ravel()
        scalers[f"{district}_target"] = tgt_scaler

        doy_arr = d_df["date"].dt.dayofyear.values

        # 3-class season: 0=Rabi (Nov-Apr), 1=Kharif (Jun-Oct), 2=Sugarcane (May or year-round)
        month       = d_df["date"].dt.month
        season_arr  = np.where(
            d_df["crop"] == "Sugarcane", 2,
            np.where((month >= 6) & (month <= 10), 1, 0)
        ).astype(int)

        n = len(feat_scaled)
        for i in range(n - seq_len - horizon + 1):
            all_X.append(feat_scaled[i: i + seq_len])
            all_y.append(tgt_scaled[i + seq_len: i + seq_len + horizon])
            all_doy.append(doy_arr[i + seq_len])
            all_season.append(season_arr[i + seq_len])

    if not all_X:
        return None

    X = np.array(all_X, dtype=np.float32)
    y = np.array(all_y, dtype=np.float32)
    return ELISADataset(
        X=X, y=y,
        doy=np.array(all_doy,    dtype=np.int64),
        season=np.array(all_season, dtype=np.int64),
        feature_cols=avail,
        scalers=scalers,
    )


def _default_features(df: pd.DataFrame) -> List[str]:
    """
    Default feature set for PatchTST.
    Includes:
      - Target SM (for autoregressive context)
      - Weather: temperature, precip, solar, ETo
      - Cyclic month encoding (sin/cos)
      - Integer crop label (0=Wheat, 1=Rice, 2=Sugarcane)
      - GEE satellite features if available
    """
    base = [TARGET, "temperature_C", "precip_mm", "solar_rad_MJ_m2", "ETo_mm",
            "month_sin", "month_cos", "crop_int"]
    optional = ["NDVI", "NDWI", "EVI", "delta_VV", "VV", "VH"]
    return base + [c for c in optional if c in df.columns]