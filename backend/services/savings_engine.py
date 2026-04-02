# Paste contents from the generated services/savings_engine.py here
# backend/services/savings_engine.py
"""
Savings Engine — compares a real farmer's confirmed irrigation history
against the "Blind" farmer simulation baseline from elisa2.

The key insight:
    - Blind farmer irrigates every 10 days, 80 mm regardless of anything.
    - ELISA farmer irrigates only when MPC says to.
    - We run blind_simulate() on the same weather data and count the
      difference in water applied, energy used, and money spent.

Season detection:
    Kharif (Rice)  : June–October    → "Kharif-YYYY"
    Rabi   (Wheat) : November–April  → "Rabi-YYYY"    (labelled by end year)

This module is called:
    1. After every confirm-irrigation event (incremental update)
    2. By the daily scheduler job (full recompute)
    3. By the /savings endpoint (read-cached + trigger recompute if stale)
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Optional
import pandas as pd

_log = logging.getLogger(__name__)

# ── elisa2 imports (via ml_bridge path injection which runs first) ─────────────
# ml_bridge must have been imported before this module to ensure sys.path
# contains elisa2/. In practice FastAPI imports services alphabetically,
# so we re-inject here defensively.

import sys
from pathlib import Path


def _ensure_elisa2_on_path() -> None:
    from core.config import get_settings
    root_str = str(get_settings().elisa2_root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)


_ensure_elisa2_on_path()

from config.settings import agro, settings as elisa_settings           # noqa: E402
from simulation.farmer_blind import simulate as blind_simulate          # noqa: E402
from simulation.metrics import compute as compute_metrics               # noqa: E402
from utils.dates import read_csv                                        # noqa: E402


# ── Season helpers ─────────────────────────────────────────────────────────────

def current_season(reference: Optional[date] = None) -> str:
    """
    Returns the season label for a given date.
    Examples:
        date(2025,  3, 15) → "Rabi-2025"
        date(2025,  8, 10) → "Kharif-2025"
        date(2024, 11, 20) → "Rabi-2025"   (Rabi starts Nov, labelled by harvest year)
    """
    d = reference or date.today()
    m = d.month
    if 6 <= m <= 10:
        return f"Kharif-{d.year}"
    # Rabi: Nov–Apr, label year = year of April harvest
    label_year = d.year + 1 if m >= 11 else d.year
    return f"Rabi-{label_year}"


def season_date_range(season: str) -> tuple[date, date]:
    """
    Returns (start_date, end_date) for a season label.
    Examples:
        "Rabi-2025"   → (2024-11-01, 2025-04-30)
        "Kharif-2025" → (2025-06-01, 2025-10-31)
    """
    kind, year_str = season.split("-")
    year = int(year_str)
    if kind == "Kharif":
        return date(year, 6, 1), date(year, 10, 31)
    else:  # Rabi
        return date(year - 1, 11, 1), date(year, 4, 30)


# ── Blind baseline ─────────────────────────────────────────────────────────────

def _get_blind_baseline(district: str, season: str) -> dict:
    """
    Runs the blind farmer simulation on the available dataset for the given
    district and season, returning aggregated metrics.

    Tries real-soil dataset first, falls back to simulated.
    Filters to the season date range for an apples-to-apples comparison.
    """
    path = elisa_settings.real_soil_dataset
    if not path.exists():
        path = elisa_settings.simulated_dataset
        _log.debug("Real-soil dataset absent — using simulated for baseline.")

    if not path.exists():
        _log.error("No dataset found at %s or %s.", elisa_settings.real_soil_dataset, path)
        return _empty_baseline()

    try:
        df = read_csv(path)
    except Exception as exc:
        _log.error("Failed to load dataset: %s", exc)
        return _empty_baseline()

    # Filter to district + season window
    start, end = season_date_range(season)
    # Ensure date column is datetime for reliable comparison
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    mask = (
        (df["district"] == district)
        & (df["date"] >= pd.Timestamp(start))
        & (df["date"] <= pd.Timestamp(end))
    )
    season_df = df[mask].copy()

    if season_df.empty:
        _log.warning(
            "No data for district=%s season=%s (%s → %s).",
            district, season, start, end,
        )
        # Fall back: use whatever data exists for this district
        season_df = df[df["district"] == district].copy()
        if season_df.empty:
            return _empty_baseline()

    blind_df  = blind_simulate(season_df, district)
    metrics   = compute_metrics(blind_df, "Blind", district)
    return metrics


def _empty_baseline() -> dict:
    return {
        "farmer": "Blind",
        "district": "unknown",
        "irrigation_events":  36,     # 365 / 10 ≈ fallback
        "water_applied_mm":   2880.0, # 36 × 80 mm
        "energy_kwh":         round(36 * agro.pump.energy_per_run_kwh, 2),
        "cost_inr":           round(
            36 * agro.pump.energy_per_run_kwh
            * (agro.tariff.low + agro.tariff.medium) / 2,
            2,
        ),
        "stress_days": 0,
        "mean_ks":     1.0,
    }


# ── Actual events loader ───────────────────────────────────────────────────────

def _load_actual_events(farm_id: str, season: str) -> dict:
    """
    Reads the farm's confirmed irrigation event log and filters to
    the current season window.

    Returns a dict with:
        events, water_mm, energy_kwh, cost_inr
    """
    events_path = (
        elisa_settings.data_dir / "farm_states" / f"{farm_id}_events.csv"
    )
    if not events_path.exists():
        return {"events": 0, "water_mm": 0.0, "energy_kwh": 0.0, "cost_inr": 0.0}

    try:
        ev_df = read_csv(events_path)
    except Exception as exc:
        _log.error("Failed to load events for farm %s: %s", farm_id, exc)
        return {"events": 0, "water_mm": 0.0, "energy_kwh": 0.0, "cost_inr": 0.0}

    start, end = season_date_range(season)
    mask   = (ev_df["date"].dt.date >= start) & (ev_df["date"].dt.date <= end)
    season_ev = ev_df[mask]

    n_events   = len(season_ev)
    water_mm   = float(season_ev["irrigation_mm"].sum())
    energy_kwh = n_events * agro.pump.energy_per_run_kwh
    tariff_avg = (agro.tariff.low + agro.tariff.medium) / 2
    cost_inr   = energy_kwh * tariff_avg

    return {
        "events":      n_events,
        "water_mm":    round(water_mm,   1),
        "energy_kwh":  round(energy_kwh, 3),
        "cost_inr":    round(cost_inr,   2),
    }


# ── Main public API ────────────────────────────────────────────────────────────

def compute_savings(
    farm_id:  str,
    district: str,
    crop:     str,
    season:   Optional[str] = None,
) -> dict:
    """
    Computes season savings for one farm vs blind baseline.

    Args:
        farm_id  : ELISA farm ID (same UUID string stored in farms table).
        district : Nearest district name.
        crop     : 'Wheat' or 'Rice'.
        season   : Season label e.g. 'Rabi-2025'. Defaults to current season.

    Returns dict:
        {
            season, farm_id, district, crop,
            actual_events,         blind_baseline_events,
            actual_water_mm,       blind_water_mm,
            water_saved_mm,
            actual_energy_kwh,     blind_energy_kwh,
            actual_cost_inr,       blind_cost_inr,
            cost_saved_inr,
            stress_days,           savings_pct_water, savings_pct_cost,
            computed_at,
        }
    """
    season = season or current_season()
    _log.info(
        "Computing savings: farm=%s district=%s season=%s",
        farm_id, district, season,
    )

    baseline = _get_blind_baseline(district, season)
    actual   = _load_actual_events(farm_id, season)

    blind_water = baseline["water_applied_mm"]
    blind_cost  = baseline["cost_inr"]
    blind_kwh   = baseline["energy_kwh"]
    blind_n     = baseline["irrigation_events"]

    actual_water = actual["water_mm"]
    actual_cost  = actual["cost_inr"]
    actual_kwh   = actual["energy_kwh"]
    actual_n     = actual["events"]

    water_saved = max(0.0, blind_water - actual_water)
    cost_saved  = max(0.0, blind_cost  - actual_cost)

    savings_pct_water = (
        round(water_saved / blind_water * 100, 1) if blind_water > 0 else 0.0
    )
    savings_pct_cost = (
        round(cost_saved / blind_cost * 100, 1) if blind_cost > 0 else 0.0
    )

    result = {
        "season":                 season,
        "farm_id":                farm_id,
        "district":               district,
        "crop":                   crop,
        # Counts
        "actual_events":          actual_n,
        "blind_baseline_events":  blind_n,
        # Water
        "actual_water_mm":        actual_water,
        "blind_water_mm":         round(blind_water, 1),
        "water_saved_mm":         round(water_saved, 1),
        # Energy
        "actual_energy_kwh":      actual_kwh,
        "blind_energy_kwh":       round(blind_kwh, 3),
        # Cost
        "actual_cost_inr":        actual_cost,
        "blind_cost_inr":         round(blind_cost, 2),
        "cost_saved_inr":         round(cost_saved, 2),
        # Health
        "stress_days":            baseline.get("stress_days", 0),
        # Percentage savings
        "savings_pct_water":      savings_pct_water,
        "savings_pct_cost":       savings_pct_cost,
        "computed_at":            datetime.now(timezone.utc).isoformat(),
    }

    _log.info(
        "Savings result: farm=%s season=%s water_saved=%.1fmm cost_saved=₹%.0f",
        farm_id, season, water_saved, cost_saved,
    )
    return result


def compute_all_seasons(
    farm_id:  str,
    district: str,
    crop:     str,
    n_seasons: int = 4,
) -> list[dict]:
    """
    Returns savings history for the last N seasons.
    Useful for the savings history chart in the frontend.

    Args:
        n_seasons: How many seasons back to compute (default 4 = ~2 years).
    """
    results = []
    today   = date.today()

    for i in range(n_seasons):
        # Walk backwards: current season, then subtract ~6 months each time
        # by picking the first of the month 6*i months ago
        month_offset = i * 6
        m = today.month - month_offset
        y = today.year
        while m <= 0:
            m += 12
            y -= 1
        ref = date(y, m, 1)
        season = current_season(ref)
        # Deduplicate — multiple refs in the same season window map to the same label
        if season not in [r["season"] for r in results]:
            try:
                s = compute_savings(farm_id, district, crop, season)
                results.append(s)
            except Exception as exc:
                _log.error("Failed to compute savings for season %s: %s", season, exc)

    return results