# soil_balance.py
"""
features/soil_balance.py
─────────────────────────
Daily FAO-56 soil water balance simulation.

Generates synthetic but physically-correct soil moisture training labels
for districts where real ERA5 data is unavailable.

Two crop logics:
    Wheat (MAD — Management Allowed Depletion):
        Irrigate when SM drops below trigger = FC - MAD × (FC - PWP).
        SM bounded between [PWP, FC].

    Rice (Ponding):
        Maintain a standing water layer. Irrigate when ponding level drops
        below trigger, refilling to the target depth. Accounts for
        daily percolation losses.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from config.settings import agro, settings
from utils.dates import parse_dates

_log = settings.get_logger(__name__)


def simulate_district(district_df: pd.DataFrame, district_name: str) -> pd.DataFrame:
    """
    Runs the water balance simulation for a single district.

    Required input columns: date, crop, precip_mm, ETo_mm

    Returns:
        district_df with new columns: real_soil_moisture_mm, generated_irrigated
    """
    district_df = parse_dates(district_df)
    profiles = agro.crops
    wheat    = profiles["Wheat"]
    rice     = profiles["Rice"]

    wheat_state = {"sm": wheat.fc_mm}
    rice_state  = {"ponding": rice.ponding_target_mm}
    moisture, irrigated = [], []

    for _, row in district_df.iterrows():
        crop = row["crop"]
        irr  = 0.0

        if crop == "Wheat":
            sm = wheat_state["sm"] + row["precip_mm"]
            if sm < wheat.trigger_mm and row["date"].month in wheat.growing_months:
                irr = wheat.irr_amount_mm
                sm += irr
            sm = float(np.clip(sm - row["ETo_mm"], wheat.pwp_mm, wheat.fc_mm))
            wheat_state["sm"] = sm
            moisture.append(sm)

        elif crop == "Rice":
            ponding = (
                rice_state["ponding"]
                + row["precip_mm"]
                - row["ETo_mm"]
                - rice.percolation_mm_day
            )
            if ponding < rice.trigger_mm and row["date"].month in rice.growing_months:
                irr     = rice.irr_amount_mm
                ponding = rice.ponding_target_mm
            ponding = max(0.0, ponding)
            rice_state["ponding"] = ponding
            moisture.append(ponding)

        else:
            # Transition month — carry wheat state forward
            moisture.append(wheat_state["sm"])

        irrigated.append(irr)

    out = district_df.copy()
    out["real_soil_moisture_mm"] = moisture
    out["generated_irrigated"]   = irrigated
    return out


def simulate_all(df: pd.DataFrame) -> pd.DataFrame:
    """Runs simulation for every district in df."""
    _log.info("  Running soil water balance simulation...")
    results = []
    for district in df["district"].unique():
        d_df = df[df["district"] == district].sort_values("date").reset_index(drop=True)
        sim  = simulate_district(d_df, district)
        results.append(sim)
        _log.info(
            "  [%s] %d irrigation events over %d days.",
            district,
            int(sim["generated_irrigated"].gt(0).sum()),
            len(sim),
        )
    result = pd.concat(results, ignore_index=True)
    return result.sort_values(["district", "date"]).reset_index(drop=True)
