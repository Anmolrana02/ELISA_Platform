"""
utils/dates.py
───────────────
Centralised date-parsing helper.
Handles DD-MM-YYYY and all other formats transparently.
"""

from __future__ import annotations
from pathlib import Path
from typing import Union
import pandas as pd


def parse_dates(df: pd.DataFrame, col: str = "date") -> pd.DataFrame:
    if col not in df.columns:
        return df
    if pd.api.types.is_datetime64_any_dtype(df[col]):
        return df
    df = df.copy()
    df[col] = pd.to_datetime(df[col], format="mixed", dayfirst=True)
    return df


def read_csv(path: Union[str, Path], **kwargs) -> pd.DataFrame:
    kwargs.pop("parse_dates", None)
    df = pd.read_csv(path, **kwargs)
    return parse_dates(df, col="date")