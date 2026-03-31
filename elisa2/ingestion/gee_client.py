# gee_client.py
"""
ingestion/gee_client.py
───────────────────────
GEE authentication and session management.

Handles:
  - Service-account credential loading
  - Singleton ee.Initialize (called once per process)
  - Stub-mode detection (GEE_ENABLED=false → no import of earthengine)
  - Clear error messages for missing credentials
"""

from __future__ import annotations

import threading
from typing import Optional

from config.settings import settings

_log = settings.get_logger(__name__)

# Thread-safe one-time init guard
_lock         = threading.Lock()
_initialised  = False
_stub_warned  = False


class GEEClient:
    """
    Thin wrapper around the Earth Engine API.

    Usage:
        client = GEEClient()
        if client.is_live:
            img = client.ee.Image(...)   # full GEE access
        else:
            # use synthetic stub data
    """

    def __init__(self):
        self._ee        = None
        self._is_live   = False
        self._try_init()

    # ── Public API ────────────────────────────────────────────────────────────

    @property
    def is_live(self) -> bool:
        """True when GEE is enabled AND successfully authenticated."""
        return self._is_live

    @property
    def ee(self):
        """
        Returns the `ee` module for building GEE queries.
        Raises RuntimeError if not authenticated.
        """
        if not self._is_live or self._ee is None:
            raise RuntimeError(
                "GEE is not authenticated. "
                "Set GEE_ENABLED=true + credentials in .env and retry."
            )
        return self._ee

    def test_connection(self) -> dict:
        """
        Smoke-test: fetch ERA5 SM for Meerut on 2024-01-01.
        Returns dict with value if successful, raises on failure.
        """
        if not self._is_live:
            raise RuntimeError("GEE not authenticated.")

        ee = self.ee
        point = ee.Geometry.Point([77.70, 28.98])
        val = (
            ee.ImageCollection("ECMWF/ERA5_LAND/DAILY_AGGR")
            .filterDate("2024-01-01", "2024-01-02")
            .first()
            .select("volumetric_soil_water_layer_1")
            .reduceRegion(ee.Reducer.mean(), point, scale=9000)
            .getInfo()
        )
        _log.info("GEE connection test OK. ERA5 SM (Meerut, 2024-01-01): %s", val)
        return val

    # ── Internal ──────────────────────────────────────────────────────────────

    def _try_init(self) -> None:
        global _initialised, _stub_warned

        if not settings.gee_enabled:
            if not _stub_warned:
                _log.info(
                    "GEE_ENABLED=false → running in STUB mode. "
                    "Set GEE_ENABLED=true + credentials in .env for real satellite data."
                )
                _stub_warned = True
            return

        if not settings.gee_is_ready:
            missing = []
            if not settings.gee_service_account:
                missing.append("GEE_SERVICE_ACCOUNT")
            if not settings.gee_key_file:
                missing.append("GEE_KEY_FILE")
            _log.error(
                "GEE_ENABLED=true but credentials incomplete. "
                "Missing in .env: %s", missing,
            )
            return

        with _lock:
            if _initialised:
                # Another thread already inited — just grab the module
                try:
                    import ee as _ee_mod
                    self._ee      = _ee_mod
                    self._is_live = True
                except ImportError:
                    pass
                return

            try:
                import ee as _ee_mod
                creds = _ee_mod.ServiceAccountCredentials(
                    email    = settings.gee_service_account,
                    key_file = settings.gee_key_file,
                )
                _ee_mod.Initialize(creds)
                self._ee      = _ee_mod
                self._is_live = True
                _initialised  = True
                _log.info(
                    "GEE authenticated as: %s", settings.gee_service_account
                )

            except ImportError:
                _log.error(
                    "earthengine-api not installed. "
                    "Run: pip install earthengine-api"
                )
            except Exception as exc:
                _log.error("GEE authentication failed: %s", exc, exc_info=True)


# Module-level singleton — import this everywhere
gee = GEEClient()
