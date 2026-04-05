"""
ingestion/live_weather.py
──────────────────────────
Fetches recent NASA POWER weather (last 60 days) and appends
to the existing dataset so PatchTST always has a fresh 30-day window.
Call this from the nightly scheduler before predictions run.
"""

import pandas as pd
from datetime import date, timedelta
from pathlib import Path

from config.settings import agro, settings
from ingestion.nasa_power import fetch_district
from features.crop_calendar import assign as assign_crop
from features.eto import calculate as calc_eto
from utils.dates import read_csv

def extend_dataset(days_back: int = 60) -> None:
    """
    Appends the last `days_back` days of NASA POWER weather
    to dataset_real_soil.csv for all districts.
    SM column is estimated from each farm's state file.
    """
    path = settings.real_soil_dataset
    if not path.exists():
        path = settings.simulated_dataset

    existing = read_csv(path)
    end_date = date.today()
    start_date = end_date - timedelta(days=days_back)

    new_frames = []

    for district, (lat, lon) in agro.districts.items():
        # Only fetch if we don't already have recent data
        last_date = existing[existing["district"] == district]["date"].max()
        if pd.Timestamp(end_date) - last_date < pd.Timedelta(days=3):
            continue  # already up to date

        fetch_start = last_date.strftime("%Y-%m-%d")
        df = fetch_district(
            district=district, lat=lat, lon=lon,
            start=fetch_start,
            end=end_date.strftime("%Y-%m-%d"),
        )
        if df is None:
            continue

        df["district"] = district
        df["latitude"] = lat
        df = assign_crop(df)
        df = calc_eto(df)

        # SM: use district's last known value and apply ETo decay
        last_sm = float(
            existing[existing["district"] == district]["real_soil_moisture_mm"].iloc[-1]
        )
        sm_values = []
        for i in range(len(df)):
            last_sm = max(
                last_sm + float(df.iloc[i]["precip_mm"]) - float(df.iloc[i]["ETo_mm"]),
                135.0  # PWP floor
            )
            sm_values.append(round(last_sm, 2))

        df["real_soil_moisture_mm"] = sm_values
        new_frames.append(df)

    if new_frames:
        new_data = pd.concat(new_frames, ignore_index=True)
        updated = pd.concat([existing, new_data], ignore_index=True)
        updated = updated.drop_duplicates(subset=["date", "district"]).sort_values(
            ["district", "date"]
        ).reset_index(drop=True)
        updated.to_csv(path, index=False)
        print(f"Dataset extended: {len(new_data)} new rows added.")