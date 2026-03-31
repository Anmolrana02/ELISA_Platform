# mpc.py
"""
decision/mpc.py
────────────────
48-hour Model Predictive Control irrigation optimizer.

Three conditions evaluated in sequence:

    C1 — SM forecast (48h lookahead from PatchTST days 1–2):
         If SM stays above trigger for both days → skip.

    C2 — Rain suppression:
         If >5mm rain forecast in next 24h → skip.

    C3 — Cost optimization:
         Irrigation confirmed. Find cheapest 2-hour pump window
         using UPPCL ToU tariff schedule.

This is classical control (heuristic optimisation), NOT reinforcement
learning. MPC is appropriate because:
    - Training data is too sparse for a DRL agent (~50 farm-years)
    - Decision logic must be explainable to farmers
    - Deterministic rules are auditable by agriculture supervisors
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from sys import path
from typing import Optional

import pandas as pd
from utils.dates import read_csv

import requests

from config.settings import agro, settings
from decision.tariff import PumpWindow, calculator

_log = settings.get_logger(__name__)


# ── Data classes ───────────────────────────────────────────────────────────────

@dataclass
class IrrigationState:
    """Current farm conditions passed to the optimizer."""
    district:          str
    crop:              str
    current_sm_mm:     float
    sm_forecast_7day:  list[float]
    rain_forecast_48h: list[float]
    decision_date:     date


@dataclass
class IrrigationDecision:
    """Full output from the MPC optimizer."""
    irrigate:    bool
    reason:      str
    window:      Optional[PumpWindow] = None

    def to_dict(self) -> dict:
        d = {"irrigate": self.irrigate, "reason": self.reason}
        if self.window:
            d.update({
                "start_hour":  self.window.start_hour,
                "end_hour":    self.window.end_hour,
                "energy_kwh":  self.window.energy_kwh,
                "cost_inr":    self.window.cost_inr,
                "tariff_slot": self.window.tariff_slot,
            })
        return d

    def pretty(self) -> str:
        sep = "=" * 56
        lines = [
            sep,
            "  ELISA 2.0 — MPC IRRIGATION DECISION",
            sep,
            f"  Decision  : {'*** IRRIGATE ***' if self.irrigate else 'Skip — no irrigation needed'}",
            f"  Reason    : {self.reason}",
        ]
        if self.irrigate and self.window:
            lines += [
                f"  Window    : {self.window.pretty()}",
            ]
        lines.append(sep)
        return "\n".join(lines)


# ── Rain forecast ─────────────────────────────────────────────────────────────

def fetch_rain_forecast(lat: float, lon: float, days: int = 2) -> list[float]:
    """
    Fetches hourly precipitation forecast from OpenMeteo (free, no key).
    Falls back to zeros on API failure (conservative — will not skip irrigation
    incorrectly, only potentially irrigate when rain was coming).
    """
    try:
        resp = requests.get(
            settings.openmeteo_forecast_url,
            params={
                "latitude":      lat,
                "longitude":     lon,
                "hourly":        "precipitation",
                "forecast_days": days,
                "timezone":      "Asia/Kolkata",
            },
            timeout=10,
        )
        resp.raise_for_status()
        rain = [float(v or 0.0) for v in resp.json()["hourly"]["precipitation"]]
        _log.debug("Rain forecast: %d hours, total=%.1f mm.", len(rain), sum(rain))
        return rain
    except requests.exceptions.ConnectionError:
        _log.warning("OpenMeteo unreachable. Using zero rain — conservative fallback.")
        return [0.0] * (days * 24)
    except Exception as exc:
        _log.warning("Rain forecast failed (%s). Using zeros.", exc)
        return [0.0] * (days * 24)


# ── Core MPC logic ─────────────────────────────────────────────────────────────

def decide(state: IrrigationState) -> IrrigationDecision:
    """
    Core MPC decision. Evaluates C1 → C2 → C3 in order.

    Args:
        state : Current farm conditions (SM, forecast, rain).

    Returns:
        IrrigationDecision with full recommendation.
    """
    crop    = agro.get_crop(state.crop)
    trigger = crop.trigger_mm
    rain_th = agro.mpc["rain_suppression_threshold_mm"]

    # ── C1: 48h SM forecast ───────────────────────────────────────────────────
    forecast_48h = state.sm_forecast_7day[:2] if len(state.sm_forecast_7day) >= 2 \
                   else [state.current_sm_mm] * 2
    sm_drops     = any(sm < trigger for sm in forecast_48h)

    _log.debug(
        "C1: trigger=%.1f | day1=%.1f | day2=%.1f | drops=%s",
        trigger, forecast_48h[0], forecast_48h[1], sm_drops,
    )

    if not sm_drops and state.current_sm_mm >= trigger:
        return IrrigationDecision(
            irrigate=False,
            reason=(
                f"SM forecast ({forecast_48h[0]:.0f} mm, {forecast_48h[1]:.0f} mm) "
                f"stays above trigger ({trigger:.0f} mm) for next 48h. "
                f"Current SM: {state.current_sm_mm:.0f} mm."
            ),
        )

    # ── C2: Rain suppression ──────────────────────────────────────────────────
    rain_24h = sum(state.rain_forecast_48h[:24]) if state.rain_forecast_48h else 0.0
    _log.debug("C2: rain_24h=%.1f mm | threshold=%.1f mm", rain_24h, rain_th)

    if rain_24h > rain_th:
        return IrrigationDecision(
            irrigate=False,
            reason=(
                f"Rain forecast: {rain_24h:.1f} mm in next 24h "
                f"(threshold: {rain_th:.0f} mm). Irrigation suppressed."
            ),
        )

    # ── C3: Optimal pump window ───────────────────────────────────────────────
    window = calculator.cheapest_window(duration_h=2)
    _log.debug("C3: best window %02d:00 (%s, ₹%.2f)", window.start_hour, window.tariff_slot, window.cost_inr)

    return IrrigationDecision(
        irrigate=True,
        reason=(
            f"SM forecast drops to {min(forecast_48h):.0f} mm "
            f"(trigger: {trigger:.0f} mm). "
            f"Rain forecast: {rain_24h:.1f} mm only."
        ),
        window=window,
    )


# ── Full decision pipeline ─────────────────────────────────────────────────────

def run_decision(
    district:    str,
    farm_id:     Optional[str] = None,
    on_date:     Optional[date] = None,
    data_source: str = "real",
) -> Optional[IrrigationDecision]:
    """
    Full pipeline: load state → 7-day forecast → rain → decide.

    Args:
        district    : District name.
        farm_id     : Farm ID — enables feedback loop. None = district-level only.
        on_date     : Decision date. None = latest available.
        data_source : 'real' or 'simulated'.
    """
    _log.info("=" * 56)
    _log.info("MPC Decision  district=%s  farm=%s", district, farm_id or "district-level")
    _log.info("=" * 56)

    on_date = on_date or date.today()
    lat, lon = agro.districts[district]

    # ── 1. Current SM ─────────────────────────────────────────────────────────
    if farm_id:
        from decision.state_manager import get_state
        state_data = get_state(farm_id)
        if state_data and state_data.get("sm_mm"):
            current_sm = float(state_data["sm_mm"])
            crop       = str(state_data.get("crop", "Wheat"))
            _log.info("Current SM (farm state): %.1f mm  crop=%s", current_sm, crop)
        else:
            farm_id = None  # fall through

    if not farm_id:
        path = settings.real_soil_dataset if data_source == "real" else settings.simulated_dataset
        df   = read_csv(path)
        recent = df[(df["district"] == district) & (df["date"] <= pd.Timestamp(on_date))].tail(1)
        if recent.empty:
            _log.error("No data found for '%s'.", district)
            return None
        current_sm = float(recent["real_soil_moisture_mm"].iloc[0])
        crop       = str(recent["crop"].iloc[0])
        _log.info("Current SM (ERA5 dataset): %.1f mm  crop=%s", current_sm, crop)

    # ── 2. 7-day forecast ─────────────────────────────────────────────────────
    sm_forecast = _get_forecast(district, farm_id, on_date, data_source, current_sm)
    _log.info("7-day forecast: %s mm", [f"{v:.0f}" for v in sm_forecast])

    # ── 3. Rain forecast ──────────────────────────────────────────────────────
    rain = fetch_rain_forecast(lat, lon, days=2)
    _log.info(
        "Rain: next 24h=%.1f mm | 24–48h=%.1f mm",
        sum(rain[:24]), sum(rain[24:]),
    )

    # ── 4. MPC ────────────────────────────────────────────────────────────────
    state    = IrrigationState(
        district=district, crop=crop,
        current_sm_mm=current_sm,
        sm_forecast_7day=sm_forecast,
        rain_forecast_48h=rain,
        decision_date=on_date,
    )
    decision = decide(state)
    _log.info("\n%s", decision.pretty())
    return decision


def _get_forecast(
    district:    str,
    farm_id:     Optional[str],
    on_date:     date,
    data_source: str,
    current_sm:  float,
) -> list[float]:
    """
    Gets 7-day SM forecast from PatchTST.
    Falls back to simple ETo decay if model is unavailable.
    """
    try:
        import pandas as pd
        from models.patchtst.trainer import load_checkpoint
        from models.patchtst import model as model_mod
        import torch

        ckpt         = load_checkpoint()
        feature_cols = ckpt["feature_cols"]
        n_features   = ckpt["n_features"]
        model        = model_mod.build(n_features)
        model.load_state_dict(ckpt["model_state"])
        model.eval()

        path     = settings.real_soil_dataset if data_source == "real" else settings.simulated_dataset
        df       = read_csv(path)
        d_df     = df[(df["district"] == district) & (df["date"] <= pd.Timestamp(on_date))]

        # Apply feedback loop if farm_id provided
        if farm_id:
            from decision.state_manager import inject_into_window
            d_df = inject_into_window(farm_id, district, d_df)

        sample   = d_df.tail(settings.seq_len)
        if len(sample) < settings.seq_len:
            raise ValueError(f"Only {len(sample)} rows — need {settings.seq_len}.")

        from sklearn.preprocessing import MinMaxScaler
        avail    = [c for c in feature_cols if c in sample.columns]
        scaler   = ckpt["scalers"].get(district, MinMaxScaler())
        if not hasattr(scaler, "mean_"):
            scaler.fit(sample[avail])
        x_scaled = scaler.transform(sample[avail]).astype("float32")
        x_tensor = torch.tensor(x_scaled).unsqueeze(0)

        last     = sample.iloc[-1]
        doy      = int(last["date"].timetuple().tm_yday)
        season   = int(6 <= last["date"].month <= 10)

        with torch.no_grad():
            pred_scaled = model(
                x_tensor,
                torch.tensor([doy],    dtype=torch.long),
                torch.tensor([season], dtype=torch.long),
            ).numpy().ravel()

        tgt_scaler = ckpt["scalers"].get(f"{district}_target", MinMaxScaler())
        if not hasattr(tgt_scaler, "scale_"):
            from models.patchtst.dataset import TARGET
            tgt_scaler.fit(sample[[TARGET]])
        forecast = tgt_scaler.inverse_transform(pred_scaled.reshape(-1, 1)).ravel().tolist()
        return [round(v, 2) for v in forecast]

    except Exception as exc:
        _log.warning("PatchTST forecast unavailable (%s). Using ETo decay.", exc)
        eto_daily = 4.0
        return [max(0.0, current_sm - eto_daily * (i + 1)) for i in range(settings.forecast_horizon)]
