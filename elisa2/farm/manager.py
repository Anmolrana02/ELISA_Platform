# manager.py
"""
farm/manager.py
────────────────
Farm registration and hyperlocal SM retrieval.

SM priority:
    1. state_manager (physics-corrected, includes logged irrigation)
    2. RF downscaler  (farm-centroid spatial prediction at 100m)
    3. ERA5 district  (9km fallback, always available)
"""

from __future__ import annotations

import json
from datetime import date
from typing import Optional

import pandas as pd
from utils.dates import read_csv

from config.settings import agro, settings
from farm.geocoder import area_ha, centroid, farm_id, geocode

_log  = settings.get_logger(__name__)
_DIR  = settings.data_dir / "farms"


def save(farm: dict) -> None:
    _DIR.mkdir(parents=True, exist_ok=True)
    with open(_DIR / f"{farm['farm_id']}.json", "w") as f:
        json.dump(farm, f, indent=2, default=str)


def load(fid: str) -> Optional[dict]:
    path = _DIR / f"{fid}.json"
    if not path.exists():
        _log.error("Farm '%s' not found.", fid)
        return None
    with open(path) as f:
        return json.load(f)


def list_farms() -> list:
    farms = []
    for p in sorted(_DIR.glob("*.json")):
        try:
            with open(p) as f:
                farms.append(json.load(f))
        except Exception:
            pass
    return farms


def _nearest_district(lat: float, lon: float) -> str:
    best, best_d = "", float("inf")
    for name, (dlat, dlon) in agro.districts.items():
        d = ((lat - dlat)**2 + (lon - dlon)**2)**0.5
        if d < best_d:
            best_d, best = d, name
    return best


class FarmManager:

    def register(
        self,
        name:     str,
        village:  str,
        district: str,
        polygon:  Optional[list] = None,
        crop:     str   = "Wheat",
        pump_hp:  float = 5.0,
        area:     Optional[float] = None,
    ) -> dict:
        """
        Registers a farm. Polygon → centroid + area computed automatically.
        Falls back to Nominatim geocoding if no polygon given.
        """
        if polygon and len(polygon) >= 3:
            lat, lon = centroid(polygon)
            area     = area or area_ha(polygon)
        else:
            geo = geocode(village, district)
            if geo:
                lat, lon = geo["lat"], geo["lon"]
            else:
                lat, lon = agro.districts.get(district, (28.98, 77.70))
            polygon = None
            area    = area or 1.5

        fid = farm_id(name, lat, lon)
        record = {
            "farm_id":           fid,
            "name":              name,
            "village":           village,
            "district":          district,
            "nearest_district":  _nearest_district(lat, lon),
            "centroid_lat":      lat,
            "centroid_lon":      lon,
            "polygon":           polygon,
            "area_ha":           area,
            "crop":              crop,
            "pump_hp":           pump_hp,
            "registered":        date.today().isoformat(),
        }
        save(record)
        _log.info("Registered farm '%s' (ID: %s, %.2f ha).", name, fid, area)
        return record

    def get_sm(
        self,
        farm_id:     str,
        as_of:       Optional[date] = None,
        data_source: str = "real",
    ) -> Optional[dict]:
        """Returns best available SM for the farm with source label."""
        farm = load(farm_id)
        if not farm:
            return None

        lat, lon  = farm["centroid_lat"], farm["centroid_lon"]
        district  = farm["nearest_district"]

        # Priority 1: state_manager
        try:
            from decision.state_manager import get_state
            state = get_state(farm_id)
            if state and state.get("sm_mm"):
                return {"farm_id": farm_id, "farm_name": farm["name"],
                        "sm_mm": float(state["sm_mm"]), "date": state["date"],
                        "source": "state_manager", "lat": lat, "lon": lon}
        except Exception:
            pass

        # Priority 2: RF downscaler
        try:
            import joblib
            from models.downscaler.rf_model import predict_farm_sm
            rf_path = settings.downscaler_checkpoint
            if rf_path.exists():
                rf   = joblib.load(rf_path)
                sm   = predict_farm_sm(rf, lat, lon, district, (as_of or date.today()).isoformat())
                if sm is not None:
                    return {"farm_id": farm_id, "farm_name": farm["name"],
                            "sm_mm": sm, "date": (as_of or date.today()).isoformat(),
                            "source": "rf_downscaled_100m", "lat": lat, "lon": lon}
        except Exception as exc:
            _log.debug("RF fallback failed: %s", exc)

        # Priority 3: ERA5 district average
        try:
            path = settings.real_soil_dataset if data_source == "real" else settings.simulated_dataset
            df   = read_csv(path)
            d_df = df[df["district"] == district]
            if as_of:
                d_df = d_df[d_df["date"] <= pd.Timestamp(as_of)]
            if not d_df.empty:
                latest = d_df.iloc[-1]
                _log.warning("Using 9km district average for farm '%s'.", farm_id)
                return {"farm_id": farm_id, "farm_name": farm["name"],
                        "sm_mm": float(latest["real_soil_moisture_mm"]),
                        "date": str(latest["date"].date()),
                        "source": "era5_district_9km",
                        "warning": "District-level average — run RF downscaler for farm accuracy",
                        "lat": lat, "lon": lon}
        except Exception as exc:
            _log.error("All SM sources failed: %s", exc)

        return None

    def summary(self) -> pd.DataFrame:
        farms = list_farms()
        if not farms:
            return pd.DataFrame()
        return pd.DataFrame([{
            "farm_id": f["farm_id"], "name": f["name"],
            "village": f["village"], "district": f["district"],
            "area_ha": f.get("area_ha"), "crop": f["crop"],
            "lat": f["centroid_lat"], "lon": f["centroid_lon"],
            "registered": f.get("registered"),
        } for f in farms])
