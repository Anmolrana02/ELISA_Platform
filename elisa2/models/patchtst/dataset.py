# dataset.py
"""
models/patchtst/dataset.py
───────────────────────────
PyTorch Dataset for multi-step PatchTST forecasting.

Creates overlapping (X, y) windows from the time-series data.
Each sample:
    X[i]  : features for days [i, i+seq_len)         shape: (seq_len, n_features)
    y[i]  : soil moisture for days [i+seq_len, i+seq_len+horizon) shape: (horizon,)
    doy   : day-of-year at position i+seq_len          scalar (int)
    season: 0=Rabi, 1=Kharif at position i+seq_len    scalar (int)

Processes per-district to avoid sequence bleeding across district boundaries.
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

    Not a torch.utils.data.Dataset subclass intentionally — we build
    numpy arrays and convert to tensors in the trainer to keep this
    module torch-free (easier to test independently).
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
        """Converts scaled SM predictions back to mm for a given district."""
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
    Builds sequences from the full dataset.

    Args:
        df           : Full training DataFrame (all districts).
        seq_len      : Input window length in days.
        horizon      : Forecast horizon in days.
        feature_cols : Feature columns to use. Defaults to a standard set.

    Returns:
        ELISADataset or None on failure.
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

        # Scale target separately (for easy inverse transform at inference)
        tgt_scaler  = MinMaxScaler()
        tgt_scaled  = tgt_scaler.fit_transform(d_df[[TARGET]]).ravel()
        scalers[f"{district}_target"] = tgt_scaler

        doy_arr    = d_df["date"].dt.dayofyear.values
        season_arr = ((d_df["date"].dt.month >= 6) & (d_df["date"].dt.month <= 10)).astype(int).values

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


def split_chronological(
    dataset: ELISADataset,
    test_ratio: float = 0.2,
) -> Tuple[ELISADataset, ELISADataset]:
    """
    Splits dataset chronologically (no shuffle).
    Earlier sequences → train. Later sequences → test.
    """
    n_train = int(len(dataset) * (1 - test_ratio))
    train   = ELISADataset(
        X=dataset.X[:n_train], y=dataset.y[:n_train],
        doy=dataset.doy[:n_train], season=dataset.season[:n_train],
        feature_cols=dataset.feature_cols, scalers=dataset.scalers,
    )
    test    = ELISADataset(
        X=dataset.X[n_train:], y=dataset.y[n_train:],
        doy=dataset.doy[n_train:], season=dataset.season[n_train:],
        feature_cols=dataset.feature_cols, scalers=dataset.scalers,
    )
    return train, test


def _default_features(df: pd.DataFrame) -> List[str]:
    base     = [TARGET, "temperature_C", "precip_mm", "solar_rad_MJ_m2", "ETo_mm"]
    optional = ["NDVI", "NDWI", "delta_VV", "VV"]
    return base + [c for c in optional if c in df.columns]
