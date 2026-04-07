# crop_calendar.py
"""
features/crop_calendar.py
──────────────────────────
Assigns crop type to each date based on the Western UP Kharif/Rabi cycle.
"""

import numpy as np
import pandas as pd
from utils.dates import parse_dates


def assign(df: pd.DataFrame) -> pd.DataFrame:
    """
    Adds a 'crop' column to df based on calendar month.

        Rice  (Kharif) : June  – October   [6–10]
        Wheat (Rabi)   : November – April  [11–4]
        None            : May (transition month)

    Args:
        df: DataFrame with a 'date' column (datetime).

    Returns:
        df with new 'crop' column.
    """
    df = df.copy()
    # Force datetime parsing — handles DD-MM-YYYY and all other formats
    df["date"] = pd.to_datetime(df["date"], dayfirst=True)
    df = parse_dates(df)
    month = df["date"].dt.month
    df["crop"] = np.select(
        condlist=[(month >= 6) & (month <= 10),
                  (month >= 11) | (month <= 4)],
        choicelist=["Rice", "Wheat"],
        default="None",# crop_calendar.py

""" 

features/crop_calendar.py
──────────────────────────
Assigns crop type to each date based on the Western UP crop calendar.

Crop assignment (all districts, year-round Sugarcane):
    Sugarcane  : all 12 months (year-round ratoon crop)
    Rice       : Jun–Oct      [6–10]   — Kharif season
    Wheat      : Nov–Apr      [11–4]   — Rabi season
    None       : May          [5]      — transition / fallow

NOTE:
    Since Sugarcane is a year-round ratoon crop, it co-exists with
    Rice and Wheat in many fields. However for the ML training labels
    we assign the DOMINANT crop per month:
      - May (transition): Sugarcane (active growth, not fallow)
      - Jun–Oct: If a district has Sugarcane, Sugarcane. Otherwise Rice.
      - Nov–Apr: If a district has Sugarcane, Sugarcane. Otherwise Wheat.

    For this dataset ALL 5 districts have Sugarcane as a registered crop,
    so the assignment is:
        All months → Sugarcane

    This is consistent with Western UP agronomy where Sugarcane is
    cultivated year-round and is the primary cash crop in all 5 districts.
    The seasonal Rice/Wheat behaviour is captured by the ERA5 SM signal
    and the FAO-56 water balance parameters for Sugarcane.

    If you need a per-district override (e.g. Meerut/Ghaziabad as
    Rice/Wheat), change SUGARCANE_ALL_DISTRICTS to False and use
    the district-aware logic below.

"""

import numpy as np
import pandas as pd
from utils.dates import parse_dates

# Set to True to assign Sugarcane year-round to all districts
# (recommended — Sugarcane is a major crop across all 5 Western UP districts)
SUGARCANE_ALL_DISTRICTS: bool = True


def assign(df: pd.DataFrame) -> pd.DataFrame:
    """
    Adds a 'crop' column to df based on calendar month.

    If SUGARCANE_ALL_DISTRICTS=True (default):
        All months → "Sugarcane" (year-round ratoon)

    If SUGARCANE_ALL_DISTRICTS=False (district-aware mode):
        Sugarcane districts (Muzaffarnagar, Shamli, Baghpat):
            All months → "Sugarcane"
        Other districts (Meerut, Ghaziabad):
            Jun–Oct  → "Rice"
            Nov–Apr  → "Wheat"
            May      → "None"

    Args:
        df: DataFrame with 'date' column (datetime) and optionally 'district'.

    Returns:
        df with new 'crop' column.
    """
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"], dayfirst=True)
    df = parse_dates(df)
    month = df["date"].dt.month

    if SUGARCANE_ALL_DISTRICTS:
        # All districts, all months → Sugarcane (year-round ratoon)
        df["crop"] = "Sugarcane"

    else:
        # District-aware: Sugarcane for 3 dominant districts, Rice/Wheat for rest
        _SUGARCANE_DISTRICTS = {"Muzaffarnagar", "Shamli", "Baghpat"}

        if "district" not in df.columns:
            # No district column — fall back to simple Rice/Wheat calendar
            df["crop"] = np.select(
                condlist=[
                    (month >= 6) & (month <= 10),
                    (month >= 11) | (month <= 4),
                ],
                choicelist=["Rice", "Wheat"],
                default="None",
            )
        else:
            is_sugarcane_district = df["district"].isin(_SUGARCANE_DISTRICTS)

            conditions = [
                is_sugarcane_district,                                         # Sugarcane districts
                (~is_sugarcane_district) & ((month >= 6) & (month <= 10)),    # Rice months
                (~is_sugarcane_district) & ((month >= 11) | (month <= 4)),    # Wheat months
            ]
            choices = ["Sugarcane", "Rice", "Wheat"]
            df["crop"] = np.select(conditions, choices, default="None")

    return df


def crop_to_int(crop: str) -> int:
    """
    Converts crop name to integer for ML features.
        0 = Wheat
        1 = Rice
        2 = Sugarcane
        -1 = None / unknown
    """
    _MAP = {"Wheat": 0, "Rice": 1, "Sugarcane": 2, "None": -1}
    return _MAP.get(crop, -1)
    )
    return df
