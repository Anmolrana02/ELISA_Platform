"""
download_era5.py
─────────────────
Downloads ERA5-Land swvl2 and swvl3 monthly files from Copernicus CDS.
Your swvl1 files already exist — this only downloads what is missing.

Run from ELISA_Platform folder:
    python download_era5.py

Takes about 20-40 minutes total depending on CDS queue.
Files save to elisa2/data/soil_moisture_data/
"""

import cdsapi
import os
from pathlib import Path

OUTPUT_DIR = Path("elisa2/data/soil_moisture_data")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Years and months to download
YEARS  = [str(y) for y in range(2015, 2025)]   # 2015–2024
MONTHS = [f"{m:02d}" for m in range(1, 13)]     # 01–12

# Variables to download — swvl1 already exists, download 2 and 3
VARIABLES = [
    "volumetric_soil_water_layer_2",   # 7–28cm
    "volumetric_soil_water_layer_3",   # 28–100cm
]

# Bounding box covering all 5 districts (lat 26–30, lon 77–80)
AREA = [30, 77, 26, 80]   # North, West, South, East

c = cdsapi.Client()

for year in YEARS:
    for month in MONTHS:
        for var_idx, variable in enumerate(VARIABLES, start=2):
            # Output filename matches your existing naming convention
            fname = OUTPUT_DIR / f"soil_moisture_{year}-{month}_swvl{var_idx}.nc"

            if fname.exists():
                size_kb = fname.stat().st_size / 1000
                print(f"  EXISTS ({size_kb:.0f} KB): {fname.name}")
                continue

            print(f"  Downloading {year}-{month} {variable}...")

            try:
                c.retrieve(
                    "reanalysis-era5-land",
                    {
                        "variable":     variable,
                        "year":         year,
                        "month":        month,
                        "day":          [f"{d:02d}" for d in range(1, 32)],
                        "time":         [f"{h:02d}:00" for h in range(24)],
                        "area":         AREA,
                        "format":       "netcdf",
                    },
                    str(fname),
                )
                size_mb = fname.stat().st_size / 1_000_000
                print(f"    Saved {size_mb:.1f} MB → {fname.name}")

            except Exception as e:
                print(f"    FAILED {year}-{month}: {e}")

print("\nDownload complete.")
print("Now run: python -m elisa2.pipelines.run --step 3 --force")