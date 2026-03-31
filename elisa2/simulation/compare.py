# compare.py
"""
simulation/compare.py
──────────────────────
Orchestrates the 3-farmer comparative simulation and generates
4 publication-ready figures.

Output:
    logs/simulation_results.csv
    logs/fig1_cumulative_water.png
    logs/fig2_cumulative_cost.png
    logs/fig3_daily_sm.png
    logs/fig4_savings_bar.png
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from config.settings import agro, settings
from simulation import farmer_blind, farmer_major, farmer_minor
from simulation.metrics import compute

_log = settings.get_logger(__name__)


def run(
    df:               pd.DataFrame,
    district_filter:  Optional[str] = None,
    generate_plots:   bool          = True,
) -> Optional[pd.DataFrame]:
    """
    Runs all 3 farmer simulations for every district (or one filtered district).

    Returns:
        DataFrame of metrics (rows = farmer × district), also saved to CSV.
    """
    _log.info("=" * 62)
    _log.info("3-Farmer Simulation | noise_std=%.1f mm", settings.forecast_noise_std)
    _log.info("=" * 62)

    sim_year = df["date"].dt.year.max()
    df_year  = df[df["date"].dt.year == sim_year].copy()
    _log.info("Simulating year: %d", sim_year)

    districts = list(agro.districts.keys())
    if district_filter:
        districts = [d for d in districts if d == district_filter]

    all_metrics = []
    dfs_b, dfs_m, dfs_M = [], [], []

    for district in districts:
        if district not in df_year["district"].values:
            _log.warning("  [%s] Not in data. Skipping.", district)
            continue

        _log.info("  Simulating %s...", district)
        db = farmer_blind.simulate(df_year, district)
        dm = farmer_minor.simulate(df_year, district)
        dM = farmer_major.simulate(df_year, district)

        for sim, name in [(db, "Blind"), (dm, "ELISA Minor"), (dM, "ELISA Major")]:
            all_metrics.append(compute(sim, name, district))
        dfs_b.append(db); dfs_m.append(dm); dfs_M.append(dM)

        b_w = all_metrics[-3]["water_applied_mm"]
        M_w = all_metrics[-1]["water_applied_mm"]
        _log.info(
            "  [%s] ELISA Major saves %.0f mm water vs Blind.",
            district, b_w - M_w,
        )

    if not all_metrics:
        _log.error("No simulation results generated.")
        return None

    results = pd.DataFrame(all_metrics)

    # Cross-district summary
    _log.info("\n%s", "─" * 62)
    _log.info("  %-14s | %-14s | %-12s | %-12s", "Farmer", "Water (mm)", "Cost (₹)", "Ks")
    for farmer in ["Blind", "ELISA Minor", "ELISA Major"]:
        fdf = results[results["farmer"] == farmer]
        _log.info(
            "  %-14s | %6.0f ± %4.0f | %5.0f ± %4.0f | %.3f ± %.3f",
            farmer,
            fdf["water_applied_mm"].mean(), fdf["water_applied_mm"].std(),
            fdf["cost_inr"].mean(),         fdf["cost_inr"].std(),
            fdf["mean_ks"].mean(),          fdf["mean_ks"].std(),
        )

    out = settings.logs_dir / "simulation_results.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    results.to_csv(out, index=False)
    _log.info("Metrics saved to '%s'.", out)

    if generate_plots and dfs_b:
        _make_figures(
            pd.concat(dfs_b, ignore_index=True),
            pd.concat(dfs_m, ignore_index=True),
            pd.concat(dfs_M, ignore_index=True),
            results, districts,
        )

    return results


def _make_figures(df_b, df_m, df_M, results, districts):
    try:
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates

        C   = {"Blind": "#E24B4A", "ELISA Minor": "#EF9F27", "ELISA Major": "#1D9E75"}
        LW  = 1.8
        tariff_avg = (agro.tariff.low + agro.tariff.medium) / 2
        kwh_per_ev = agro.pump.energy_per_run_kwh

        def cumsum(df, col):
            return df.groupby("date")[col].sum().sort_index().cumsum()

        # ── Fig 1: Cumulative water ───────────────────────────────────────────
        fig, ax = plt.subplots(figsize=(10, 4))
        for d_, name in [(df_b, "Blind"), (df_m, "ELISA Minor"), (df_M, "ELISA Major")]:
            c = cumsum(d_, "irrigation_mm")
            ax.plot(c.index, c.values, color=C[name], lw=LW, label=name)
        ax.set_xlabel("Date"); ax.set_ylabel("Cumulative water (mm)")
        ax.set_title("Cumulative irrigation water — 3 farmer archetypes")
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b"))
        ax.xaxis.set_major_locator(mdates.MonthLocator())
        ax.legend(frameon=False); ax.grid(axis="y", alpha=0.3); plt.tight_layout()
        _savefig(fig, "fig1_cumulative_water.png")

        # ── Fig 2: Cumulative cost ────────────────────────────────────────────
        fig2, ax2 = plt.subplots(figsize=(10, 4))
        for d_, name in [(df_b, "Blind"), (df_m, "ELISA Minor"), (df_M, "ELISA Major")]:
            c = cumsum(d_, "event") * kwh_per_ev * tariff_avg
            ax2.plot(c.index, c.values, color=C[name], lw=LW, label=name)
        ax2.set_xlabel("Date"); ax2.set_ylabel("Cumulative cost (₹)")
        ax2.set_title("Cumulative energy cost — 3 farmer archetypes")
        ax2.xaxis.set_major_formatter(mdates.DateFormatter("%b"))
        ax2.xaxis.set_major_locator(mdates.MonthLocator())
        ax2.legend(frameon=False); ax2.grid(axis="y", alpha=0.3); plt.tight_layout()
        _savefig(fig2, "fig2_cumulative_cost.png")

        # ── Fig 3: Daily SM — example district ───────────────────────────────
        ex = "Meerut" if "Meerut" in districts else districts[0]
        fig3, ax3 = plt.subplots(figsize=(12, 4))
        for d_, name in [(df_b, "Blind"), (df_m, "ELISA Minor"), (df_M, "ELISA Major")]:
            dd = d_[d_["district"] == ex].sort_values("date")
            ax3.plot(dd["date"], dd["sm_mm"], color=C[name], lw=LW, label=name)
        wheat = agro.crops["Wheat"]
        ax3.axhline(wheat.trigger_mm, color="#555", ls="--", lw=1, label=f"Trigger ({wheat.trigger_mm:.0f}mm)")
        ax3.axhline(wheat.pwp_mm,     color="#E24B4A", ls=":", lw=1, label=f"PWP ({wheat.pwp_mm:.0f}mm)")
        ax3.set_xlabel("Date"); ax3.set_ylabel("SM (mm)")
        ax3.set_title(f"Daily soil moisture — {ex}")
        ax3.xaxis.set_major_formatter(mdates.DateFormatter("%b"))
        ax3.xaxis.set_major_locator(mdates.MonthLocator())
        ax3.legend(frameon=False, ncol=2); ax3.grid(axis="y", alpha=0.3); plt.tight_layout()
        _savefig(fig3, "fig3_daily_sm.png")

        # ── Fig 4: Per-district savings bar ───────────────────────────────────
        fig4, axes = plt.subplots(1, 2, figsize=(12, 4))
        for ax4, col, title, unit in [
            (axes[0], "water_applied_mm", "Water applied",  "mm/year"),
            (axes[1], "cost_inr",          "Energy cost",   "₹/year"),
        ]:
            x = np.arange(len(districts)); w = 0.25
            for i, farmer in enumerate(["Blind", "ELISA Minor", "ELISA Major"]):
                vals = [
                    results[(results["farmer"] == farmer) & (results["district"] == d)][col].values[0]
                    for d in districts
                    if len(results[(results["farmer"] == farmer) & (results["district"] == d)]) > 0
                ]
                ax4.bar(x[:len(vals)] + i * w, vals, w, label=farmer, color=C[farmer])
            ax4.set_xticks(x + w); ax4.set_xticklabels(districts, rotation=15, fontsize=9)
            ax4.set_ylabel(unit); ax4.set_title(title)
            ax4.legend(fontsize=9, frameon=False)
        plt.tight_layout()
        _savefig(fig4, "fig4_savings_bar.png")

        _log.info("All 4 figures saved to '%s'.", settings.logs_dir)

    except ImportError:
        _log.warning("matplotlib not installed — skipping figures.")
    except Exception as exc:
        _log.error("Figure generation failed: %s", exc, exc_info=True)


def _savefig(fig, name: str):
    import matplotlib.pyplot as plt
    path = settings.logs_dir / name
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    _log.info("  Saved: %s", name)
