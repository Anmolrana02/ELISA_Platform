# metrics.py
"""
simulation/metrics.py
──────────────────────
Shared metric computation for all farmer simulations.

Metrics per farmer × district:
    irrigation_events  : Total number of irrigation events
    water_applied_mm   : Total water applied (mm/season)
    energy_kwh         : kWh consumed by pump
    cost_inr           : Total ₹ cost at average off-peak tariff
    stress_days        : Days where SM < PWP (crop stress)
    mean_ks            : FAO-56 Ks yield stress index (0–1, 1=no stress)

Kc (crop coefficient) — FAO-56 piecewise table from agronomy.yaml:
    Wheat: initial (0.30) → mid-season (1.15) → late (0.40)
    Rice:  initial (1.05) → mid-season (1.20) → late (0.90)
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from config.settings import agro


def kc(crop: str, doy: int) -> float:
    """Returns FAO-56 crop coefficient for a given crop and day-of-year."""
    return agro.get_crop(crop).kc(doy)


def compute(sim_df: pd.DataFrame, farmer_name: str, district: str) -> dict:
    """
    Computes all comparison metrics for a single farmer/district simulation.

    Args:
        sim_df      : Simulation output DataFrame with columns:
                      date, crop, sm_mm, irrigation_mm, event
        farmer_name : Label string.
        district    : District name.

    Returns:
        Metrics dict.
    """
    pump        = agro.pump
    tariff      = agro.tariff
    tariff_avg  = (tariff.low + tariff.medium) / 2   # off-peak weighted average

    stress_days = 0
    ks_vals     = []

    for _, row in sim_df.iterrows():
        crop    = row["crop"]
        profile = agro.get_crop(crop)
        sm      = row["sm_mm"]

        if sm < profile.pwp_mm:
            stress_days += 1
            ks_vals.append(0.0)
        else:
            denom = max(profile.trigger_mm - profile.pwp_mm, 1.0)
            ks    = float(np.clip((sm - profile.pwp_mm) / denom, 0.0, 1.0))
            ks_vals.append(ks)

    total_events = int(sim_df["event"].sum())
    total_water  = float(sim_df["irrigation_mm"].sum())
    energy_kwh   = total_events * pump.energy_per_run_kwh
    cost_inr     = energy_kwh   * tariff_avg

    return {
        "farmer":            farmer_name,
        "district":          district,
        "irrigation_events": total_events,
        "water_applied_mm":  round(total_water, 1),
        "energy_kwh":        round(energy_kwh,  2),
        "cost_inr":          round(cost_inr,    2),
        "stress_days":       stress_days,
        "mean_ks":           round(float(np.mean(ks_vals)), 4),
    }
