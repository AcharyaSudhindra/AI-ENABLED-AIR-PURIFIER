import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime, timedelta
import time
import random
import requests
import math

st.set_page_config(
    page_title="AirGuard — Smart Air Purifier",
    page_icon="🌬️",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
.metric-card {
  background: #1a1f2e;
  border: 1px solid #2a3050;
  border-radius: 14px;
  padding: 1.1rem 1.2rem;
  text-align: center;
  margin-bottom: 0.5rem;
}
.metric-value { font-size: 2rem; font-weight: 700; margin: 0.2rem 0 0; line-height:1; }
.metric-label { font-size: 0.72rem; color: #6b7a99; text-transform: uppercase; letter-spacing: 0.08em; margin: 0; }
.metric-sub   { font-size: 0.78rem; margin-top: 0.3rem; }
.aqi-good    { color: #00c896; }
.aqi-mod     { color: #f4c542; }
.aqi-poor    { color: #ff6b35; }
.aqi-hazard  { color: #e53935; }
.status-pill {
  display: inline-block; padding: 0.22rem 0.85rem;
  border-radius: 999px; font-size: 0.72rem; font-weight: 600; letter-spacing: 0.05em;
}
.pill-on   { background: rgba(0,200,150,0.15); color: #00c896; border: 1px solid rgba(0,200,150,0.4); }
.pill-off  { background: rgba(229,57,53,0.15);  color: #e53935; border: 1px solid rgba(229,57,53,0.4); }
.pill-auto { background: rgba(55,138,221,0.15); color: #378add; border: 1px solid rgba(55,138,221,0.4); }
.pill-warn { background: rgba(244,197,66,0.15); color: #f4c542; border: 1px solid rgba(244,197,66,0.4); }
.section-hdr {
  font-size: 0.88rem; font-weight: 600; color: #ccd6f6;
  border-left: 3px solid #378add; padding-left: 0.6rem;
  margin: 1.3rem 0 0.8rem; letter-spacing: 0.02em;
}
.alert-box { border-radius: 9px; padding: 0.7rem 0.9rem; margin: 0.3rem 0; font-size: 0.83rem; }
.alert-warn { background: rgba(244,197,66,0.1);  border: 1px solid rgba(244,197,66,0.35); color: #f4c542; }
.alert-crit { background: rgba(229,57,53,0.1);   border: 1px solid rgba(229,57,53,0.35);  color: #e53935; }
.alert-info { background: rgba(55,138,221,0.1);  border: 1px solid rgba(55,138,221,0.35); color: #378add; }
.alert-ok   { background: rgba(0,200,150,0.1);   border: 1px solid rgba(0,200,150,0.35);  color: #00c896; }
.tip-card {
  background: #161b2e; border: 1px solid #2a3050;
  border-radius: 10px; padding: 0.8rem 1rem; font-size: 0.82rem;
  color: #aab4cc; line-height: 1.5;
}
.forecast-card {
  background: #1a1f2e; border: 1px solid #2a3050;
  border-radius: 10px; padding: 0.75rem; text-align: center;
}
.log-entry { font-size: 0.78rem; color: #8892b0; padding: 0.2rem 0; border-bottom: 1px solid #1e2540; }
div[data-testid="stSidebar"] { background: #0d1020; }
div[data-testid="stSidebar"] * { color: #ccd6f6 !important; }
</style>
""", unsafe_allow_html=True)


# ─── Helpers ──────────────────────────────────────────────────────────────────
def aqi_category(aqi):
    if aqi <= 50:   return "Good",       "#00c896", "aqi-good"
    if aqi <= 100:  return "Moderate",   "#f4c542", "aqi-mod"
    if aqi <= 150:  return "Unhealthy",  "#ff6b35", "aqi-poor"
    if aqi <= 200:  return "Very Unhealthy", "#e53935", "aqi-hazard"
    return "Hazardous", "#b71c1c", "aqi-hazard"

def fan_label(s): return {0:"OFF",1:"LOW",2:"MEDIUM",3:"HIGH"}.get(s,"—")
def filter_color(p): return "#00c896" if p>60 else "#f4c542" if p>30 else "#e53935"

def get_sensor_data():
    """Simulated readings — swap with: requests.get('http://ESP32_IP/sensors').json()"""
    aqi  = max(0, min(500, st.session_state.base_aqi + random.uniform(-6, 6)))
    dust = max(0, st.session_state.dust_base + random.uniform(-4, 4))
    voc  = max(0, st.session_state.voc_base  + random.uniform(-0.04, 0.04))
    temp = 26 + random.uniform(-0.4, 0.4)
    hum  = 55 + random.uniform(-1.5, 1.5)
    return {
        "aqi":        round(aqi, 1),
        "dust_pm25":  round(dust, 1),
        "dust_pm10":  round(dust * 1.7, 1),
        "voc_ppm":    round(voc, 3),
        "co2_ppm":    round(400 + aqi * 2.5 + random.uniform(-15, 15), 0),
        "temperature":round(temp, 1),
        "humidity":   round(hum, 1),
        "timestamp":  datetime.now()
    }

def hourly_forecast():
    base = st.session_state.base_aqi
    hours = []
    for i in range(12):
        noise = 15 * math.sin(i * 0.6) + random.uniform(-8, 8)
        hours.append({
            "hour": (datetime.now() + timedelta(hours=i)).strftime("%I%p"),
            "aqi":  max(0, round(base + noise, 1))
        })
    return hours

def daily_forecast():
    base = st.session_state.base_aqi
    days = ["Today","Mon","Tue","Wed","Thu","Fri","Sat"]
    icons= ["🌬️","☁️","🌧️","☀️","🌤️","🌧️","☀️"]
    return [{"day": days[i], "icon": icons[i],
             "aqi": max(0, round(base + random.uniform(-20,20), 0))} for i in range(7)]

# ─── Session state ────────────────────────────────────────────────────────────
defs = {
    'history':        [],
    'event_log':      [],
    'fan_speed':      1,
    'purifier_on':    True,
    'auto_mode':      True,
    'schedule_on':    False,
    'schedule_start': "07:00",
    'schedule_end':   "22:00",
    'filter_hours':   120,
    'filter_max':     720,
    'base_aqi':       72,
    'dust_base':      45,
    'voc_base':       0.6,
    'aqi_threshold':  100,
    'notifications':  [],
    'uptime_mins':    0,
    'energy_kwh':     0.0,
    'purif_cycles':   0,
    'active_page':    "Dashboard",
    'last_sensor_time': 0.0,
    'current_data':   None,
    'refresh_interval': 3,
}
for k, v in defs.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ─── Live data — only update every N seconds ──────────────────────────────────
now_ts = time.time()
if (st.session_state.current_data is None or
        now_ts - st.session_state.last_sensor_time >= st.session_state.refresh_interval):
    st.session_state.current_data     = get_sensor_data()
    st.session_state.last_sensor_time = now_ts

data = st.session_state.current_data
# Only append to history when we got a fresh reading
if len(st.session_state.history) == 0 or st.session_state.history[-1]['timestamp'] != data['timestamp']:
    st.session_state.history.append(data)
if len(st.session_state.history) > 300:
    st.session_state.history = st.session_state.history[-300:]

if st.session_state.purifier_on:
    st.session_state.uptime_mins += 0.05
    st.session_state.energy_kwh  += 0.000015 * (st.session_state.fan_speed + 1)
    st.session_state.filter_hours = min(st.session_state.filter_max,
                                        st.session_state.filter_hours + 0.002)

if st.session_state.auto_mode and st.session_state.purifier_on:
    aqi = data['aqi']
    new_speed = 1 if aqi <= 50 else 2 if aqi <= 100 else 3
    if new_speed != st.session_state.fan_speed:
        st.session_state.event_log.append(
            f"{datetime.now().strftime('%H:%M:%S')} · Auto — fan → {fan_label(new_speed)} (AQI {aqi})")
    st.session_state.fan_speed = new_speed

# Schedule logic
if st.session_state.schedule_on:
    now_t = datetime.now().strftime("%H:%M")
    if st.session_state.schedule_start <= now_t <= st.session_state.schedule_end:
        if not st.session_state.purifier_on:
            st.session_state.purifier_on = True
            st.session_state.event_log.append(
                f"{datetime.now().strftime('%H:%M:%S')} · Schedule ON")
    else:
        if st.session_state.purifier_on:
            st.session_state.purifier_on = False
            st.session_state.event_log.append(
                f"{datetime.now().strftime('%H:%M:%S')} · Schedule OFF")

if len(st.session_state.event_log) > 50:
    st.session_state.event_log = st.session_state.event_log[-50:]

filter_pct = (1 - st.session_state.filter_hours / st.session_state.filter_max) * 100

# Notifications
notes = []
if data['aqi'] > 150:
    notes.append(("crit", f"🚨 AQI {data['aqi']} — HAZARDOUS! Purifier forced to HIGH."))
elif data['aqi'] > 100:
    notes.append(("warn", f"⚠️ AQI {data['aqi']} — Unhealthy for sensitive groups."))
if filter_pct < 15:
    notes.append(("crit", f"🚨 Filter critical: {filter_pct:.0f}% remaining — replace now!"))
elif filter_pct < 35:
    notes.append(("warn", f"⚠️ Filter at {filter_pct:.0f}% — schedule replacement."))
if data['voc_ppm'] > 1.0:
    notes.append(("crit", f"🚨 VOC spike {data['voc_ppm']} ppm — possible gas leak! Ventilate."))
if data['co2_ppm'] > 1000:
    notes.append(("warn", f"⚠️ CO₂ {data['co2_ppm']:.0f} ppm — open a window briefly."))
if data['humidity'] > 70:
    notes.append(("warn", f"⚠️ Humidity {data['humidity']}% — mold risk. Check ventilation."))
if not notes:
    notes.append(("ok", "✅ All sensors normal — air quality is good."))
st.session_state.notifications = notes

outdoor_aqi = round(st.session_state.base_aqi * 1.15 + random.uniform(-10, 10), 1)

# ═══════════════════════════════════════════════════════════════════════════════
# SIDEBAR
# ═══════════════════════════════════════════════════════════════════════════════
with st.sidebar:
    st.markdown("## 🌬️ AirGuard")
    st.caption("ESP32-S3 · MQ135 · GP2Y1010")
    st.markdown("---")

    st.markdown('<div class="section-hdr">Power & Mode</div>', unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    with c1:
        if st.session_state.purifier_on:
            if st.button("⏹ OFF", width="stretch"):
                st.session_state.purifier_on = False
                st.session_state.fan_speed = 0
                st.session_state.event_log.append(f"{datetime.now().strftime('%H:%M:%S')} · Manual OFF")
        else:
            if st.button("▶ ON", width="stretch"):
                st.session_state.purifier_on = True
                st.session_state.fan_speed = 1
                st.session_state.event_log.append(f"{datetime.now().strftime('%H:%M:%S')} · Manual ON")
    with c2:
        st.session_state.auto_mode = st.toggle("Auto", value=st.session_state.auto_mode)

    if st.session_state.purifier_on and not st.session_state.auto_mode:
        speed = st.select_slider("Fan Speed", ["OFF","LOW","MED","HIGH"],
                                 value=["OFF","LOW","MED","HIGH"][st.session_state.fan_speed])
        st.session_state.fan_speed = ["OFF","LOW","MED","HIGH"].index(speed)

    st.markdown('<div class="section-hdr">Schedule</div>', unsafe_allow_html=True)
    st.session_state.schedule_on = st.toggle("Enable Schedule", value=st.session_state.schedule_on)
    if st.session_state.schedule_on:
        st.session_state.schedule_start = st.text_input("ON  (HH:MM)", st.session_state.schedule_start)
        st.session_state.schedule_end   = st.text_input("OFF (HH:MM)", st.session_state.schedule_end)

    st.markdown('<div class="section-hdr">AQI Alert Threshold</div>', unsafe_allow_html=True)
    st.session_state.aqi_threshold = st.slider("Alert above AQI", 50, 200,
                                                st.session_state.aqi_threshold)
    if data['aqi'] > st.session_state.aqi_threshold:
        st.warning(f"AQI {data['aqi']} exceeds your threshold of {st.session_state.aqi_threshold}!")

    st.markdown('<div class="section-hdr">Filter</div>', unsafe_allow_html=True)
    fc = filter_color(filter_pct)
    st.markdown(f"Remaining: <b style='color:{fc}'>{filter_pct:.0f}%</b>", unsafe_allow_html=True)
    st.progress(max(0.01, filter_pct / 100))
    st.caption(f"{st.session_state.filter_hours:.0f} / {st.session_state.filter_max} hrs")
    if st.button("🔄 Reset Filter"):
        st.session_state.filter_hours = 0

    st.markdown('<div class="section-hdr">Simulate Sensors</div>', unsafe_allow_html=True)
    st.session_state.base_aqi  = st.slider("AQI",        0, 300, st.session_state.base_aqi)
    st.session_state.dust_base = st.slider("PM2.5",      0, 150, st.session_state.dust_base)
    st.session_state.voc_base  = st.slider("VOC (ppm)", 0.0, 2.5, float(st.session_state.voc_base), step=0.05)

    st.markdown('<div class="section-hdr">Refresh Rate</div>', unsafe_allow_html=True)
    st.session_state.refresh_interval = st.select_slider(
        "Update every", options=[1, 2, 3, 5, 10, 30], value=st.session_state.refresh_interval,
        format_func=lambda x: f"{x}s"
    )

    st.markdown("---")
    up_h = int(st.session_state.uptime_mins // 60)
    up_m = int(st.session_state.uptime_mins % 60)
    st.caption(f"Uptime: {up_h}h {up_m}m\nEnergy: {st.session_state.energy_kwh:.4f} kWh")

# ═══════════════════════════════════════════════════════════════════════════════
# MAIN — TAB NAVIGATION
# ═══════════════════════════════════════════════════════════════════════════════
cat_name, cat_color, cat_css = aqi_category(data['aqi'])

st.markdown("# 🌬️ AirGuard — Smart Air Purifier")
st.markdown(
    f"Purifier <span class='status-pill {'pill-on' if st.session_state.purifier_on else 'pill-off'}'>{'ON' if st.session_state.purifier_on else 'OFF'}</span> &nbsp;"
    f"Mode <span class='status-pill {'pill-auto' if st.session_state.auto_mode else 'pill-on'}'>{'AUTO' if st.session_state.auto_mode else 'MANUAL'}</span> &nbsp;"
    f"Fan <span class='status-pill pill-warn'>{fan_label(st.session_state.fan_speed)}</span> &nbsp;"
    f"<span style='color:#6b7a99;font-size:0.78rem'>{data['timestamp'].strftime('%H:%M:%S')}</span>",
    unsafe_allow_html=True
)

pages = st.tabs(["📊 Dashboard", "📈 Analytics", "🌤️ Forecast", "🤖 AI Insights", "⚙️ Settings & Logs"])

# ═══════════════════════════════
# TAB 1 — DASHBOARD
# ═══════════════════════════════
with pages[0]:
    # KPIs
    cols = st.columns(6)
    kpis = [
        ("AQI",         str(data['aqi']),         cat_name,           cat_color),
        ("PM2.5 µg/m³", str(data['dust_pm25']),   "Particulates",     "#ccd6f6"),
        ("PM10 µg/m³",  str(data['dust_pm10']),   "Coarse Dust",      "#ccd6f6"),
        ("VOC ppm",     str(data['voc_ppm']),      "Volatiles",        "#ccd6f6"),
        ("Temp °C",     str(data['temperature']),  "Indoor Temp",      "#ccd6f6"),
        ("Humidity %",  str(data['humidity']),     "Relative Hum.",    "#ccd6f6"),
    ]
    for col, (lbl, val, sub, color) in zip(cols, kpis):
        with col:
            st.markdown(f"""<div class="metric-card">
              <p class="metric-label">{lbl}</p>
              <p class="metric-value" style="color:{color}">{val}</p>
              <p class="metric-sub" style="color:{color}99">{sub}</p>
            </div>""", unsafe_allow_html=True)

    st.markdown("---")

    # Notifications
    st.markdown('<div class="section-hdr">Alerts</div>', unsafe_allow_html=True)
    for ntype, msg in st.session_state.notifications:
        st.markdown(f'<div class="alert-box alert-{ntype}">{msg}</div>', unsafe_allow_html=True)

    st.markdown("---")

    # AQI mini-chart + Purifier stats
    hdf = pd.DataFrame(st.session_state.history)
    col_chart, col_stats = st.columns([2, 1])
    with col_chart:
        st.markdown('<div class="section-hdr">Live AQI</div>', unsafe_allow_html=True)
        if len(hdf) > 2:
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=hdf['timestamp'], y=hdf['aqi'],
                fill='tozeroy',
                fillcolor='rgba(55,138,221,0.10)',
                line=dict(color='#378add', width=2),
                name='AQI'
            ))
            # Fixed: use rgba() strings instead of 8-digit hex
            fig.add_hrect(y0=0,   y1=50,  fillcolor="rgba(0,200,150,0.06)",   line_width=0, annotation_text="Good",      annotation_position="right", annotation_font_color="#00c896")
            fig.add_hrect(y0=50,  y1=100, fillcolor="rgba(244,197,66,0.06)",  line_width=0, annotation_text="Moderate",  annotation_position="right", annotation_font_color="#f4c542")
            fig.add_hrect(y0=100, y1=150, fillcolor="rgba(255,107,53,0.06)",  line_width=0, annotation_text="Unhealthy", annotation_position="right", annotation_font_color="#ff6b35")
            fig.add_hrect(y0=150, y1=500, fillcolor="rgba(229,57,53,0.06)",   line_width=0, annotation_text="Hazardous", annotation_position="right", annotation_font_color="#e53935")
            fig.update_layout(
                height=260, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
                font_color='#8892b0', margin=dict(l=0,r=60,t=10,b=0), showlegend=False,
                xaxis=dict(showgrid=False, color='#4a5568'),
                yaxis=dict(showgrid=True, gridcolor='rgba(255,255,255,0.05)', title='AQI')
            )
            st.plotly_chart(fig, width="stretch")
        else:
            st.info("Collecting data — refresh a few times.")

    with col_stats:
        st.markdown('<div class="section-hdr">System Stats</div>', unsafe_allow_html=True)
        st.markdown(f"""
        <div class="metric-card" style="margin-bottom:0.5rem">
          <p class="metric-label">Uptime</p>
          <p class="metric-value" style="color:#378add;font-size:1.4rem">{int(st.session_state.uptime_mins//60)}h {int(st.session_state.uptime_mins%60)}m</p>
        </div>
        <div class="metric-card" style="margin-bottom:0.5rem">
          <p class="metric-label">Energy Used</p>
          <p class="metric-value" style="color:#f4c542;font-size:1.4rem">{st.session_state.energy_kwh:.3f} kWh</p>
        </div>
        <div class="metric-card">
          <p class="metric-label">Filter Life</p>
          <p class="metric-value" style="color:{filter_color(filter_pct)};font-size:1.4rem">{filter_pct:.0f}%</p>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("---")

    # Indoor vs Outdoor
    st.markdown('<div class="section-hdr">Indoor vs Outdoor</div>', unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)
    _, in_c, _ = aqi_category(data['aqi'])
    _, out_c, _ = aqi_category(outdoor_aqi)
    with c1:
        st.markdown(f"""<div class="metric-card">
          <p class="metric-label">Indoor AQI</p>
          <p class="metric-value" style="color:{in_c}">{data['aqi']}</p>
          <p class="metric-sub" style="color:{in_c}88">{aqi_category(data['aqi'])[0]}</p>
        </div>""", unsafe_allow_html=True)
    with c2:
        st.markdown(f"""<div class="metric-card">
          <p class="metric-label">Outdoor AQI</p>
          <p class="metric-value" style="color:{out_c}">{outdoor_aqi}</p>
          <p class="metric-sub" style="color:{out_c}88">{aqi_category(outdoor_aqi)[0]}</p>
        </div>""", unsafe_allow_html=True)
    with c3:
        if outdoor_aqi > data['aqi'] + 10:
            rec = "🪟 Keep windows closed"
            rec_c = "#00c896"
        elif data['aqi'] > outdoor_aqi + 10:
            rec = "💨 Open windows now!"
            rec_c = "#f4c542"
        else:
            rec = "🔄 Air quality similar"
            rec_c = "#ccd6f6"
        st.markdown(f"""<div class="metric-card">
          <p class="metric-label">Recommendation</p>
          <p class="metric-value" style="color:{rec_c};font-size:1rem;padding-top:0.4rem">{rec}</p>
        </div>""", unsafe_allow_html=True)


# ═══════════════════════════════
# TAB 2 — ANALYTICS
# ═══════════════════════════════
with pages[1]:
    hdf = pd.DataFrame(st.session_state.history)

    if len(hdf) < 3:
        st.info("Collecting data... please wait a few seconds and refresh.")
    else:
        # AQI + dust dual chart
        st.markdown('<div class="section-hdr">AQI Trend</div>', unsafe_allow_html=True)
        fig_aqi = go.Figure()
        fig_aqi.add_trace(go.Scatter(x=hdf['timestamp'], y=hdf['aqi'],
            line=dict(color='#378add', width=2), fill='tozeroy',
            fillcolor='rgba(55,138,221,0.08)', name='AQI'))
        fig_aqi.update_layout(height=220, paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)', font_color='#8892b0',
            margin=dict(l=0,r=0,t=10,b=0), showlegend=False,
            xaxis=dict(showgrid=False),
            yaxis=dict(showgrid=True, gridcolor='rgba(255,255,255,0.05)'))
        st.plotly_chart(fig_aqi, width="stretch")

        c1, c2 = st.columns(2)
        with c1:
            st.markdown('<div class="section-hdr">Particulates (PM2.5 / PM10)</div>', unsafe_allow_html=True)
            fig2 = go.Figure()
            fig2.add_trace(go.Scatter(x=hdf['timestamp'], y=hdf['dust_pm25'],
                name='PM2.5', line=dict(color='#00c896', width=2)))
            fig2.add_trace(go.Scatter(x=hdf['timestamp'], y=hdf['dust_pm10'],
                name='PM10', line=dict(color='#f4c542', width=2, dash='dot')))
            fig2.update_layout(height=200, paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)', font_color='#8892b0',
                margin=dict(l=0,r=0,t=10,b=0),
                xaxis=dict(showgrid=False),
                yaxis=dict(showgrid=True, gridcolor='rgba(255,255,255,0.05)', title='µg/m³'),
                legend=dict(bgcolor='rgba(0,0,0,0)'))
            st.plotly_chart(fig2, width="stretch")

        with c2:
            st.markdown('<div class="section-hdr">VOC & CO₂</div>', unsafe_allow_html=True)
            fig3 = go.Figure()
            fig3.add_trace(go.Scatter(x=hdf['timestamp'], y=hdf['voc_ppm'],
                name='VOC ppm', line=dict(color='#ff6b35', width=2)))
            fig3.add_trace(go.Scatter(x=hdf['timestamp'], y=hdf['co2_ppm'],
                name='CO₂ ppm', line=dict(color='#378add', width=2), yaxis='y2'))
            fig3.update_layout(height=200, paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)', font_color='#8892b0',
                margin=dict(l=0,r=0,t=10,b=0),
                xaxis=dict(showgrid=False),
                yaxis=dict(title='VOC ppm', showgrid=True, gridcolor='rgba(255,255,255,0.05)'),
                yaxis2=dict(title='CO₂ ppm', overlaying='y', side='right'),
                legend=dict(bgcolor='rgba(0,0,0,0)'))
            st.plotly_chart(fig3, width="stretch")

        st.markdown('<div class="section-hdr">Temperature & Humidity</div>', unsafe_allow_html=True)
        fig4 = go.Figure()
        fig4.add_trace(go.Scatter(x=hdf['timestamp'], y=hdf['temperature'],
            name='Temp °C', line=dict(color='#e53935', width=2)))
        fig4.add_trace(go.Scatter(x=hdf['timestamp'], y=hdf['humidity'],
            name='Humidity %', line=dict(color='#378add', width=2), yaxis='y2'))
        fig4.update_layout(height=200, paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)', font_color='#8892b0',
            margin=dict(l=0,r=0,t=10,b=0),
            xaxis=dict(showgrid=False),
            yaxis=dict(title='°C', showgrid=True, gridcolor='rgba(255,255,255,0.05)'),
            yaxis2=dict(title='%', overlaying='y', side='right'),
            legend=dict(bgcolor='rgba(0,0,0,0)'))
        st.plotly_chart(fig4, width="stretch")

        st.markdown('<div class="section-hdr">AQI Distribution</div>', unsafe_allow_html=True)
        c1, c2 = st.columns(2)
        with c1:
            fig_hist = go.Figure(go.Histogram(
                x=hdf['aqi'], nbinsx=20,
                marker_color='#378add', opacity=0.8
            ))
            fig_hist.update_layout(height=220, paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)', font_color='#8892b0',
                margin=dict(l=0,r=0,t=10,b=0),
                xaxis=dict(showgrid=False, title='AQI'),
                yaxis=dict(showgrid=True, gridcolor='rgba(255,255,255,0.05)', title='Count'))
            st.plotly_chart(fig_hist, width="stretch")
        with c2:
            avg_aqi = hdf['aqi'].mean()
            fig_gauge = go.Figure(go.Indicator(
                mode="gauge+number+delta",
                value=round(avg_aqi, 1),
                delta={'reference': 100},
                gauge={
                    'axis': {'range': [0, 300], 'tickcolor': '#8892b0'},
                    'bar': {'color': cat_color},
                    'bgcolor': 'rgba(0,0,0,0)',
                    'borderwidth': 0,
                    'steps': [
                        {'range': [0, 50],   'color': 'rgba(0,200,150,0.15)'},
                        {'range': [50, 100], 'color': 'rgba(244,197,66,0.15)'},
                        {'range': [100, 150],'color': 'rgba(255,107,53,0.15)'},
                        {'range': [150, 300],'color': 'rgba(229,57,53,0.15)'},
                    ],
                    'threshold': {'line': {'color': '#e53935', 'width': 2},
                                  'thickness': 0.8, 'value': 150}
                },
                title={'text': "Session Avg AQI", 'font': {'color': '#ccd6f6', 'size': 13}}
            ))
            fig_gauge.update_layout(height=220, paper_bgcolor='rgba(0,0,0,0)',
                font_color='#ccd6f6', margin=dict(l=10,r=10,t=30,b=0))
            st.plotly_chart(fig_gauge, width="stretch")

        st.markdown('<div class="section-hdr">Session Summary</div>', unsafe_allow_html=True)
        s1, s2, s3, s4, s5 = st.columns(5)
        s1.metric("Readings", len(hdf))
        s2.metric("Max AQI", f"{hdf['aqi'].max():.1f}")
        s3.metric("Min AQI", f"{hdf['aqi'].min():.1f}")
        s4.metric("Avg PM2.5", f"{hdf['dust_pm25'].mean():.1f}")
        s5.metric("Avg VOC", f"{hdf['voc_ppm'].mean():.3f}")

        st.markdown('<div class="section-hdr">Export Data</div>', unsafe_allow_html=True)
        export = hdf.copy()
        export['timestamp'] = export['timestamp'].dt.strftime('%Y-%m-%d %H:%M:%S')
        csv = export.to_csv(index=False)
        st.download_button("⬇️ Download CSV", csv, "airguard_data.csv", "text/csv")


# ═══════════════════════════════
# TAB 3 — FORECAST
# ═══════════════════════════════
with pages[2]:
    st.markdown('<div class="section-hdr">12-Hour AQI Forecast</div>', unsafe_allow_html=True)
    forecast_h = hourly_forecast()
    fdf = pd.DataFrame(forecast_h)
    fig_fc = go.Figure()
    colors = [aqi_category(v)[1] for v in fdf['aqi']]
    fig_fc.add_trace(go.Bar(
        x=fdf['hour'], y=fdf['aqi'],
        marker_color=colors, name='Predicted AQI'
    ))
    fig_fc.add_hline(y=100, line_dash="dot", line_color="rgba(255,107,53,0.6)",
                     annotation_text="Unhealthy threshold",
                     annotation_font_color="rgba(255,107,53,0.8)")
    fig_fc.update_layout(height=280, paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)', font_color='#8892b0',
        margin=dict(l=0,r=0,t=20,b=0), showlegend=False,
        xaxis=dict(showgrid=False),
        yaxis=dict(showgrid=True, gridcolor='rgba(255,255,255,0.05)', title='AQI'))
    st.plotly_chart(fig_fc, width="stretch")

    st.markdown('<div class="section-hdr">7-Day Outlook</div>', unsafe_allow_html=True)
    forecast_d = daily_forecast()
    day_cols = st.columns(7)
    for col, day in zip(day_cols, forecast_d):
        _, dc, _ = aqi_category(day['aqi'])
        with col:
            st.markdown(f"""<div class="forecast-card">
              <div style="font-size:1.4rem">{day['icon']}</div>
              <div style="font-size:0.75rem;color:#6b7a99;margin:0.2rem 0">{day['day']}</div>
              <div style="font-size:1.1rem;font-weight:700;color:{dc}">{int(day['aqi'])}</div>
              <div style="font-size:0.65rem;color:{dc}88">{aqi_category(day['aqi'])[0]}</div>
            </div>""", unsafe_allow_html=True)

    st.markdown('<div class="section-hdr">Best Times to Ventilate</div>', unsafe_allow_html=True)
    good_hours = [h for h in forecast_h if h['aqi'] <= 50]
    mod_hours  = [h for h in forecast_h if 50 < h['aqi'] <= 100]
    if good_hours:
        times = ", ".join([h['hour'] for h in good_hours])
        st.markdown(f'<div class="alert-box alert-ok">✅ Best ventilation windows: <b>{times}</b> — AQI below 50</div>',
                    unsafe_allow_html=True)
    if mod_hours:
        times = ", ".join([h['hour'] for h in mod_hours])
        st.markdown(f'<div class="alert-box alert-warn">⚠️ Moderate periods: <b>{times}</b> — short ventilation ok</div>',
                    unsafe_allow_html=True)
    bad_hours = [h for h in forecast_h if h['aqi'] > 100]
    if bad_hours:
        times = ", ".join([h['hour'] for h in bad_hours])
        st.markdown(f'<div class="alert-box alert-crit">🚨 Keep windows closed: <b>{times}</b> — AQI above 100</div>',
                    unsafe_allow_html=True)

    st.markdown('<div class="section-hdr">Adaptive Purifier Schedule (AI Suggested)</div>', unsafe_allow_html=True)
    st.markdown("""<div class="tip-card">
    Based on the forecast, the AI recommends:<br>
    • <b>06:00–09:00</b>: Run on <b>HIGH</b> — morning pollution peak expected<br>
    • <b>10:00–16:00</b>: <b>LOW</b> speed sufficient — air quality stabilises midday<br>
    • <b>17:00–21:00</b>: <b>MEDIUM</b> — evening traffic pollution rise<br>
    • <b>22:00–05:00</b>: <b>LOW / OFF</b> — overnight, minimal pollution expected
    </div>""", unsafe_allow_html=True)


# ═══════════════════════════════
# TAB 4 — AI INSIGHTS
# ═══════════════════════════════
with pages[3]:
    st.markdown('<div class="section-hdr">Real-Time Health Advice</div>', unsafe_allow_html=True)

    tips = []
    aqi_v = data['aqi']
    if aqi_v <= 50:
        tips += [("ok","✅ Air quality excellent — safe for all activities including outdoor exercise."),
                 ("info","💡 Great time to open windows for 10–15 min for natural ventilation.")]
    elif aqi_v <= 100:
        tips += [("warn","⚠️ Moderate AQI — sensitive groups (asthma, elderly, children) should reduce outdoor time."),
                 ("info","💡 Keep purifier on LOW or AUTO. Indoor air is being maintained.")]
    elif aqi_v <= 150:
        tips += [("crit","🚨 Unhealthy for sensitive groups — everyone should limit strenuous outdoor activity."),
                 ("warn","⚠️ Keep all windows/doors shut. Purifier should be on HIGH."),
                 ("info","💡 Wear N95 mask if going outside.")]
    else:
        tips += [("crit","🚨 HAZARDOUS — avoid all outdoor activity. Stay indoors."),
                 ("crit","🚨 Seal any gaps around windows and doors."),
                 ("warn","⚠️ Purifier MUST run on HIGH. Consider air quality emergency kit.")]

    if data['humidity'] > 65:
        tips.append(("warn","⚠️ High humidity — risk of dust mite growth. Consider a dehumidifier."))
    if data['co2_ppm'] > 800:
        tips.append(("warn",f"⚠️ CO₂ at {data['co2_ppm']:.0f} ppm — brief ventilation improves cognitive performance."))
    if data['temperature'] > 28:
        tips.append(("info","💡 Warm air holds more pollutants. Consider cooling the room slightly."))

    tip_cols = st.columns(2)
    for i, (ttype, tmsg) in enumerate(tips):
        with tip_cols[i % 2]:
            st.markdown(f'<div class="alert-box alert-{ttype}" style="min-height:60px">{tmsg}</div>',
                        unsafe_allow_html=True)

    st.markdown("---")
    st.markdown('<div class="section-hdr">Anomaly Detection</div>', unsafe_allow_html=True)
    hdf = pd.DataFrame(st.session_state.history)
    if len(hdf) > 10:
        aqi_mean = hdf['aqi'].mean()
        aqi_std  = hdf['aqi'].std() if hdf['aqi'].std() > 0 else 1
        z_score  = abs(data['aqi'] - aqi_mean) / aqi_std
        if z_score > 2.5:
            st.markdown(f'<div class="alert-box alert-crit">🚨 Anomaly detected — AQI spike (z-score {z_score:.1f}σ). Possible pollution event or appliance issue.</div>', unsafe_allow_html=True)
        else:
            st.markdown(f'<div class="alert-box alert-ok">✅ No anomalies — readings within normal range (z={z_score:.2f}σ).</div>', unsafe_allow_html=True)

        voc_mean = hdf['voc_ppm'].mean()
        voc_std  = hdf['voc_ppm'].std() if hdf['voc_ppm'].std() > 0 else 0.01
        voc_z    = abs(data['voc_ppm'] - voc_mean) / voc_std
        if voc_z > 2.5:
            st.markdown(f'<div class="alert-box alert-crit">🚨 VOC anomaly (z={voc_z:.1f}σ) — check for cleaning products, paint, gas appliances.</div>', unsafe_allow_html=True)
        else:
            st.markdown(f'<div class="alert-box alert-ok">✅ VOC levels normal (z={voc_z:.2f}σ).</div>', unsafe_allow_html=True)
    else:
        st.info("Collecting baseline data for anomaly detection...")

    st.markdown("---")
    st.markdown('<div class="section-hdr">Filter Predictive Analytics</div>', unsafe_allow_html=True)
    hours_left = st.session_state.filter_max - st.session_state.filter_hours
    days_left  = hours_left / 24
    wear_rate  = st.session_state.filter_hours / max(1, st.session_state.uptime_mins / 60)
    ca, cb, cc = st.columns(3)
    ca.metric("Filter Hours Used",   f"{st.session_state.filter_hours:.0f} h")
    cb.metric("Est. Hours Remaining",f"{hours_left:.0f} h")
    cc.metric("Est. Days to Replace",f"{days_left:.0f} days")

    fig_filter = go.Figure(go.Indicator(
        mode="gauge+number",
        value=round(filter_pct, 1),
        number={'suffix': '%', 'font': {'color': filter_color(filter_pct)}},
        gauge={
            'axis': {'range': [0, 100], 'tickcolor': '#8892b0'},
            'bar': {'color': filter_color(filter_pct)},
            'bgcolor': 'rgba(0,0,0,0)',
            'borderwidth': 0,
            'steps': [
                {'range': [0, 30],  'color': 'rgba(229,57,53,0.15)'},
                {'range': [30, 60], 'color': 'rgba(244,197,66,0.15)'},
                {'range': [60, 100],'color': 'rgba(0,200,150,0.15)'},
            ]
        },
        title={'text': "Filter Life Remaining", 'font': {'color': '#ccd6f6', 'size': 13}}
    ))
    fig_filter.update_layout(height=220, paper_bgcolor='rgba(0,0,0,0)',
        font_color='#ccd6f6', margin=dict(l=10,r=10,t=30,b=0))
    st.plotly_chart(fig_filter, width="stretch")

    st.markdown("---")
    st.markdown('<div class="section-hdr">Personalized Recommendations</div>', unsafe_allow_html=True)
    recs = [
        "🏃 Best exercise window today: 10AM–2PM (forecast AQI below 60)",
        "🪟 Ventilate tonight between 11PM–6AM for lowest outdoor pollution",
        "💧 Maintain indoor humidity 40–60% to reduce allergen proliferation",
        "🌿 Add 2–3 indoor plants (snake plant, peace lily) to supplement purification",
        "📅 Set filter replacement reminder for " + (datetime.now() + timedelta(days=int(days_left))).strftime("%b %d, %Y"),
    ]
    for r in recs:
        st.markdown(f'<div class="tip-card" style="margin-bottom:0.4rem">{r}</div>', unsafe_allow_html=True)


# ═══════════════════════════════
# TAB 5 — SETTINGS & LOGS
# ═══════════════════════════════
with pages[4]:
    col_set, col_log = st.columns([1, 1])

    with col_set:
        st.markdown('<div class="section-hdr">ESP32-S3 Connection</div>', unsafe_allow_html=True)
        esp_ip   = st.text_input("ESP32 IP Address", "192.168.1.100")
        esp_port = st.number_input("Port", value=80, step=1)
        if st.button("Test Connection"):
            try:
                r = requests.get(f"http://{esp_ip}:{esp_port}/sensors", timeout=2)
                st.success(f"Connected! Response: {r.status_code}")
            except Exception as e:
                st.error(f"Cannot reach ESP32: {e}\n(Running in simulation mode)")

        st.code(f"""# Replace get_sensor_data() with:
import requests
def get_sensor_data():
    try:
        r = requests.get(
            'http://{esp_ip}:{esp_port}/sensors',
            timeout=2
        )
        return r.json()
    except:
        return {{}}  # fallback

# Control fan from dashboard:
def set_fan_speed(speed: int):
    requests.get(
        f'http://{esp_ip}:{esp_port}/relay?speed={{speed}}'
    )""", language="python")

        st.markdown('<div class="section-hdr">Notification Settings</div>', unsafe_allow_html=True)
        st.checkbox("Email alerts", value=False)
        st.checkbox("Push notifications", value=True)
        st.checkbox("Sound alarm on hazardous AQI", value=False)
        st.text_input("Alert email", placeholder="you@example.com")

        st.markdown('<div class="section-hdr">Data Retention</div>', unsafe_allow_html=True)
        st.slider("Keep last N readings", 50, 500, 300)
        hdf2 = pd.DataFrame(st.session_state.history)
        if len(hdf2) > 0:
            export2 = hdf2.copy()
            export2['timestamp'] = export2['timestamp'].dt.strftime('%Y-%m-%d %H:%M:%S')
            st.download_button("⬇️ Export All Data (CSV)",
                               export2.to_csv(index=False),
                               "airguard_full_export.csv", "text/csv")

    with col_log:
        st.markdown('<div class="section-hdr">Event Log</div>', unsafe_allow_html=True)
        if st.session_state.event_log:
            for entry in reversed(st.session_state.event_log[-30:]):
                st.markdown(f'<div class="log-entry">{entry}</div>', unsafe_allow_html=True)
        else:
            st.caption("No events yet — events are logged when auto mode changes fan speed, schedule triggers, or manual overrides occur.")

        st.markdown('<div class="section-hdr">System Info</div>', unsafe_allow_html=True)
        info = {
            "Firmware":    "AirGuard v1.0",
            "Board":       "ESP32-S3",
            "Gas Sensor":  "MQ135",
            "Dust Sensor": "GP2Y1010AU0F",
            "Display":     "SSD1306 128×64 OLED",
            "Relay":       "4-channel 5V relay",
            "Dashboard":   "Streamlit + Plotly",
            "Python":      "3.10+",
        }
        for k, v in info.items():
            st.markdown(f'<div class="log-entry"><span style="color:#6b7a99;min-width:100px;display:inline-block">{k}</span> {v}</div>',
                        unsafe_allow_html=True)


st.markdown("<div style='text-align:center;color:#2a3050;font-size:0.72rem;padding:1.2rem'>AirGuard v1.0 · ESP32-S3 + MQ135 + GP2Y1010 · Built with Streamlit</div>",
            unsafe_allow_html=True)

time.sleep(st.session_state.refresh_interval)
st.rerun()
