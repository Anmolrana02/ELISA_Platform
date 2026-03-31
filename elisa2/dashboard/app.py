# app.py
"""
dashboard/app.py
─────────────────
ELISA 2.0 Streamlit Farmer Dashboard.

5 tabs:
    1. Status     — SM metrics, 14-day history, district map
    2. Forecast   — 7-day chart with trigger line + rain bars
    3. Decision   — Large MPC decision card + pump window
    4. Log        — Farmer confirms irrigation (feedback loop)
    5. Season     — 3-farmer comparison charts

Run:
    streamlit run dashboard/app.py
    python -m pipelines.run --dashboard
"""

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd
import streamlit as st

from config.settings import agro, settings

st.set_page_config(
    page_title="ELISA 2.0 — Smart Irrigation",
    page_icon="🌾",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
.mcard{background:#f8f9fa;border-radius:10px;padding:1rem;border:1px solid #e0e0e0;text-align:center}
.mlabel{font-size:12px;color:#777;margin-bottom:3px}
.mvalue{font-size:26px;font-weight:700;color:#1a1a1a}
.card-g{background:#e8f5e9;border-left:5px solid #1D9E75;border-radius:8px;padding:1.2rem;margin:.6rem 0}
.card-r{background:#fff3f3;border-left:5px solid #E24B4A;border-radius:8px;padding:1.2rem;margin:.6rem 0}
.ctitle{font-size:20px;font-weight:700;margin-bottom:.4rem}
</style>
""", unsafe_allow_html=True)


# ── Cached loaders ─────────────────────────────────────────────────────────────

@st.cache_data(ttl=1800)
def _df(src):
    p = settings.real_soil_dataset if src == "real" else settings.simulated_dataset
    return pd.read_csv(p, parse_dates=["date"]) if p.exists() else None


@st.cache_data(ttl=1800)
def _sim_results():
    p = settings.logs_dir / "simulation_results.csv"
    return pd.read_csv(p) if p.exists() else None


@st.cache_data(ttl=600)
def _rain(lat, lon):
    from decision.mpc import fetch_rain_forecast
    return fetch_rain_forecast(lat, lon, days=7)


# ── Sidebar ────────────────────────────────────────────────────────────────────

def _sidebar():
    st.sidebar.title("🌾 ELISA 2.0")
    st.sidebar.caption("Smart Irrigation | Jamia Millia Islamia")
    st.sidebar.markdown("---")
    district = st.sidebar.selectbox("District", agro.districts.keys(), index=2)
    src      = st.sidebar.radio("Data source", ["real", "simulated"],
                                 format_func=lambda x: "ERA5-Land (real)" if x == "real" else "Simulated")
    st.sidebar.markdown("---")
    st.sidebar.markdown(f"**GEE:** {'✅ Enabled' if settings.gee_is_ready else '⏳ Pending'}")
    return district, src


# ── Helpers ────────────────────────────────────────────────────────────────────

def _status(df, district):
    d = df[df["district"] == district].sort_values("date")
    if d.empty:
        return {}
    row     = d.iloc[-1]
    profile = agro.get_crop(str(row["crop"]))
    rain    = d[d["precip_mm"] > 1.0]
    return {
        "sm":      float(row["real_soil_moisture_mm"]),
        "trigger": profile.trigger_mm,
        "crop":    str(row["crop"]),
        "date":    row["date"],
        "precip":  float(row["precip_mm"]),
        "days_rain": (row["date"] - rain.iloc[-1]["date"]).days if not rain.empty else "—",
        "ndvi":    float(row["NDVI"]) if "NDVI" in d.columns and not pd.isna(row.get("NDVI")) else None,
        "history": d.tail(14)[["date", "real_soil_moisture_mm"]].copy(),
    }


def _forecast(df, district):
    d = df[df["district"] == district].sort_values("date")
    if d.empty:
        return []
    sm0  = float(d.iloc[-1]["real_soil_moisture_mm"])
    dt   = d.iloc[-1]["date"].date()
    try:
        from decision.mpc import _get_forecast
        return _get_forecast(district, None, dt, "real", sm0)
    except Exception:
        eto = float(d.tail(7)["ETo_mm"].mean()) if "ETo_mm" in d.columns else 4.0
        return [max(0.0, sm0 - eto * (i + 1)) for i in range(settings.forecast_horizon)]


# ── Tab implementations ────────────────────────────────────────────────────────

def _tab_status(df, district, lat, lon):
    status = _status(df, district)
    if not status:
        st.warning(f"No data for {district}."); return

    sm, trig = status["sm"], status["trigger"]
    pct      = sm / trig * 100 if trig > 0 else 100
    clr      = "#1D9E75" if pct > 90 else ("#EF9F27" if pct > 70 else "#E24B4A")
    lbl      = "✅ Safe" if pct > 90 else ("⚠️ Monitor" if pct > 70 else "🔴 Low")

    c1, c2, c3, c4 = st.columns(4)
    for col, label, val, sub in [
        (c1, "Soil moisture",      f'<span style="color:{clr}">{sm:.0f} mm</span>', lbl),
        (c2, "Irrigation trigger", f"{trig:.0f} mm", status["crop"]),
        (c3, "NDVI",               f"{status['ndvi']:.2f}" if status["ndvi"] else "N/A",
             "Sentinel-2" if status["ndvi"] else "GEE pending"),
        (c4, "Days since rain",    str(status["days_rain"]), "> 1mm events"),
    ]:
        col.markdown(
            f'<div class="mcard"><div class="mlabel">{label}</div>'
            f'<div class="mvalue">{val}</div>'
            f'<div class="mlabel">{sub}</div></div>',
            unsafe_allow_html=True,
        )
    st.markdown("---")
    col_m, col_h = st.columns(2)
    with col_m:
        st.subheader("District map")
        try:
            import folium
            from streamlit_folium import st_folium
            m = folium.Map([lat, lon], zoom_start=10)
            for n, (dlat, dlon) in agro.districts.items():
                folium.CircleMarker([dlat, dlon],
                    radius=10 if n == district else 5,
                    color="#1D9E75" if n == district else "#185FA5",
                    fill=True, tooltip=n).add_to(m)
            st_folium(m, height=260, returned_objects=[])
        except ImportError:
            st.caption(f"📍 {district} — {lat:.2f}°N, {lon:.2f}°E")
    with col_h:
        st.subheader("14-day SM history")
        st.line_chart(status["history"].set_index("date")["real_soil_moisture_mm"], height=220)


def _tab_forecast(df, district, lat, lon):
    status   = _status(df, district)
    forecast = _forecast(df, district)
    if not forecast or not status:
        st.warning("Forecast unavailable."); return

    rain_hourly = _rain(lat, lon)
    rain_daily  = [sum(rain_hourly[i*24:(i+1)*24]) for i in range(7)]
    trig        = status["trigger"]

    try:
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
        colors = ["#1D9E75" if v > trig * 1.1 else ("#EF9F27" if v > trig else "#E24B4A")
                  for v in forecast]
        days = [f"Day {i+1}" for i in range(7)]
        fig  = make_subplots(rows=2, cols=1, row_heights=[0.72, 0.28],
                             shared_xaxes=True, vertical_spacing=0.06)
        fig.add_trace(go.Scatter(x=days, y=forecast, mode="lines+markers",
            line=dict(color="#534AB7", width=2.5),
            marker=dict(color=colors, size=10, line=dict(color="white", width=1)),
            name="Predicted SM"), row=1, col=1)
        fig.add_trace(go.Scatter(x=["Now"], y=[status["sm"]], mode="markers",
            marker=dict(color="#E24B4A", size=13, symbol="diamond"),
            name="Current SM"), row=1, col=1)
        fig.add_hline(y=trig, line_dash="dash", line_color="#E24B4A",
                      annotation_text=f"Trigger ({trig:.0f}mm)",
                      annotation_position="top right", row=1, col=1)
        fig.add_trace(go.Bar(x=days, y=rain_daily[:7], name="Rain forecast",
            marker_color="#7EC8E3", opacity=0.75), row=2, col=1)
        fig.update_layout(height=420, margin=dict(l=20,r=20,t=20,b=20),
                          plot_bgcolor="white", paper_bgcolor="white",
                          legend=dict(orientation="h", y=1.04))
        fig.update_yaxes(title_text="SM (mm)",   row=1, col=1, gridcolor="#f0f0f0")
        fig.update_yaxes(title_text="Rain (mm)", row=2, col=1, gridcolor="#f0f0f0")
        st.plotly_chart(fig, use_container_width=True)
    except ImportError:
        st.line_chart(pd.DataFrame({"SM": forecast}, index=[f"Day {i+1}" for i in range(7)]))

    rows = [{"Day": f"Day {i+1}", "SM (mm)": f"{v:.1f}", "Rain (mm)": f"{rain_daily[i]:.1f}",
             "Status": ("✅ Safe" if v > trig * 1.1 else ("⚠️ Caution" if v > trig else "🔴 Below trigger"))}
            for i, v in enumerate(forecast)]
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    st.caption("Day-1 R² target >0.85 | Day-7 R² ~0.60–0.70 | PatchTST (30-day context → 7-day output)")


def _tab_decision(df, district, lat, lon):
    status   = _status(df, district)
    forecast = _forecast(df, district)
    if not status or not forecast:
        st.warning("Insufficient data for recommendation."); return

    try:
        from decision.mpc import IrrigationState, decide, fetch_rain_forecast
        rain  = fetch_rain_forecast(lat, lon, days=2)
        state = IrrigationState(
            district=district, crop=status["crop"],
            current_sm_mm=status["sm"], sm_forecast_7day=forecast,
            rain_forecast_48h=rain[:48], decision_date=date.today(),
        )
        dec = decide(state)
    except Exception as exc:
        st.error(f"Decision engine error: {exc}"); return

    if dec.irrigate:
        w     = dec.window
        wtext = f"<br>Pump window: <strong>{w.start_hour:02d}:00–{w.end_hour:02d}:00</strong> ({w.tariff_slot} tariff) | ₹{w.cost_inr:.2f}" if w else ""
        st.markdown(
            f'<div class="card-r"><div class="ctitle">💧 Irrigation Required</div>'
            f'<p>{dec.reason}{wtext}</p></div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f'<div class="card-g"><div class="ctitle">✅ No Irrigation Needed</div>'
            f'<p style="color:#555">{dec.reason}</p></div>',
            unsafe_allow_html=True,
        )

    with st.expander("Decision logic"):
        st.markdown(f"""
| Parameter | Value |
|---|---|
| Forecast Day-1 | {forecast[0]:.1f} mm |
| Forecast Day-2 | {forecast[1]:.1f} mm |
| Trigger | {status["trigger"]:.0f} mm |
| Rain threshold | {agro.mpc["rain_suppression_threshold_mm"]:.0f} mm |
| Method | 48h MPC (not reinforcement learning) |
| Pump | {agro.pump.power_hp} HP = {agro.pump.power_kw:.2f} kW, η={agro.pump.efficiency} |
        """)


def _tab_log(district):
    st.subheader("Log an irrigation event")
    st.caption("When you irrigate, record it here. The model will account for it in tomorrow's forecast.")

    from farm.manager import FarmManager, list_farms
    fm    = FarmManager()
    farms = list_farms()

    if not farms:
        st.info("No farms registered yet.")
        with st.expander("Register a farm"):
            fn = st.text_input("Farm name", value=f"My {district} Farm")
            if st.button("Register"):
                f = fm.register(name=fn, village=district, district=district)
                st.success(f"Registered! ID: `{f['farm_id']}`")
                st.rerun()
        return

    sel    = st.selectbox("Farm", [f["name"] for f in farms])
    fid    = next(f["farm_id"] for f in farms if f["name"] == sel)
    c1, c2 = st.columns(2)
    with c1: irr_date = st.date_input("Date", value=date.today())
    with c2: mm = st.number_input("Water applied (mm)", min_value=10.0,
                                   max_value=200.0, value=70.0, step=5.0)
    if st.button("✅ Confirm irrigation", type="primary"):
        from decision.state_manager import log_irrigation, update_state
        log_irrigation(fid, irr_date, mm)
        dist = next(f["nearest_district"] for f in farms if f["farm_id"] == fid)
        s    = update_state(fid, dist, irr_date)
        st.success(f"Logged {mm:.0f} mm. Updated SM: **{s['sm_mm']:.1f} mm**. Tomorrow's forecast will reflect this.")

    st.markdown("---")
    from decision.state_manager import get_irrigation_history
    hist = get_irrigation_history(fid, days=60)
    st.markdown("**Recent irrigation events**")
    st.dataframe(hist if not hist.empty else pd.DataFrame({"message": ["No events logged yet."]}),
                 use_container_width=True, hide_index=True)


def _tab_season(district):
    sim = _sim_results()
    if sim is None:
        st.info("Run `python -m pipelines.run --step 9` to generate simulation results."); return

    d = sim[sim["district"] == district]
    if d.empty:
        st.warning(f"No results for {district}."); return

    try:
        import plotly.graph_objects as go
        C = {"Blind": "#E24B4A", "ELISA Minor": "#EF9F27", "ELISA Major": "#1D9E75"}
        c1, c2 = st.columns(2)
        for col, metric, title, unit in [
            (c1, "water_applied_mm", "Water applied", "mm/year"),
            (c2, "cost_inr",         "Energy cost",   "₹/year"),
        ]:
            fig = go.Figure()
            for _, row in d.iterrows():
                fig.add_trace(go.Bar(x=[row["farmer"]], y=[row[metric]],
                    name=row["farmer"], marker_color=C.get(row["farmer"], "#888"),
                    text=[f"{row[metric]:.0f} {unit}"], textposition="auto"))
            fig.update_layout(title=f"{title} ({unit})", showlegend=False, height=320,
                              margin=dict(l=10,r=10,t=40,b=10), plot_bgcolor="white")
            col.plotly_chart(fig, use_container_width=True)
    except ImportError:
        st.dataframe(d[["farmer","water_applied_mm","cost_inr","stress_days","mean_ks"]],
                     use_container_width=True)

    b = d[d["farmer"] == "Blind"]
    M = d[d["farmer"] == "ELISA Major"]
    if not b.empty and not M.empty:
        w = float(b["water_applied_mm"].values[0] - M["water_applied_mm"].values[0])
        c = float(b["cost_inr"].values[0]         - M["cost_inr"].values[0])
        st.success(f"**ELISA Major saves {w:.0f} mm water and ₹{c:.0f} vs traditional practice in {district}.**")

    st.dataframe(d[["farmer","irrigation_events","water_applied_mm","energy_kwh","cost_inr","stress_days","mean_ks"]],
                 use_container_width=True, hide_index=True)


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    district, src = _sidebar()
    lat, lon = agro.districts[district]

    st.title("🌾 ELISA 2.0 — Smart Irrigation Dashboard")
    st.caption(
        f"District: **{district}** | "
        f"{'ERA5-Land real' if src == 'real' else 'Simulated'} data | "
        f"GEE: {'enabled' if settings.gee_is_ready else 'pending'}"
    )

    df = _df(src)
    if df is None:
        st.error("Dataset not found. Run: `python -m pipelines.run`")
        return

    t1, t2, t3, t4, t5 = st.tabs([
        "📊 Current Status", "📈 7-Day Forecast",
        "🚿 Decision", "✍️ Log Irrigation", "📋 Season Results",
    ])
    with t1: _tab_status(df, district, lat, lon)
    with t2: _tab_forecast(df, district, lat, lon)
    with t3: _tab_decision(df, district, lat, lon)
    with t4: _tab_log(district)
    with t5: _tab_season(district)

    st.markdown("---")
    st.caption("ELISA 2.0 | EE Dept, Jamia Millia Islamia | Anmol Rana & Nitin Gaurav | Dr. Zainul Abidin Jaffery")


if __name__ == "__main__":
    main()
