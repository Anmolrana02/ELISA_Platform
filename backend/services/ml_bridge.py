# Paste contents from the generated services/ml_bridge.py here
# backend/services/ml_bridge.py
"""
ML Bridge — the single file that connects the web backend to elisa2/.

Design principle: this module owns ALL imports from elisa2/.
No other file in backend/ should import from elisa2/ directly.
If the ML core API changes, fix it here and nowhere else.

Path injection:
    elisa2/ is added to sys.path at module load time.
    This is safe because ml_bridge.py is imported once at startup.
    The elisa2 path is resolved from settings so it works both
    locally (monorepo) and on Render (absolute ELISA2_PATH in .env).

Thread safety:
    The GEE client and PatchTST model are heavy to initialise.
    Both are lazy-loaded and cached at module level on first call.
    FastAPI's async endpoints call predict via run_in_executor so
    the CPU-bound PyTorch inference doesn't block the event loop.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Optional

# ── Inject elisa2/ into sys.path ──────────────────────────────────────────────
# Done at module level (not inside a function) so all subsequent imports
# from elisa2 sub-packages resolve correctly regardless of call order.

def _inject_elisa2_path() -> Path:
    from core.config import get_settings
    root = get_settings().elisa2_root
    root_str = str(root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)
    return root


_ELISA2_ROOT = _inject_elisa2_path()

# ── elisa2 imports (all in one place) ─────────────────────────────────────────
from config.settings import agro, settings as elisa_settings          # noqa: E402
from decision.mpc import (                                             # noqa: E402
    IrrigationDecision,
    IrrigationState,
    decide,
    fetch_rain_forecast,
    run_decision,
)
from decision.state_manager import (                                   # noqa: E402
    get_irrigation_history,
    get_state,
    log_irrigation,
    update_state,
)
from decision.tariff import calculator as tariff_calculator            # noqa: E402

_log = logging.getLogger(__name__)

# Thread pool for CPU-bound PatchTST inference (keeps async loop unblocked)
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="ml_bridge")


# ── Districts ─────────────────────────────────────────────────────────────────

DISTRICTS: dict[str, tuple[float, float]] = {
    name: (lat, lon)
    for name, (lat, lon) in agro.districts.items()
}


def detect_district(lat: float, lon: float) -> str:
    """
    Returns the name of the nearest district centroid.
    Used when registering a farm to auto-assign district.
    """
    best, best_d = "Meerut", float("inf")
    for name, (dlat, dlon) in DISTRICTS.items():
        d = ((lat - dlat) ** 2 + (lon - dlon) ** 2) ** 0.5
        if d < best_d:
            best_d, best = d, name
    return best


# ── Prediction ────────────────────────────────────────────────────────────────

def _run_prediction_sync(
    farm_id: str,
    district: str,
    crop: str,
    on_date: date,
) -> dict:
    """
    Synchronous prediction — runs PatchTST + MPC in a thread.

    Called via asyncio.get_event_loop().run_in_executor() from the
    async wrapper below so it never blocks the FastAPI event loop.

    Returns a fully-serialisable dict (no dataclass objects).
    """
    _log.info(
        "Prediction requested: farm=%s district=%s crop=%s date=%s",
        farm_id, district, crop, on_date,
    )

    decision: Optional[IrrigationDecision] = run_decision(
        district=district,
        farm_id=farm_id,
        on_date=on_date,
        data_source="real",
    )

    if decision is None:
        _log.warning(
            "run_decision returned None for farm=%s — insufficient data.", farm_id
        )
        return {
            "error": "Insufficient data to generate prediction. "
                     "Ensure the real-soil dataset covers this district and date.",
            "farm_id": farm_id,
            "date": on_date.isoformat(),
        }

    result = decision.to_dict()
    result["farm_id"] = farm_id
    result["date"]    = on_date.isoformat()

    # Serialise PumpWindow fields (to_dict() already handles this, but be explicit)
    if decision.window:
        result["pump_start_hour"] = decision.window.start_hour
        result["pump_end_hour"]   = decision.window.end_hour
        result["energy_kwh"]      = decision.window.energy_kwh
        result["cost_inr"]        = decision.window.cost_inr
        result["tariff_slot"]     = decision.window.tariff_slot
    else:
        result.setdefault("pump_start_hour", None)
        result.setdefault("pump_end_hour",   None)
        result.setdefault("energy_kwh",      None)
        result.setdefault("cost_inr",        None)
        result.setdefault("tariff_slot",     None)

    _log.info(
        "Prediction done: farm=%s irrigate=%s window=%s",
        farm_id,
        result["irrigate"],
        f"{result['pump_start_hour']:02d}:00" if result.get("pump_start_hour") is not None else "—",
    )
    return result


async def get_prediction(
    farm_id: str,
    district: str,
    crop: str,
    on_date: Optional[date] = None,
) -> dict:
    """
    Async wrapper — schedules PatchTST + MPC in the thread pool.

    Returns a dict ready for JSON serialisation:
        {
            farm_id, date,
            irrigate:         bool,
            reason:           str,
            sm_forecast:      list[float] | None,  # 7 days in mm
            pump_start_hour:  int | None,
            pump_end_hour:    int | None,
            energy_kwh:       float | None,
            cost_inr:         float | None,
            tariff_slot:      str | None,
        }
    """
    target_date = on_date or date.today()
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        _executor,
        _run_prediction_sync,
        farm_id,
        district,
        crop,
        target_date,
    )


def get_sm_forecast_sync(
    farm_id: str,
    district: str,
    on_date: date,
    data_source: str = "real",
) -> list[float]:
    """
    Returns the raw 7-day SM forecast list (mm) without the MPC decision.
    Used by the savings engine and directly by the /forecast endpoint.
    Falls back to ETo-decay if PatchTST checkpoint is unavailable.
    """
    from decision.mpc import _get_forecast

    # Get current SM from state manager or dataset
    state = get_state(farm_id)
    current_sm = float(state["sm_mm"]) if state and state.get("sm_mm") else _fallback_sm(district)

    return _get_forecast(
        district=district,
        farm_id=farm_id,
        on_date=on_date,
        data_source=data_source,
        current_sm=current_sm,
    )


def _fallback_sm(district: str) -> float:
    """Returns field-capacity SM as a conservative fallback."""
    return float(agro.crops["Wheat"].fc_mm)


# ── Rain forecast (async — calls OpenMeteo) ───────────────────────────────────

async def get_rain_forecast(
    lat: float,
    lon: float,
    days: int = 2,
) -> list[float]:
    """
    Fetches hourly rain forecast from OpenMeteo.
    Returns list of hourly values (days × 24 elements).
    Never raises — returns zeros on failure (conservative).
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        _executor,
        fetch_rain_forecast,
        lat, lon, days,
    )


# ── Irrigation feedback loop ──────────────────────────────────────────────────

def confirm_irrigation(
    farm_id: str,
    district: str,
    on_date: date,
    mm: float,
) -> dict:
    """
    Records a confirmed irrigation event and runs a FAO-56 physics
    correction so tomorrow's PatchTST input reflects the new SM.

    Returns the updated state dict:
        {sm_mm, date, irrigation_mm, precip_mm, eto_mm, crop, ...}
    """
    _log.info(
        "Logging irrigation: farm=%s district=%s date=%s mm=%.1f",
        farm_id, district, on_date, mm,
    )
    log_irrigation(farm_id, on_date, mm)
    state = update_state(farm_id, district, on_date)
    _log.info(
        "State updated: farm=%s new_sm=%.1f mm",
        farm_id, state["sm_mm"],
    )
    return state


def get_farm_state(farm_id: str) -> Optional[dict]:
    """
    Returns the latest physics-corrected state for a farm, or None.

    State keys: farm_id, district, date, sm_mm, irrigation_mm,
                precip_mm, eto_mm, crop, sm_yesterday_mm
    """
    return get_state(farm_id)


def get_farm_irrigation_history(farm_id: str, days: int = 60):
    """
    Returns a DataFrame of the last N days of logged irrigation events.
    Columns: date, irrigation_mm, source
    """
    return get_irrigation_history(farm_id, days=days)


# ── Agronomy constants (for frontend display) ─────────────────────────────────

def get_agronomy_constants() -> dict:
    """
    Returns crop thresholds, pump specs, and tariff rates.
    Consumed by the frontend to draw trigger lines on SM charts.
    """
    wheat = agro.crops["Wheat"]
    rice  = agro.crops["Rice"]
    pump  = agro.pump
    tariff = agro.tariff

    return {
        "crops": {
            "Wheat": {
                "trigger_mm": round(wheat.trigger_mm, 1),
                "fc_mm":      round(wheat.fc_mm,      1),
                "pwp_mm":     round(wheat.pwp_mm,     1),
                "irr_amount_mm": wheat.irr_amount_mm,
                "root_depth_mm": wheat.root_depth_mm,
                "growing_months": wheat.growing_months,
            },
            "Rice": {
                "trigger_mm":     round(rice.trigger_mm, 1),
                "ponding_target_mm": rice.ponding_target_mm,
                "irr_amount_mm":  rice.ponding_target_mm,
                "root_depth_mm":  rice.root_depth_mm,
                "growing_months": rice.growing_months,
            },
        },
        "pump": {
            "power_hp":          pump.power_hp,
            "power_kw":          round(pump.power_kw, 3),
            "efficiency":        pump.efficiency,
            "run_duration_h":    pump.run_duration_h,
            "energy_per_run_kwh": round(pump.energy_per_run_kwh, 3),
        },
        "tariff": {
            "low":    tariff.low,
            "medium": tariff.medium,
            "peak":   tariff.peak,
            "cheapest_window": _cheapest_window_info(),
        },
        "districts": {
            name: {"lat": lat, "lon": lon}
            for name, (lat, lon) in DISTRICTS.items()
        },
    }


def _cheapest_window_info() -> dict:
    w = tariff_calculator.cheapest_window(duration_h=2)
    return {
        "start_hour":  w.start_hour,
        "end_hour":    w.end_hour,
        "tariff_slot": w.tariff_slot,
        "cost_inr":    w.cost_inr,
        "energy_kwh":  w.energy_kwh,
    }


# ── Health check ──────────────────────────────────────────────────────────────

def check_ml_health() -> dict:
    """
    Returns a status dict for the /health endpoint.
    Checks: elisa2 path, dataset presence, model checkpoints.
    """
    status = {
        "elisa2_root":             str(_ELISA2_ROOT),
        "elisa2_exists":           _ELISA2_ROOT.exists(),
        "real_dataset_exists":     elisa_settings.real_soil_dataset.exists(),
        "simulated_dataset_exists": elisa_settings.simulated_dataset.exists(),
        "patchtst_checkpoint":     elisa_settings.patchtst_checkpoint.exists(),
        "rf_checkpoint":           elisa_settings.downscaler_checkpoint.exists(),
        "gee_ready":               elisa_settings.gee_is_ready,
    }
    status["overall"] = (
        status["elisa2_exists"]
        and (status["real_dataset_exists"] or status["simulated_dataset_exists"])
    )
    return status