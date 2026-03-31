# farmer_minor.py
"""
simulation/farmer_minor.py
───────────────────────────
Farmer 2 — "ELISA Minor" (Reactive threshold).

Strategy: irrigate 70mm when current SM drops below crop trigger.
No rain forecast, no lookahead, no tariff awareness.
Represents naive rule-based precision irrigation.
"""

import numpy as np
import pandas as pd
from config.settings import agro
from simulation.metrics import kc


def simulate(df: pd.DataFrame, district: str) -> pd.DataFrame:
    d     = df[df["district"] == district].sort_values("date").copy()
    wheat = agro.crops["Wheat"]
    sm    = wheat.fc_mm
    sm_l, irr_l, ev_l = [], [], []

    for _, row in d.iterrows():
        irr     = 0.0
        doy     = row["date"].timetuple().tm_yday
        Kc      = kc(row["crop"], doy)
        profile = agro.get_crop(row["crop"])

        if sm < profile.trigger_mm:
            irr = profile.irr_amount_mm

        sm = float(np.clip(sm + row["precip_mm"] + irr - Kc * row["ETo_mm"],
                            wheat.pwp_mm, wheat.fc_mm))
        sm_l.append(sm); irr_l.append(irr); ev_l.append(1 if irr > 0 else 0)

    d = d.copy()
    d["sm_mm"]         = sm_l
    d["irrigation_mm"] = irr_l
    d["event"]         = ev_l
    d["farmer"]        = "ELISA Minor"
    return d
