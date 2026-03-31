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
        default="None",
    )
    return df
