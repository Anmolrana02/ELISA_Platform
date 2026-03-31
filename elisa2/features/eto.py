# eto.py
"""
features/eto.py
───────────────
Calculates Reference Evapotranspiration (ETo) using the Hargreaves-Samani
method (FAO-56 compatible).

Why Hargreaves-Samani instead of Penman-Monteith:
    Penman-Monteith requires humidity and wind speed measurements that are
    noisy or unavailable at farm scale in Western UP. Hargreaves-Samani
    needs only temperature and solar radiation — both available from
    NASA POWER at good quality.

    Formula (FAO-56 Eq. 52):
        ETo = 0.0023 × (T_avg + 17.8) × √T_diff × Ra_mm
    where:
        Ra_mm   = extraterrestrial radiation converted to mm/day
        T_diff  = estimated daily temp range from Rs/Ra ratio
"""

import numpy as np
import pandas as pd
from utils.dates import parse_dates

from config.settings import settings

_log = settings.get_logger(__name__)

_Gsc = 0.0820   # Solar constant (MJ/m²/min)


def calculate(df: pd.DataFrame) -> pd.DataFrame:
    """
    Adds 'ETo_mm' column to df.

    Required input columns:
        date, latitude, temperature_C, solar_rad_MJ_m2

    Returns:
        df with new 'ETo_mm' column (mm/day, clipped ≥ 0).
    """
    _log.info("  Calculating ETo (Hargreaves-Samani)...")
    df = df.copy()
    df = parse_dates(df)
    try:
        J   = df["date"].dt.dayofyear           # Day of year
        phi = np.deg2rad(df["latitude"])         # Latitude in radians

        # Solar declination (rad)
        delta = 0.409 * np.sin(2 * np.pi / 365 * J - 1.39)

        # Sunset hour angle (rad) — clipped for numerical safety
        ws_arg = -np.tan(phi) * np.tan(delta)
        ws     = np.arccos(np.clip(ws_arg, -1.0, 1.0))

        # Inverse relative Earth–Sun distance
        dr = 1 + 0.033 * np.cos(2 * np.pi / 365 * J)

        # Extraterrestrial radiation (MJ/m²/day) — FAO-56 Eq. 21
        Ra = (24 * 60 / np.pi) * _Gsc * dr * (
            ws * np.sin(phi) * np.sin(delta)
            + np.cos(phi) * np.cos(delta) * np.sin(ws)
        )
        Ra = Ra.clip(lower=0.0001)

        # Estimate daily temp range from Rs/Ra (Hargreaves 1994 proxy)
        Rs_over_Ra = np.clip(df["solar_rad_MJ_m2"] / Ra, 0.3, 1.0)
        T_diff_est = 8.0 + (16.0 - 8.0) * Rs_over_Ra

        Ra_mm       = Ra * 0.408      # MJ/m²/day → mm/day equivalent
        T_avg       = df["temperature_C"]
        ETo         = 0.0023 * (T_avg + 17.8) * np.sqrt(T_diff_est) * Ra_mm
        df["ETo_mm"] = ETo.fillna(0).clip(lower=0)

        _log.info(
            "  ETo done. Mean=%.2f mm/day, Max=%.2f mm/day",
            df["ETo_mm"].mean(), df["ETo_mm"].max(),
        )
    except Exception as exc:
        _log.error("  ETo calculation failed: %s", exc, exc_info=True)
        df["ETo_mm"] = 0.0

    return df
