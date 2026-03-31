# era5_loader.py
"""
ingestion/era5_loader.py
─────────────────────────
Loads ERA5-Land NetCDF files and computes a weighted root-zone soil
moisture composite from three soil layers.

Why 3 layers instead of just swvl1:
    Wheat roots extend to ~90 cm. ERA5-Land swvl1 covers only 0–7 cm
    (top 7 cm). Using swvl1 alone severely underestimates root-zone SM
    and gives the wrong picture of crop water stress.

Layer depth weights (proportional to thickness):
    swvl1 : 0–7 cm    →  7 / 100 = 0.07
    swvl2 : 7–28 cm   → 21 / 100 = 0.21
    swvl3 : 28–100 cm → 72 / 100 = 0.72
    Total             = 100 cm root zone

Output:
    xarray Dataset with variable 'sm_rootzone' (m³/m³), aggregated to daily.
"""

from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Optional

from config.settings import settings

_log = settings.get_logger(__name__)

_LAYER_WEIGHTS = {
    "swvl1": 0.07,
    "swvl2": 0.21,
    "swvl3": 0.72,
}


def _unzip_inplace(soil_dir: Path) -> None:
    """
    Some Copernicus CDS downloads arrive as .zip containing a .nc inside.
    Extracts the inner .nc and overwrites the zip file in-place.
    """
    for f in soil_dir.glob("*.nc"):
        if not zipfile.is_zipfile(f):
            continue
        _log.debug("  Unzipping in-place: %s", f.name)
        try:
            with zipfile.ZipFile(f, "r") as zf:
                inner = next((n for n in zf.namelist() if n.endswith(".nc")), None)
                if not inner:
                    continue
                data = zf.read(inner)
            f.write_bytes(data)
            _log.debug("  Extracted: %s", inner)
        except Exception as exc:
            _log.error("  Failed to unzip %s: %s", f.name, exc)


def load(soil_dir: Optional[Path] = None):
    """
    Opens all .nc files in soil_dir, builds a weighted root-zone SM
    composite, and returns a daily-aggregated xarray Dataset.

    Args:
        soil_dir: Directory with ERA5-Land .nc files.
                  Defaults to data/soil_moisture_data/.

    Returns:
        xarray.Dataset with variable 'sm_rootzone', or None on failure.
    """
    try:
        import xarray as xr
    except ImportError:
        _log.error("xarray not installed. Run: pip install xarray netcdf4")
        return None

    soil_dir = soil_dir or (settings.data_dir / "soil_moisture_data")
    nc_files = list(soil_dir.glob("*.nc"))

    if not nc_files:
        _log.error(
            "No .nc files in '%s'. "
            "Download ERA5-Land swvl1/swvl2/swvl3 from "
            "https://cds.climate.copernicus.eu",
            soil_dir,
        )
        return None

    _log.info("  ERA5: found %d .nc file(s) in '%s'.", len(nc_files), soil_dir)
    _unzip_inplace(soil_dir)

    _log.info("  Loading with xarray (engine=netcdf4)...")
    try:
        ds = xr.open_mfdataset(
            sorted(str(p) for p in nc_files),
            combine="by_coords",
            engine="netcdf4",
        )
    except Exception as exc:
        _log.error("  xarray open failed: %s", exc, exc_info=True)
        return None

    available = list(ds.data_vars)
    _log.info("  ERA5 variables found: %s", available)

    # Build weighted composite
    composite    = None
    total_weight = 0.0
    for var, weight in _LAYER_WEIGHTS.items():
        if var not in available:
            _log.warning("  Layer %s not found — contribution skipped.", var)
            continue
        composite     = ds[var] * weight if composite is None else composite + ds[var] * weight
        total_weight += weight
        _log.info("  Using %s (weight=%.2f, covers %.0f cm)", var, weight, weight * 100)

    if composite is None:
        _log.error(
            "No ERA5 soil layers found. "
            "Expected: swvl1, swvl2, swvl3. Got: %s", available,
        )
        return None

    if total_weight < 0.99:
        _log.warning(
            "  Only %.0f%% of root zone represented. Re-normalising.",
            total_weight * 100,
        )
        composite = composite / total_weight

    ds_out = composite.to_dataset(name="sm_rootzone")
    _log.info("  Aggregating to daily mean...")
    ds_daily = ds_out.resample(valid_time="1D").mean()

    n_days = len(ds_daily["valid_time"])
    lat_range = ds_daily["latitude"].values[[0, -1]]
    lon_range = ds_daily["longitude"].values[[0, -1]]
    _log.info(
        "  ERA5 ready: %d days | lat [%.2f, %.2f] | lon [%.2f, %.2f]",
        n_days, *lat_range, *lon_range,
    )
    return ds_daily


def extract_district_series(ds_daily, district: str, lat: float, lon: float):
    """
    Extracts daily root-zone SM series for the nearest ERA5 grid point.

    Returns:
        DataFrame with columns [date, sm_rootzone_m3m3]
    """
    import pandas as pd

    try:
        series = ds_daily["sm_rootzone"].sel(
            latitude=lat, longitude=lon, method="nearest"
        )
        df = series.to_dataframe().reset_index()
        df.rename(
            columns={"valid_time": "date", "sm_rootzone": "sm_rootzone_m3m3"},
            inplace=True,
        )
        df["date"] = pd.to_datetime(df["date"])
        _log.debug(
            "  [%s] Extracted %d SM values (nearest grid: %.2f, %.2f).",
            district, len(df), lat, lon,
        )
        return df[["date", "sm_rootzone_m3m3"]].copy()
    except Exception as exc:
        _log.error("  [%s] Extraction failed: %s", district, exc)
        return None
