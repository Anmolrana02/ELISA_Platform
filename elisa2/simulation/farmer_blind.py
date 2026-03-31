# farmer_blind.py
"""
simulation/farmer_blind.py
───────────────────────────
Farmer 1 — "Blind" (Traditional flood irrigation).

Strategy: irrigate every 10 days, 80mm per event, regardless of
soil moisture, rainfall, or crop growth stage.
Represents the current default practice in Western UP.
"""

import numpy as np
import pandas as pd
from config.settings import agro
from simulation.metrics import kc


def simulate(df: pd.DataFrame, district: str) -> pd.DataFrame:
    """
    Args:
        df       : Full dataset DataFrame.
        district : District to simulate.

    Returns:
        DataFrame with sm_mm, irrigation_mm, event, farmer columns.
    """
    d       = df[df["district"] == district].sort_values("date").copy()
    wheat   = agro.crops["Wheat"]
    sm      = wheat.fc_mm
    sm_l, irr_l, ev_l = [], [], []
    start   = d["date"].iloc[0]

    for _, row in d.iterrows():
        irr = 0.0
        doy = row["date"].timetuple().tm_yday
        Kc  = kc(row["crop"], doy)
        if (row["date"] - start).days % agro.sim["blind_interval_days"] == 0:
            irr = agro.sim["blind_amount_mm"]
        sm  = float(np.clip(sm + row["precip_mm"] + irr - Kc * row["ETo_mm"],
                             wheat.pwp_mm, wheat.fc_mm))
        sm_l.append(sm); irr_l.append(irr); ev_l.append(1 if irr > 0 else 0)

    d = d.copy()
    d["sm_mm"]         = sm_l
    d["irrigation_mm"] = irr_l
    d["event"]         = ev_l
    d["farmer"]        = "Blind"
    return d
