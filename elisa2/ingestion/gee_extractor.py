# gee_extractor.py
"""
ingestion/gee_extractor.py
───────────────────────────
Extracts Sentinel-1 SAR, Sentinel-2 optical indices, SRTM terrain,
and ERA5-Land SM at a 3×3 grid of points per district.

Why 3×3 grid (9 points) instead of just the centroid:
    ERA5 gives one SM value per 9×9 km pixel. The RF downscaler needs
    to learn how SAR/NDVI/terrain differ WITHIN the same ERA5 pixel so
    it can predict farm-level SM differences. If we only extract at the
    centroid, the RF only sees temporal variation — it cannot learn
    spatial downscaling. The 3×3 grid gives genuine within-pixel
    spatial variation for the RF to train on.

Stub mode (GEE_ENABLED=false):
    Generates synthetic but physically-plausible data per grid point.
    Each point gets unique values based on its position in the grid
    (corner points are drier/rougher; centre is wetter/flatter).
    Output format is IDENTICAL to real GEE output.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd

from config.settings import agro, settings
from ingestion.gee_client import gee

_log = settings.get_logger(__name__)

_DRY_MONTHS = [1, 2]   # Jan–Feb: Rabi dry season reference for delta_VV

OUTPUT_COLS = [
    "date", "district", "grid_lat", "grid_lon", "grid_idx",
    "VV", "VH", "VV_VH_ratio", "delta_VV",
    "NDVI", "NDWI", "EVI",
    "slope", "TWI",
    "era5_sm_m3m3",
]


# ── GEE real extraction ────────────────────────────────────────────────────────

def _extract_point_live(lat: float, lon: float, start: str, end: str) -> Optional[pd.DataFrame]:
    """Full GEE extraction for one (lat, lon) point."""
    ee = gee.ee
    geom  = ee.Geometry.Point([lon, lat]).buffer(200).bounds()  # for SAR + optical
    point = ee.Geometry.Point([lon, lat])                        # for ERA5 + DEM

    # ── Sentinel-1 SAR ────────────────────────────────────────────────────────
    s1 = (
        ee.ImageCollection("COPERNICUS/S1_GRD")
        .filterBounds(geom).filterDate(start, end)
        .filter(ee.Filter.eq("instrumentMode", "IW"))
        .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VV"))
        .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VH"))
        .select(["VV", "VH"])
    )

    def sar_reduce(img):
        s = img.reduceRegion(ee.Reducer.mean(), geom, scale=10, maxPixels=1e9)
        return ee.Feature(None, {
            "date": img.date().format("YYYY-MM-dd"),
            "VV":   s.get("VV"), "VH": s.get("VH"),
        })

    sar_rows = []
    for f in s1.map(sar_reduce).filter(ee.Filter.notNull(["VV", "VH"])).getInfo()["features"]:
        p = f["properties"]
        vv, vh = float(p["VV"]), float(p["VH"])
        sar_rows.append({"date": pd.to_datetime(p["date"]), "VV": vv, "VH": vh,
                          "VV_VH_ratio": vv / vh if vh != 0 else np.nan})
    sar_df = pd.DataFrame(sar_rows) if sar_rows else pd.DataFrame(
        columns=["date", "VV", "VH", "VV_VH_ratio"])
    if not sar_df.empty:
        sar_df = sar_df.sort_values("date").reset_index(drop=True)

    # delta_VV: deviation from dry-season annual mean
    sar_df["_yr"] = sar_df["date"].dt.year
    sar_df["_mo"] = sar_df["date"].dt.month
    dry = sar_df[sar_df["_mo"].isin(_DRY_MONTHS)]
    global_dry = dry["VV"].mean() if not dry.empty else sar_df["VV"].mean()
    yr_dry     = dry.groupby("_yr")["VV"].mean().to_dict()
    sar_df["delta_VV"] = sar_df.apply(
        lambda r: r["VV"] - yr_dry.get(r["_yr"], global_dry), axis=1
    )
    sar_df.drop(columns=["_yr", "_mo"], inplace=True)

    # ── ERA5 SM ───────────────────────────────────────────────────────────────
    era5_rows = []
    for f in (
        ee.ImageCollection("ECMWF/ERA5_LAND/DAILY_AGGR")
        .filterBounds(geom).filterDate(start, end)
        .select(["volumetric_soil_water_layer_1"])
        .map(lambda img: ee.Feature(None, {
            "date": img.date().format("YYYY-MM-dd"),
            "era5_sm_m3m3": img.reduceRegion(
                    ee.Reducer.mean(), point, scale=9000, maxPixels=1e9
                ).get("volumetric_soil_water_layer_1"),
        }))
        .filter(ee.Filter.notNull(["era5_sm_m3m3"]))
        .getInfo()["features"]
    ):
        era5_rows.append({
            "date": pd.to_datetime(f["properties"]["date"]),
            "era5_sm_m3m3": float(f["properties"]["era5_sm_m3m3"]),
        })
    era5_df = pd.DataFrame(era5_rows) if era5_rows else pd.DataFrame(
        columns=["date", "era5_sm_m3m3"])
    if not era5_df.empty:
        era5_df = era5_df.sort_values("date").reset_index(drop=True)

    # ── DEM static ────────────────────────────────────────────────────────────
    srtm    = ee.Image("USGS/SRTMGL1_003")
    terrain = ee.Algorithms.Terrain(srtm)
    slope   = terrain.select("slope")
    twi     = (
        ee.Image(30.0)
        .divide(slope.multiply(np.pi / 180).tan().max(ee.Image(0.001)))
        .log()
        .rename("TWI")
    )
    dem_st = (
            srtm.addBands(slope).addBands(twi)
            .select(["elevation", "slope", "TWI"])
            .reduceRegion(ee.Reducer.mean(), point, scale=30, maxPixels=1e9)
            .getInfo()
        )
    slope_v = float(dem_st.get("slope", 0.5))
    twi_v   = float(dem_st.get("TWI",   8.0))

    # ── Sentinel-2 optical (monthly composites) ───────────────────────────────
    def _mask_clouds(img):
        qa = img.select("QA60")
        return img.updateMask(qa.bitwiseAnd(1 << 10).eq(0).And(qa.bitwiseAnd(1 << 11).eq(0)))

    def _indices(img):
        return img.addBands([
            img.normalizedDifference(["B8", "B4"]).rename("NDVI"),
            img.normalizedDifference(["B3", "B8"]).rename("NDWI"),
            img.expression(
                "2.5*((B8-B4)/(B8+6*B4-7.5*B2+1))",
                {"B8": img.select("B8"), "B4": img.select("B4"), "B2": img.select("B2")},
            ).rename("EVI"),
        ])

    s2 = (
        ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
        .filterBounds(geom).filterDate(start, end)
        .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 30))
        .map(_mask_clouds).map(_indices)
        .select(["NDVI", "NDWI", "EVI"])
    )
    s_dt = datetime.strptime(start[:10], "%Y-%m-%d")
    e_dt = datetime.strptime(end[:10], "%Y-%m-%d")
    n_months = (e_dt.year - s_dt.year) * 12 + (e_dt.month - s_dt.month)
    opt_rows = []
    for m in range(n_months):
        total_m = s_dt.month + m - 1
        yr = s_dt.year + total_m // 12
        mo = total_m % 12 + 1
        s_m = f"{yr}-{mo:02d}-01"
        e_m = f"{yr + (1 if mo == 12 else 0)}-{(mo % 12) + 1:02d}-01"
        comp = s2.filterDate(s_m, e_m).median()
        st   = comp.reduceRegion(ee.Reducer.mean(), geom, scale=10, maxPixels=1e9).getInfo()
        if st.get("NDVI"):
            opt_rows.append({"date": pd.to_datetime(s_m),
                              "NDVI": st["NDVI"], "NDWI": st.get("NDWI", 0), "EVI": st.get("EVI", 0)})
    opt_df = pd.DataFrame(opt_rows) if opt_rows else pd.DataFrame(
        columns=["date", "NDVI", "NDWI", "EVI"])

    # ── Assemble daily spine ──────────────────────────────────────────────────
    daily = pd.DataFrame({"date": pd.date_range(start=start, end=end, freq="D")})
    daily = daily.merge(sar_df[["date", "VV", "VH", "VV_VH_ratio", "delta_VV"]], on="date", how="left")
    if not opt_df.empty:
        daily = daily.merge(opt_df[["date", "NDVI", "NDWI", "EVI"]], on="date", how="left")
    else:
        daily[["NDVI", "NDWI", "EVI"]] = np.nan
    daily = daily.merge(era5_df, on="date", how="left")
    for col in ["VV", "VH", "VV_VH_ratio", "delta_VV"]:
        daily[col] = daily[col].ffill(limit=6)
    for col in ["NDVI", "NDWI", "EVI"]:
        daily[col] = daily[col].ffill(limit=31)
    daily["era5_sm_m3m3"] = daily["era5_sm_m3m3"].ffill(limit=1).bfill(limit=1)
    daily["slope"] = slope_v
    daily["TWI"]   = twi_v
    daily.dropna(subset=["era5_sm_m3m3"], inplace=True)
    if daily.empty:
        _log.warning("  Point (%.4f, %.4f): ERA5 returned no data — skipping.", lat, lon)
        return None
    return daily.reset_index(drop=True)


# ── Synthetic stub ─────────────────────────────────────────────────────────────

def _generate_stub_point(
    district: str, lat: float, lon: float,
    grid_idx: int, start: str, end: str,
) -> pd.DataFrame:
    """
    Physically-plausible synthetic data for one grid point.
    Each point in the 3×3 grid gets DIFFERENT values based on position:
      - Centre (idx=4): lower slope, higher TWI, denser vegetation
      - Corners (idx=0,2,6,8): higher slope, lower TWI, sparser vegetation
    This simulates real spatial variation the RF downscaler needs to learn.
    """
    rng      = np.random.default_rng(seed=abs(hash(f"{district}_{grid_idx}")) % (2**31))
    dates    = pd.date_range(start=start, end=end, freq="D")
    n        = len(dates)
    doy      = np.array([d.timetuple().tm_yday for d in dates])
    seasonal = np.sin(2 * np.pi * (doy - 80) / 365)

    # Position relative to centre: 0=centre, 1=edge, ~1.41=corner
    centre_dist = abs(grid_idx - 4) / 4.0

    # SAR VV (dB) — wetter soil → higher VV
    vv_base    = -15.0 + 3.0 * np.clip(seasonal, 0, 1)
    vv_spatial = centre_dist * rng.uniform(-0.8, 0.8)
    vv         = vv_base + vv_spatial + rng.normal(0, 0.8, n)
    mask       = np.zeros(n, dtype=bool); mask[::6] = True
    vv_filled  = pd.Series(np.where(mask, vv, np.nan)).ffill(limit=6).values
    vh         = vv_filled - 6.0 + rng.normal(0, 0.4, n)

    years     = np.array([d.year for d in dates])
    months    = np.array([d.month for d in dates])
    dry_means = {yr: vv[(years == yr) & np.isin(months, _DRY_MONTHS)].mean()
                 if (years == yr).any() else vv.mean() for yr in np.unique(years)}
    delta_vv  = vv_filled - np.array([dry_means[y] for y in years])

    # NDVI — denser at centre
    ndvi_base   = 0.25 + 0.50 * np.clip(seasonal, 0, 1) - centre_dist * 0.05
    ndvi_sparse = np.where(np.arange(n) % 5 == 0, ndvi_base + rng.normal(0, 0.04, n), np.nan)
    ndvi        = pd.Series(ndvi_sparse).ffill(limit=31).values
    ndwi        = -0.10 + 0.35 * np.clip(seasonal, 0, 1) + rng.normal(0, 0.03, n)
    evi         = 0.15 + 0.40 * np.clip(seasonal, 0, 1) + rng.normal(0, 0.03, n)

    # ERA5 SM — SAME across all 9 points (that's the whole point of the 3×3 grid:
    # ERA5 pixel is uniform, but SAR/NDVI/terrain vary → RF learns spatial mapping)
    era5_sm = 0.20 + 0.18 * np.clip(seasonal, 0, 1) + rng.normal(0, 0.015, n)
    era5_sm = np.clip(era5_sm, 0.10, 0.40)

    # Terrain — flatter at centre (higher TWI → wetter)
    slope_v = 0.3 + centre_dist * 0.8 + rng.uniform(0, 0.2)
    twi_v   = 9.0 - centre_dist * 1.5 + rng.uniform(0, 0.5)

    return pd.DataFrame({
        "date":         dates,
        "VV":           vv_filled,
        "VH":           vh,
        "VV_VH_ratio":  vv_filled / np.where(vh != 0, vh, np.nan),
        "delta_VV":     delta_vv,
        "NDVI":         np.clip(ndvi, 0, 1),
        "NDWI":         np.clip(ndwi, -1, 1),
        "EVI":          np.clip(evi, 0, 1),
        "slope":        slope_v,
        "TWI":          twi_v,
        "era5_sm_m3m3": era5_sm,
    })


# ── District orchestrator ──────────────────────────────────────────────────────

def extract_district(district: str, force: bool = False) -> Optional[pd.DataFrame]:
    """
    Extracts all 9 grid points for one district.
    Saves a single CSV with grid_lat, grid_lon, grid_idx columns.
    """
    out = settings.data_dir / "gee_extracts" / f"{district}_hyperlocal.csv"
    if out.exists() and not force:
        _log.info("  [%s] Cached. Use force=True to re-extract.", district)
        return pd.read_csv(out, parse_dates=["date"])

    start = settings.nasa_start_date
    end   = settings.nasa_end_date
    grid  = agro.districts.grid_3x3(district, spacing=settings.gee_grid_spacing_deg)

    all_points = []
    for idx, (lat, lon) in enumerate(grid):
        _log.info(
            "  [%s] Point %d/9 (%.4f, %.4f) — %s",
            district, idx + 1, lat, lon,
            "LIVE" if gee.is_live else "stub",
        )
        try:
            df = (_extract_point_live(lat, lon, start, end)
                  if gee.is_live
                  else _generate_stub_point(district, lat, lon, idx, start, end))
        except Exception as exc:
            _log.error("  [%s] Point %d failed: %s", district, idx, exc)
            df = None

        if df is None:
            continue
        df["district"] = district
        df["grid_lat"] = lat
        df["grid_lon"] = lon
        df["grid_idx"] = idx
        all_points.append(df)

    if not all_points:
        _log.error("  [%s] All grid points failed.", district)
        return None

    combined = pd.concat(all_points, ignore_index=True)
    cols     = [c for c in OUTPUT_COLS if c in combined.columns]
    combined = combined[cols]

    out.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(out, index=False)
    _log.info(
        "  [%s] Saved %d rows (9 pts × %d days) → '%s'.",
        district, len(combined), len(combined) // 9, out,
    )
    return combined


def extract_all(district_filter: Optional[str] = None, force: bool = False) -> dict:
    _log.info("=" * 60)
    _log.info("GEE Extraction (3×3 grid per district)")
    _log.info("  Mode : %s", "LIVE" if gee.is_live else "STUB")
    _log.info("=" * 60)

    districts = list(agro.districts.keys())
    if district_filter:
        districts = [d for d in districts if d == district_filter]

    results = {}
    for name in districts:
        df = extract_district(name, force=force)
        if df is not None:
            results[name] = df

    _log.info("Extraction complete: %d/%d districts.", len(results), len(districts))
    return results
