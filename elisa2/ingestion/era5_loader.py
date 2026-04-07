# era5_loader.py
"""
ingestion/era5_loader.py
─────────────────────────
Loads ERA5-Land monthly NetCDF files and computes a weighted
root-zone soil moisture composite from three soil layers.

Handles file layout:
    swvl1: soil_moisture_YYYY-MM.nc          (no suffix)
    swvl2: soil_moisture_YYYY-MM_swvl2.nc
    swvl3: soil_moisture_YYYY-MM_swvl3.nc

Layer weights (FAO-56, 100 cm wheat root zone):
    swvl1:  0–7 cm    weight = 0.07
    swvl2:  7–28 cm   weight = 0.21
    swvl3: 28–100 cm  weight = 0.72
"""

from __future__ import annotations
from pathlib import Path
from typing import Optional
from config.settings import settings

_log = settings.get_logger(__name__)

_WEIGHTS = {"swvl1": 0.07, "swvl2": 0.21, "swvl3": 0.72}


def _load_layer(files: list, layer_name: str):
    """Opens one layer's monthly files and returns a daily-aggregated DataArray."""
    import xarray as xr

    if not files:
        return None

    _log.info("  Loading %s from %d files...", layer_name, len(files))

    try:
        ds = xr.open_mfdataset(
            [str(f) for f in sorted(files)],
            combine="by_coords",
            engine="netcdf4",
            decode_times=True,
        )
    except Exception as exc:
        _log.warning(
            "  open_mfdataset failed for %s: %s. Trying one-by-one.", layer_name, exc
        )
        datasets = []
        for f in sorted(files):
            try:
                datasets.append(xr.open_dataset(str(f), engine="netcdf4"))
            except Exception as e2:
                _log.warning("    Skipping %s: %s", f.name, e2)
        if not datasets:
            return None
        ds = xr.concat(datasets, dim="valid_time")

    # Find the SM variable — could be swvl1/2/3 or volumetric_soil_water_layer_N
    var_candidates = [
        layer_name,
        f"volumetric_soil_water_layer_{layer_name[-1]}",
    ]
    var_name = None
    for candidate in var_candidates:
        if candidate in ds.data_vars:
            var_name = candidate
            break

    if var_name is None:
        _log.error(
            "  Cannot find SM variable in %s files. Available: %s",
            layer_name, list(ds.data_vars),
        )
        return None

    _log.info("  Variable name: '%s'", var_name)

    # Normalise time dimension name
    for tname in ["time", "forecast_reference_time"]:
        if tname in ds.dims:
            ds = ds.rename({tname: "valid_time"})
            break

    # Aggregate hourly → daily
    da = ds[var_name].resample(valid_time="1D").mean()

    t = da["valid_time"]
    _log.info(
        "  %s: %d daily values, %s → %s",
        layer_name, len(t),
        str(t.values[0])[:10],
        str(t.values[-1])[:10],
    )
    return da


def load(soil_dir: Optional[Path] = None):
    """
    Loads all three ERA5-Land SM layers, builds weighted composite,
    returns daily-aggregated xarray Dataset with variable 'sm_rootzone'.

    Falls back gracefully if swvl2/swvl3 are not yet downloaded
    (re-normalises weights for available layers only).
    """
    try:
        import xarray as xr
        import numpy as np
    except ImportError:
        _log.error("xarray not installed. Run: pip install xarray netcdf4")
        return None

    soil_dir = soil_dir or (settings.data_dir / "soil_moisture_data")

    if not soil_dir.exists():
        _log.error("Soil moisture directory not found: %s", soil_dir)
        return None

    # File discovery per layer
    layer_files = {
        "swvl1": sorted([
            f for f in soil_dir.glob("soil_moisture_????-??.nc")
            if "_swvl" not in f.name and f.name != "data_0.nc"
        ]),
        "swvl2": sorted(soil_dir.glob("soil_moisture_????-??_swvl2.nc")),
        "swvl3": sorted(soil_dir.glob("soil_moisture_????-??_swvl3.nc")),
    }

    for layer, files in layer_files.items():
        _log.info("  %s: %d files found", layer, len(files))

    if not layer_files["swvl1"]:
        _log.error(
            "No swvl1 files found. Expected: soil_moisture_YYYY-MM.nc\n"
            "  Files in dir: %s",
            [f.name for f in soil_dir.iterdir()][:10],
        )
        return None

    missing = [l for l, files in layer_files.items() if not files]
    if missing:
        _log.warning(
            "Missing layers: %s — proceeding with available layers only. "
            "Run download_era5.py to download them.",
            missing,
        )

    # Load each available layer
    layers = {}
    for layer_name, files in layer_files.items():
        if files:
            da = _load_layer(files, layer_name)
            if da is not None:
                layers[layer_name] = da

    if not layers:
        _log.error("No layers could be loaded.")
        return None

    _log.info("  Successfully loaded layers: %s", list(layers.keys()))

    # Build weighted composite — re-normalise if layers are missing
    available_weights = {k: _WEIGHTS[k] for k in layers}
    total_weight      = sum(available_weights.values())

    if total_weight < 0.99:
        _log.warning(
            "Only %.0f%% of root zone represented (missing: %s). Re-normalising.",
            total_weight * 100,
            [l for l in _WEIGHTS if l not in layers],
        )

    composite = None
    for layer_name, da in layers.items():
        weight    = available_weights[layer_name] / total_weight
        composite = da * weight if composite is None else composite + da * weight
        _log.info(
            "  %s × %.4f (normalised from %.2f)",
            layer_name, weight, _WEIGHTS[layer_name],
        )

    ds_out = composite.to_dataset(name="sm_rootzone")
    n_days = len(ds_out["valid_time"])

    try:
        lat = ds_out["latitude"].values
        lon = ds_out["longitude"].values
        _log.info(
            "  Composite ready: %d daily steps | "
            "lat [%.2f–%.2f] | lon [%.2f–%.2f]",
            n_days,
            float(lat.min()), float(lat.max()),
            float(lon.min()), float(lon.max()),
        )
    except Exception:
        _log.info("  Composite ready: %d daily steps.", n_days)

    return ds_out


def extract_district_series(ds_daily, district: str, lat: float, lon: float):
    """
    Extracts daily root-zone SM for the nearest ERA5 grid point.
    Returns DataFrame with columns ['date', 'sm_rootzone_m3m3'].
    """
    import pandas as pd

    lat_coord = next((n for n in ["latitude", "lat"] if n in ds_daily.coords), None)
    lon_coord = next((n for n in ["longitude", "lon"] if n in ds_daily.coords), None)

    if lat_coord is None or lon_coord is None:
        _log.error(
            "[%s] No lat/lon coords found. Coords: %s",
            district, list(ds_daily.coords),
        )
        return None

    try:
        series = ds_daily["sm_rootzone"].sel(
            {lat_coord: lat, lon_coord: lon},
            method="nearest",
        )
        df = series.to_dataframe().reset_index()
        df = df.rename(columns={"valid_time": "date", "sm_rootzone": "sm_rootzone_m3m3"})
        df["date"] = pd.to_datetime(df["date"])
        df = (
            df[["date", "sm_rootzone_m3m3"]]
            .dropna()
            .sort_values("date")
            .reset_index(drop=True)
        )

        _log.info(
            "  [%s] %d daily values | SM %.4f–%.4f m³/m³ | nearest: %.2f°N %.2f°E",
            district, len(df),
            float(df["sm_rootzone_m3m3"].min()),
            float(df["sm_rootzone_m3m3"].max()),
            lat, lon,
        )
        return df

    except Exception as exc:
        # Fixed: was `_log.error(..., exc_info=True)` without `exc` — silent errors
        _log.error("[%s] Extraction failed: %s", district, exc, exc_info=True)
        return None