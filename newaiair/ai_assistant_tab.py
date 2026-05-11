"""
AirGuard AI Chat Tab — add this to your existing app.py

In your app.py tabs, add:

    pages = st.tabs(["📊 Dashboard", "📈 Analytics", "🌤️ Forecast",
                      "🤖 AI Insights", "💬 AI Assistant", "⚙️ Settings"])

Then add this file's content as the new tab section.

Alternatively, run this as standalone:
    streamlit run ai_assistant_tab.py
"""

import streamlit as st
import requests
import json
from datetime import datetime

CLOUD_SERVER = "http://localhost:5000"  # change to your PC's IP if running remotely

def ask_cloud(query: str, extra_sensors: dict = None) -> dict:
    """Send a text query to the cloud server."""
    try:
        payload = {"query": query}
        if extra_sensors:
            payload["sensors"] = extra_sensors
        r = requests.post(f"{CLOUD_SERVER}/ask", json=payload, timeout=20)
        return r.json()
    except Exception as e:
        return {"error": str(e), "response": f"Connection error: {e}"}

def get_server_sensors() -> dict:
    """Fetch latest sensor data from cloud server (which got it from ESP32)."""
    try:
        r = requests.get(f"{CLOUD_SERVER}/sensors", timeout=3)
        return r.json()
    except:
        return {}

def get_conversation_history() -> list:
    try:
        r = requests.get(f"{CLOUD_SERVER}/history", timeout=3)
        return r.json().get("history", [])
    except:
        return []

# ── Standalone page config (comment out if embedding in main app.py) ──────────
st.set_page_config(page_title="AirGuard AI Assistant", page_icon="🤖", layout="wide")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap');
html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

.chat-user {
  background: #1a3a5c;
  border: 1px solid #2a5080;
  border-radius: 12px 12px 4px 12px;
  padding: 0.8rem 1rem;
  margin: 0.5rem 0 0.5rem 3rem;
  color: #ccd6f6;
  font-size: 0.9rem;
}
.chat-ai {
  background: #1a2535;
  border: 1px solid #2a3550;
  border-radius: 12px 12px 12px 4px;
  padding: 0.8rem 1rem;
  margin: 0.5rem 3rem 0.5rem 0;
  color: #e8eef8;
  font-size: 0.9rem;
  line-height: 1.6;
}
.chat-label-user { font-size: 0.7rem; color: #378add; text-align: right; margin-right: 0.5rem; }
.chat-label-ai   { font-size: 0.7rem; color: #00c896; margin-left: 0.5rem; }
.chat-time        { font-size: 0.65rem; color: #4a5568; }

.sensor-mini {
  background: #161d2e;
  border: 1px solid #2a3550;
  border-radius: 8px;
  padding: 0.5rem 0.8rem;
  font-size: 0.78rem;
  color: #8892b0;
}
.quick-btn-row { display: flex; flex-wrap: wrap; gap: 0.4rem; margin: 0.5rem 0; }

.status-dot-online  { color: #00c896; }
.status-dot-offline { color: #e53935; }
</style>
""", unsafe_allow_html=True)


# ── Session init ──────────────────────────────────────────────────────────────
if 'chat_messages' not in st.session_state:
    st.session_state.chat_messages = []
if 'server_online' not in st.session_state:
    st.session_state.server_online = False

# ── Check server status ───────────────────────────────────────────────────────
try:
    r = requests.get(f"{CLOUD_SERVER}/health", timeout=2)
    st.session_state.server_online = r.status_code == 200
except:
    st.session_state.server_online = False

# ── Layout ────────────────────────────────────────────────────────────────────
col_chat, col_sidebar = st.columns([2, 1])

with col_sidebar:
    st.markdown("### 🤖 AirGuard AI")

    status_icon = "🟢" if st.session_state.server_online else "🔴"
    status_text = "Cloud server online" if st.session_state.server_online else "Cloud server offline"
    st.markdown(f"{status_icon} **{status_text}**")

    if not st.session_state.server_online:
        st.warning("Start `python cloud_server.py` on your PC")
        st.code("python cloud_server.py", language="bash")

    st.markdown("---")

    # Live sensor snapshot
    st.markdown("**Live Sensor Snapshot**")
    sensors = get_server_sensors()
    if sensors:
        aqi = sensors.get('aqi', '–')
        st.markdown(f"""
        <div class="sensor-mini">
          AQI: <b style='color:#378add'>{aqi}</b> &nbsp;|&nbsp;
          PM2.5: {sensors.get('pm25','–')} µg/m³<br>
          VOC: {sensors.get('voc','–')} ppm &nbsp;|&nbsp;
          CO₂: {sensors.get('co2','–')} ppm<br>
          Temp: {sensors.get('temp','–')}°C &nbsp;|&nbsp;
          Hum: {sensors.get('humidity','–')}%<br>
          Purifier: {'ON' if sensors.get('purifier') else 'OFF'} &nbsp;|&nbsp;
          Filter: {sensors.get('filter_pct','–')}%
        </div>""", unsafe_allow_html=True)
    else:
        st.markdown('<div class="sensor-mini">No sensor data yet — ESP32 not connected</div>',
                    unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("**Quick Questions**")

    quick_questions = [
        ("🌬️", "What's the current AQI?"),
        ("🪟", "Should I open windows?"),
        ("🏃", "Safe for indoor exercise?"),
        ("⚡", "Set fan to recommended speed"),
        ("🔧", "How's the filter health?"),
        ("☠️", "Any dangerous pollutants?"),
        ("📊", "Air quality summary"),
        ("🌙", "Is it safe to sleep?"),
    ]
    for icon, q in quick_questions:
        if st.button(f"{icon} {q}", key=f"quick_{q}", use_container_width=False):
            st.session_state.chat_messages.append({
                "role": "user", "content": q, "time": datetime.now().strftime("%H:%M")
            })
            with st.spinner("Asking Claude..."):
                result = ask_cloud(q)
            ai_resp = result.get("response", "Error getting response")
            st.session_state.chat_messages.append({
                "role": "assistant", "content": ai_resp, "time": datetime.now().strftime("%H:%M")
            })
            st.rerun()

    st.markdown("---")
    if st.button("🗑️ Clear Chat", use_container_width=True):
        st.session_state.chat_messages = []
        try:
            requests.post(f"{CLOUD_SERVER}/history/clear", timeout=2)
        except:
            pass
        st.rerun()

    # ESP32 connection config
    with st.expander("⚙️ Server Config"):
        new_server = st.text_input("Cloud Server URL", CLOUD_SERVER)
        if new_server != CLOUD_SERVER:
            CLOUD_SERVER = new_server
        st.caption("Format: http://IP:5000")
        st.code("""# Run on your PC:
python cloud_server.py

# Set ANTHROPIC_API_KEY:
export ANTHROPIC_API_KEY=sk-ant-xxx
""", language="bash")


with col_chat:
    st.markdown("### 💬 Chat with AirGuard AI")
    st.caption("Ask anything about your air quality. The AI has full context of your sensor data.")

    # Chat history display
    chat_container = st.container()
    with chat_container:
        if not st.session_state.chat_messages:
            st.markdown("""
            <div style="text-align:center;padding:3rem;color:#4a5568">
              <div style="font-size:2.5rem">🌬️</div>
              <div style="font-size:1rem;margin-top:0.5rem">AirGuard AI is ready</div>
              <div style="font-size:0.82rem;margin-top:0.3rem;color:#3a4560">
                Ask about your air quality, health advice, or purifier control
              </div>
            </div>""", unsafe_allow_html=True)

        for msg in st.session_state.chat_messages:
            if msg["role"] == "user":
                st.markdown(
                    f'<div class="chat-label-user">You · {msg.get("time","")}</div>'
                    f'<div class="chat-user">👤 {msg["content"]}</div>',
                    unsafe_allow_html=True
                )
            else:
                st.markdown(
                    f'<div class="chat-label-ai">🤖 AirGuard AI · {msg.get("time","")}</div>'
                    f'<div class="chat-ai">{msg["content"]}</div>',
                    unsafe_allow_html=True
                )

    st.markdown("---")

    # Input area
    col_input, col_send = st.columns([5, 1])
    with col_input:
        user_input = st.text_input(
            "Type your question...",
            placeholder="e.g. Is the air quality safe for my baby?",
            label_visibility="collapsed",
            key="chat_input"
        )
    with col_send:
        send_clicked = st.button("Send ➤", use_container_width=True)

    # Voice note (for when mic is added)
    st.caption("💡 When INMP441 microphone is connected, hold BOOT button on ESP32 to speak")

    if (send_clicked or user_input) and user_input.strip():
        msg_text = user_input.strip()
        st.session_state.chat_messages.append({
            "role": "user", "content": msg_text, "time": datetime.now().strftime("%H:%M")
        })

        with st.spinner("🤖 Asking Claude AI..."):
            result = ask_cloud(msg_text)

        ai_resp = result.get("response", "Sorry, I couldn't get a response.")
        st.session_state.chat_messages.append({
            "role": "assistant", "content": ai_resp, "time": datetime.now().strftime("%H:%M")
        })
        st.rerun()

    # Show full conversation history from server
    with st.expander("📜 Full Server Conversation History"):
        history = get_conversation_history()
        if history:
            for h in history:
                role_icon = "👤" if h["role"] == "user" else "🤖"
                st.markdown(f"**{role_icon} {h['role'].title()}:** {h['content'][:200]}...")
        else:
            st.caption("No history yet")
