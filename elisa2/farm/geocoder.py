# geocoder.py
"""
farm/geocoder.py
─────────────────
Village geocoding via Nominatim (OpenStreetMap, free, no API key).
Also provides polygon geometry helpers.
"""

import hashlib
import time
from typing import Optional

import numpy as np
import requests

from config.settings import agro, settings

_log = settings.get_logger(__name__)


def geocode(
    village:  str,
    district: str = "",
    state:    str = "Uttar Pradesh",
) -> Optional[dict]:
    """
    Geocodes a village name → (lat, lon) using Nominatim.
    Falls back to district centroid if not found or no internet.
    """
    query = f"{village}, {district}, {state}, India".strip(", ")
    try:
        time.sleep(1.1)   # Nominatim rate limit
        resp = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": query, "format": "json", "limit": 1, "countrycodes": "in"},
            headers={"User-Agent": "ELISA-2.0-Academic/1.0"},
            timeout=10,
        )
        resp.raise_for_status()
        results = resp.json()
        if not results:
            _log.warning("Nominatim: no results for '%s'.", query)
            return _district_fallback(district)
        r = results[0]
        return {"lat": float(r["lat"]), "lon": float(r["lon"]), "name": r["display_name"]}
    except requests.exceptions.ConnectionError:
        _log.warning("Nominatim: no connection. Using district centroid.")
        return _district_fallback(district)
    except Exception as exc:
        _log.error("Geocoding failed: %s", exc)
        return None


def _district_fallback(district: str) -> Optional[dict]:
    try:
        lat, lon = agro.districts[district]
        return {"lat": lat, "lon": lon, "name": f"{district} (centroid)"}
    except KeyError:
        return None


def centroid(coords: list) -> tuple:
    lats = [c[0] for c in coords]
    lons = [c[1] for c in coords]
    return float(np.mean(lats)), float(np.mean(lons))


def area_ha(coords: list) -> float:
    """Shoelace formula — accurate to ~2% for 1–2 ha polygons in UP."""
    if len(coords) < 3:
        return 0.0
    lat0, lon0    = coords[0]
    m_lat         = 111_132.0
    m_lon         = 111_132.0 * np.cos(np.deg2rad(lat0))
    xs = [(c[1] - lon0) * m_lon for c in coords]
    ys = [(c[0] - lat0) * m_lat for c in coords]
    n  = len(xs)
    return abs(sum(xs[i] * ys[(i+1) % n] - xs[(i+1) % n] * ys[i] for i in range(n))) / 2 / 10_000


def farm_id(name: str, lat: float, lon: float) -> str:
    return hashlib.md5(f"{name.lower()}{lat:.4f}{lon:.4f}".encode()).hexdigest()[:8]
