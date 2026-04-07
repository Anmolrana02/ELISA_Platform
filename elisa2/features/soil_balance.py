# soil_balance.py
"""
features/soil_balance.py
─────────────────────────
Daily FAO-56 soil water balance simulation.

Three crop logics:
    Wheat (MAD):
        Irrigate when SM drops below trigger = FC - MAD×(FC-PWP).
        SM bounded between [PWP, FC].

    Rice (Ponding):
        Maintain standing water layer. Irrigate when ponding drops
        below trigger, refilling to target depth. Cap at ponding_target_mm.

    Sugarcane (MAD — same logic as Wheat, different params):
        Deep-rooted (1200mm), higher MAD (0.65), year-round crop.
        trigger = FC - MAD×(FC-PWP) = 300 - 0.65×120 = 222 mm.
        SM bounded between [PWP=180mm, FC=300mm].
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
    profiles    = agro.crops
    wheat       = profiles["Wheat"]
    rice        = profiles["Rice"]
    sugarcane   = profiles["Sugarcane"]

    wheat_state     = {"sm": wheat.fc_mm}
    rice_state      = {"ponding": rice.ponding_target_mm}
    sugarcane_state = {"sm": sugarcane.fc_mm}

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
            # Cap at ponding_target_mm — fix for the 277mm bug
            ponding = max(0.0, min(ponding, rice.ponding_target_mm))
            rice_state["ponding"] = ponding
            moisture.append(ponding)

        elif crop == "Sugarcane":
            # MAD-based, same logic as Wheat, year-round
            sm = sugarcane_state["sm"] + row["precip_mm"]
            # Sugarcane grows year-round — irrigate whenever SM drops below trigger
            if sm < sugarcane.trigger_mm:
                irr = sugarcane.irr_amount_mm
                sm += irr
            sm = float(np.clip(sm - row["ETo_mm"], sugarcane.pwp_mm, sugarcane.fc_mm))
            sugarcane_state["sm"] = sm
            moisture.append(sm)

        else:
            # Transition / None — carry Wheat state forward as neutral fallback
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