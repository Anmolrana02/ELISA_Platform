# interpolation.py
"""
features/interpolation.py
──────────────────────────
Fills null values in GEE satellite features before RF/PatchTST training.

Two strategies:

SAR (VV, VH, VV_VH_ratio, delta_VV) — ERA5-guided interpolation:
    SAR backscatter correlates strongly with soil moisture.
    Gaps occur because Sentinel-1 has 6–12 day revisit time.
    We use ERA5 SM as a proxy to guide the interpolation:
        VV_filled[t] = VV[t1] + (ERA5[t]-ERA5[t1])/(ERA5[t2]-ERA5[t1])
                       × (VV[t2]-VV[t1])
    where t1 and t2 are the bracketing known SAR observations.
    This ensures rainfall events are reflected in filled SAR values
    instead of the flat plateaus produced by simple forward fill.

Optical (NDVI, NDWI, EVI) — Savitzky-Golay smoothing:
    Cloud cover causes gaps in Sentinel-2 optical indices.
    NDVI/EVI follow a smooth seasonal curve (crop growth cycle).
    We fit a Savitzky-Golay filter (window=31 days, poly=3) to
    available observations and interpolate gaps from the fitted curve.
    This is the standard approach in agricultural remote sensing
    (Jonsson & Eklundh 2002, TIMESAT).

Series start (first rows all NaN before first satellite acquisition):
    Backward-fill from the first valid observation.
    No prior data exists so this is the only option; we use a short
    backward-fill limit (12 days) to avoid propagating too far back.

Per grid point processing:
    All interpolation is done per (district, grid_idx) to avoid mixing
    spatial locations, since each grid point has different terrain/vegetation.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.signal import savgol_filter

from config.settings import settings

_log = settings.get_logger(__name__)

# SAR columns to fill
_SAR_COLS = ["VV", "VH", "delta_VV"]
# Optical columns to fill
_OPT_COLS = ["NDVI", "NDWI", "EVI"]
# ERA5 SM column used as proxy for SAR interpolation
_ERA5_COL = "era5_sm_m3m3"

# Maximum gap length to fill for SAR (Sentinel-1 max revisit ≈ 12 days)
# Gaps longer than this are filled with forward fill then flagged
_SAR_MAX_GAP = 12

# Savitzky-Golay parameters for optical
_SG_WINDOW  = 31   # days — must be odd
_SG_POLYORD = 3    # polynomial order


# ── ERA5-guided SAR interpolation ─────────────────────────────────────────────

def _era5_guided_fill_series(
    sar:   pd.Series,
    era5:  pd.Series,
) -> pd.Series:
    """
    Fills NaN gaps in a SAR series using ERA5 SM as interpolation guide.

    For each gap [t1 .. t2] between two known SAR values, the filled
    value at day t is:
        SAR[t] = SAR[t1] + delta_era5_norm × (SAR[t2] - SAR[t1])
    where delta_era5_norm is the fractional position of ERA5[t] between
    ERA5[t1] and ERA5[t2].

    Falls back to linear interpolation when ERA5 range is near-zero
    (no SM change between bracket points).
    """
    sar   = sar.copy().astype(float)
    era5  = era5.copy().astype(float)
    result = sar.copy()

    n      = len(sar)
    valid  = np.where(~np.isnan(sar.values))[0]

    if len(valid) == 0:
        return result   # all NaN — nothing to do

    # Backward fill the series start from first valid observation
    if valid[0] > 0:
        fill_back = min(valid[0], _SAR_MAX_GAP)
        result.iloc[valid[0] - fill_back : valid[0]] = sar.iloc[valid[0]]

    # Fill each gap between consecutive valid observations
    for k in range(len(valid) - 1):
        t1, t2 = valid[k], valid[k + 1]
        gap    = t2 - t1 - 1
        if gap == 0:
            continue

        sar_t1  = sar.iloc[t1]
        sar_t2  = sar.iloc[t2]
        era5_t1 = era5.iloc[t1]
        era5_t2 = era5.iloc[t2]
        era5_range = era5_t2 - era5_t1

        for t in range(t1 + 1, t2):
            if abs(era5_range) > 1e-6:
                # ERA5-guided: use ERA5 SM change as proxy
                alpha = (era5.iloc[t] - era5_t1) / era5_range
                alpha = float(np.clip(alpha, 0.0, 1.0))
            else:
                # ERA5 flat — fall back to linear time interpolation
                alpha = (t - t1) / (t2 - t1)

            result.iloc[t] = sar_t1 + alpha * (sar_t2 - sar_t1)

    # Forward fill any trailing NaN after last valid observation
    result = result.ffill(limit=_SAR_MAX_GAP)

    return result


def fill_sar(df: pd.DataFrame) -> pd.DataFrame:
    """
    Fills SAR null values using ERA5-guided interpolation.
    Processes per (district, grid_idx) to avoid mixing locations.

    Args:
        df: DataFrame with VV, VH, delta_VV, era5_sm_m3m3 columns.

    Returns:
        df with SAR columns filled.
    """
    df      = df.copy()
    groups  = ["district", "grid_idx"] if "grid_idx" in df.columns else ["district"]
    filled  = 0
    total   = 0

    for key, grp in df.groupby(groups, sort=False):
        idx    = grp.index
        era5   = grp[_ERA5_COL].copy()

        for col in _SAR_COLS:
            if col not in df.columns:
                continue
            before = grp[col].isna().sum()
            total += before
            if before == 0:
                continue
            filled_series = _era5_guided_fill_series(grp[col], era5)
            df.loc[idx, col] = filled_series.values
            after  = df.loc[idx, col].isna().sum()
            filled += (before - after)

    # Recompute VV_VH_ratio from filled VV and VH
    if "VV" in df.columns and "VH" in df.columns:
        denom = df["VH"].replace(0, np.nan)
        df["VV_VH_ratio"] = df["VV"] / denom

    _log.info(
        "SAR fill: %d/%d null values filled (%.1f%%)",
        filled, total, 100 * filled / max(total, 1),
    )
    return df


# ── Savitzky-Golay optical smoothing ──────────────────────────────────────────

def _savgol_fill_series(opt: pd.Series) -> pd.Series:
    """
    Fills NaN gaps in an optical index series using Savitzky-Golay smoothing.

    Strategy:
        1. Linear interpolate to get a continuous series (temporary)
        2. Apply Savitzky-Golay filter to smooth the result
        3. Use smoothed curve only for originally-missing positions;
           preserve original values where data was present.

    This avoids over-smoothing real observations while filling gaps
    with a physically realistic smooth seasonal curve.
    """
    opt    = opt.copy().astype(float)
    result = opt.copy()

    n_valid = opt.notna().sum()
    n_total = len(opt)

    if n_valid == 0:
        return result   # all NaN
    if n_valid == n_total:
        return result   # no gaps

    # Backward fill series start (cloud at beginning)
    result = result.bfill(limit=_SAR_MAX_GAP)
    # Forward fill series end
    result = result.ffill(limit=_SAR_MAX_GAP)

    # Linear interpolation to fill remaining interior gaps
    interpolated = result.interpolate(method="linear", limit_direction="both")

    # Apply SG filter only if we have enough data points
    window = min(_SG_WINDOW, (n_valid // 2) * 2 + 1)   # ensure odd
    window = max(window, _SG_POLYORD + 2)
    if window % 2 == 0:
        window += 1

    try:
        smoothed = savgol_filter(
            interpolated.fillna(method="ffill").fillna(method="bfill").values,
            window_length=window,
            polyorder=_SG_POLYORD,
            mode="mirror",
        )
        smoothed_s = pd.Series(smoothed, index=opt.index)
    except Exception:
        smoothed_s = interpolated

    # Keep original observed values; use smoothed only for gaps
    nan_mask         = opt.isna()
    result           = opt.copy()
    result[nan_mask] = smoothed_s[nan_mask]

    return result


def fill_optical(df: pd.DataFrame) -> pd.DataFrame:
    """
    Fills optical index null values using Savitzky-Golay smoothing.
    Processes per (district, grid_idx).

    Args:
        df: DataFrame with NDVI, NDWI, EVI columns.

    Returns:
        df with optical columns filled.
    """
    df     = df.copy()
    groups = ["district", "grid_idx"] if "grid_idx" in df.columns else ["district"]
    filled = 0
    total  = 0

    for key, grp in df.groupby(groups, sort=False):
        idx = grp.index
        for col in _OPT_COLS:
            if col not in df.columns:
                continue
            before = grp[col].isna().sum()
            total += before
            if before == 0:
                continue
            filled_series      = _savgol_fill_series(grp[col])
            df.loc[idx, col]   = filled_series.values
            after              = df.loc[idx, col].isna().sum()
            filled            += (before - after)

    _log.info(
        "Optical fill (Savitzky-Golay): %d/%d null values filled (%.1f%%)",
        filled, total, 100 * filled / max(total, 1),
    )
    return df


# ── Main entry point ──────────────────────────────────────────────────────────

def fill_all(df: pd.DataFrame) -> pd.DataFrame:
    """
    Applies ERA5-guided SAR fill then Savitzky-Golay optical fill.

    Call this on every GEE extract DataFrame before training.

    Args:
        df: Raw GEE extract DataFrame.

    Returns:
        df with all satellite features filled.
    """
    _log.info("  Applying satellite feature interpolation...")
    n_before = df[_SAR_COLS + _OPT_COLS].isna().sum().sum()

    df = fill_sar(df)
    df = fill_optical(df)

    n_after  = df[_SAR_COLS + _OPT_COLS].isna().sum().sum()
    _log.info(
        "  Interpolation complete: %d → %d nulls (%.1f%% reduction)",
        n_before, n_after,
        100 * (n_before - n_after) / max(n_before, 1),
    )
    return df