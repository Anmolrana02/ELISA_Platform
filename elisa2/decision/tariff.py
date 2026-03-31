# tariff.py
"""
decision/tariff.py
───────────────────
UPPCL Time-of-Use tariff calculator and optimal pump window finder.

IEX Day-Ahead Market slots (from agronomy.yaml):
    Low    : 00:00 – 06:00  ₹3.50/kWh  (off-peak, best time to pump)
    Medium : 06:00 – 18:00  ₹6.00/kWh
    Peak   : 18:00 – 22:00  ₹9.50/kWh  (never pump here)
    Medium : 22:00 – 24:00  ₹6.00/kWh

Pump model (5 HP centrifugal, standard Western UP smallholder):
    Power    : 5 HP × 0.7457 kW/HP = 3.73 kW
    Efficiency: η = 0.65
    Draw     : pump_kw / η = 5.73 kW effective
    Energy   : draw × duration_h  (kWh)
    Cost     : energy × tariff_rate (₹)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

from config.settings import agro, settings


@dataclass(frozen=True)
class PumpWindow:
    """Result of cheapest_window()."""
    start_hour:     int
    end_hour:       int
    duration_h:     int
    energy_kwh:     float
    cost_inr:       float
    tariff_slot:    str

    def pretty(self) -> str:
        return (
            f"{self.start_hour:02d}:00 – {self.end_hour:02d}:00 "
            f"| {self.tariff_slot} tariff "
            f"| {self.energy_kwh:.3f} kWh "
            f"| ₹{self.cost_inr:.2f}"
        )


class TariffCalculator:
    """
    Calculates pump operating costs and finds the cheapest window.

    Uses pump spec and tariff schedule from config/agronomy.yaml.
    """

    def __init__(self):
        self._pump   = agro.pump
        self._tariff = agro.tariff

    # ── Core calculations ─────────────────────────────────────────────────────

    def energy_kwh(self, duration_h: float) -> float:
        """kWh consumed for a pump run of duration_h hours."""
        return (self._pump.power_kw / self._pump.efficiency) * duration_h

    def cost_for_window(self, start_hour: int, duration_h: int = 2) -> float:
        """Total ₹ cost for a pump run starting at start_hour."""
        draw_kw = self._pump.power_kw / self._pump.efficiency
        return sum(
            draw_kw * self._tariff.rate_for_hour((start_hour + h) % 24)
            for h in range(duration_h)
        )

    def cheapest_window(self, duration_h: int = 2) -> PumpWindow:
        """
        Finds the cheapest contiguous pump window in a 24-hour period.

        Returns a PumpWindow with start time, energy, and cost.
        Almost always returns 00:00–02:00 (low tariff) unless the
        tariff schedule changes.
        """
        best_start, best_cost = 0, float("inf")
        for start in range(24 - duration_h + 1):
            cost = self.cost_for_window(start, duration_h)
            if cost < best_cost:
                best_cost, best_start = cost, start

        end_h  = (best_start + duration_h) % 24
        energy = self.energy_kwh(duration_h)

        return PumpWindow(
            start_hour  = best_start,
            end_hour    = end_h,
            duration_h  = duration_h,
            energy_kwh  = round(energy, 3),
            cost_inr    = round(best_cost, 2),
            tariff_slot = self._tariff.slot_name(best_start),
        )

    def cost_summary(self) -> dict:
        """Returns costs for each tariff slot (for reporting)."""
        energy = self.energy_kwh(self._pump.run_duration_h)
        return {
            "low":    round(energy * self._tariff.low,    2),
            "medium": round(energy * self._tariff.medium, 2),
            "peak":   round(energy * self._tariff.peak,   2),
        }


# Module-level singleton
calculator = TariffCalculator()
