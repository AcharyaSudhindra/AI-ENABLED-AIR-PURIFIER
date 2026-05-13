from flask import Flask, Response, jsonify, render_template, request, redirect, url_for, session
from collections import deque
from datetime import datetime, timedelta
from functools import wraps
import csv
import json
import math
import os
import random
import requests
import sqlite3
import threading
import time

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "change-this-secret-in-production")
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.getenv("COOKIE_SECURE", "0") == "1",
)

ESP32_BASE_URL = os.getenv("ESP32_BASE_URL", "").strip()
REQUEST_TIMEOUT = 2.0

DB_DIR = os.path.join(os.getcwd(), "data")
LOG_DIR = os.path.join(os.getcwd(), "logs")
os.makedirs(DB_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)
DB_PATH = os.path.join(DB_DIR, "airguard.db")
CSV_PATH = os.path.join(LOG_DIR, "air_readings.csv")

ADMIN_USER = os.getenv("AIRGUARD_ADMIN_USER", "admin")
ADMIN_PASS = os.getenv("AIRGUARD_ADMIN_PASS", "admin123")
VIEWER_USER = os.getenv("AIRGUARD_VIEWER_USER", "viewer")
VIEWER_PASS = os.getenv("AIRGUARD_VIEWER_PASS", "viewer123")

state_lock = threading.Lock()
state = {
    "mode": "auto",
    "threshold_voltage": 1.20,
    "fan_on": False,
    "refresh_ms": 2000,
    "source": "esp32" if ESP32_BASE_URL else "esp32-offline",
}
filter_state = {
    "health_pct": 100.0,
    "runtime_hours": 0.0,
    "load_score": 0.0,
    "status": "Excellent",
    "last_reset": _iso_now() if "_iso_now" in globals() else "",
}
last_filter_update_ts = time.time()

history = deque(maxlen=800)
last_sample = None
stop_event = threading.Event()


def _db_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_storage():
    conn = _db_conn()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS readings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            adc INTEGER NOT NULL,
            voltage REAL NOT NULL,
            aqi INTEGER NOT NULL,
            aqi_label TEXT NOT NULL,
            fan_on INTEGER NOT NULL,
            mode TEXT NOT NULL,
            threshold_voltage REAL NOT NULL,
            source TEXT NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()

    if not os.path.exists(CSV_PATH):
        with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "timestamp",
                "adc",
                "voltage",
                "aqi",
                "aqi_label",
                "fan_on",
                "mode",
                "threshold_voltage",
                "source",
            ])


def require_login(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapper


def require_api_login(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if "user" not in session:
            return jsonify({"error": "Unauthorized"}), 401
        return fn(*args, **kwargs)
    return wrapper


def require_admin_api(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if session.get("role") != "admin":
            return jsonify({"error": "Forbidden: admin only"}), 403
        return fn(*args, **kwargs)
    return wrapper


def _iso_now() -> str:
    return datetime.now().isoformat(timespec="seconds")


if not filter_state.get("last_reset"):
    filter_state["last_reset"] = _iso_now()


def _aqi_from_voltage(voltage: float) -> int:
    scaled = int((voltage / 3.3) * 500)
    return max(0, min(500, scaled))


def _aqi_label(aqi: int) -> str:
    if aqi <= 50:
        return "Good"
    if aqi <= 100:
        return "Moderate"
    if aqi <= 150:
        return "Unhealthy"
    if aqi <= 200:
        return "Very Unhealthy"
    return "Hazardous"


def _filter_status(health_pct: float) -> str:
    if health_pct >= 75:
        return "Excellent"
    if health_pct >= 50:
        return "Good"
    if health_pct >= 30:
        return "Replace Soon"
    return "Critical"


def _update_filter_health(sample: dict) -> None:
    global last_filter_update_ts
    now_ts = time.time()
    dt_hours = max(0.0, (now_ts - last_filter_update_ts) / 3600.0)
    last_filter_update_ts = now_ts

    aqi = float(sample.get("aqi", 0))
    fan_on = bool(sample.get("fan_on", False))
    if not fan_on:
        return

    # Base lifetime model: 720 runtime hours at moderate load, adjusted by AQI.
    load_factor = 1.0 + max(0.0, (aqi - 70.0) / 220.0)
    wear_pct = (dt_hours / 720.0) * 100.0 * load_factor
    filter_state["health_pct"] = max(0.0, filter_state["health_pct"] - wear_pct)
    filter_state["runtime_hours"] += dt_hours
    filter_state["load_score"] = 0.85 * filter_state["load_score"] + 0.15 * min(200.0, aqi)
    filter_state["status"] = _filter_status(filter_state["health_pct"])


def _predict_aqi_points(horizon: int = 12) -> list:
    samples = list(history)[-60:]
    if len(samples) < 6:
        return []

    aqi_vals = [float(s.get("aqi", 0)) for s in samples]
    n = len(aqi_vals)
    x_mean = (n - 1) / 2.0
    y_mean = sum(aqi_vals) / n
    denom = sum((i - x_mean) ** 2 for i in range(n)) or 1.0
    slope = sum((i - x_mean) * (aqi_vals[i] - y_mean) for i in range(n)) / denom
    interval_sec = max(1.0, state.get("refresh_ms", 2000) / 1000.0)
    # Convert per-sample slope into forecast step (10-minute points).
    samples_per_step = max(1.0, 600.0 / interval_sec)
    drift_per_step = slope * samples_per_step

    base = aqi_vals[-1]
    out = []
    for i in range(1, horizon + 1):
        pred = max(0.0, min(500.0, base + drift_per_step * i))
        ts = datetime.now() + timedelta(minutes=10 * i)
        out.append({"time": ts.strftime("%H:%M"), "aqi": round(pred, 1)})
    return out


def _mock_sensor_payload() -> dict:
    t = time.time() / 8.0
    base_voltage = 1.05 + 0.28 * math.sin(t) + random.uniform(-0.06, 0.06)
    voltage = max(0.2, min(2.6, base_voltage))
    adc = int((voltage / 3.3) * 4095)
    aqi = _aqi_from_voltage(voltage)

    with state_lock:
        threshold = state["threshold_voltage"]
        mode = state["mode"]
        fan_on = state["fan_on"]
        if mode == "auto":
            fan_on = voltage >= threshold
            state["fan_on"] = fan_on

    return {
        "adc": adc,
        "voltage": round(voltage, 3),
        "aqi": aqi,
        "aqi_label": _aqi_label(aqi),
        "fan_on": fan_on,
        "mode": mode,
        "threshold_voltage": threshold,
        "timestamp": _iso_now(),
        "source": "mock",
    }


def _read_esp32_payload() -> dict:
    resp = requests.get(f"{ESP32_BASE_URL}/api/status", timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    raw = resp.json()

    voltage = float(raw.get("voltage", 0.0))
    adc = int(raw.get("adc", 0))
    aqi = int(raw.get("aqi", _aqi_from_voltage(voltage)))

    with state_lock:
        if "mode" in raw:
            state["mode"] = str(raw["mode"]).lower()
        if "threshold_voltage" in raw:
            state["threshold_voltage"] = float(raw["threshold_voltage"])
        if "fan_on" in raw:
            state["fan_on"] = bool(raw["fan_on"])

        mode = state["mode"]
        threshold = state["threshold_voltage"]
        fan_on = state["fan_on"]

    return {
        "adc": adc,
        "voltage": round(voltage, 3),
        "aqi": aqi,
        "aqi_label": _aqi_label(aqi),
        "fan_on": fan_on,
        "mode": mode,
        "threshold_voltage": threshold,
        "timestamp": raw.get("timestamp", _iso_now()),
        "source": "esp32",
    }


def _persist_sample(sample: dict):
    conn = _db_conn()
    conn.execute(
        """
        INSERT INTO readings (ts, adc, voltage, aqi, aqi_label, fan_on, mode, threshold_voltage, source)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            sample["timestamp"],
            sample["adc"],
            sample["voltage"],
            sample["aqi"],
            sample["aqi_label"],
            int(sample["fan_on"]),
            sample["mode"],
            sample["threshold_voltage"],
            sample["source"],
        ),
    )
    conn.commit()
    conn.close()

    with open(CSV_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            sample["timestamp"], sample["adc"], sample["voltage"], sample["aqi"],
            sample["aqi_label"], int(sample["fan_on"]), sample["mode"],
            sample["threshold_voltage"], sample["source"]
        ])


def get_latest_sample(persist: bool = True) -> dict:
    global last_sample
    try:
        if not ESP32_BASE_URL:
            raise RuntimeError("ESP32_BASE_URL not configured")
        sample = _read_esp32_payload()
    except Exception:
        # If ESP32 mode is configured, do not inject mock values on transient errors.
        # Return the last real sample so OLED/web stay aligned.
        if ESP32_BASE_URL and last_sample is not None:
            sample = dict(last_sample)
            sample["source"] = "esp32-stale"
            sample["timestamp"] = _iso_now()
        elif ESP32_BASE_URL and last_sample is None:
            sample = {
                "adc": 0,
                "voltage": 0.0,
                "aqi": 0,
                "aqi_label": "No Data",
                "fan_on": False,
                "mode": state["mode"],
                "threshold_voltage": state["threshold_voltage"],
                "timestamp": _iso_now(),
                "source": "esp32-offline",
            }
        else:
            sample = {
                "adc": 0,
                "voltage": 0.0,
                "aqi": 0,
                "aqi_label": "No Data",
                "fan_on": False,
                "mode": state["mode"],
                "threshold_voltage": state["threshold_voltage"],
                "timestamp": _iso_now(),
                "source": "esp32-offline",
            }

    with state_lock:
        state["source"] = sample["source"]

    _update_filter_health(sample)
    sample["filter_health_pct"] = round(filter_state["health_pct"], 1)
    sample["filter_status"] = filter_state["status"]

    history.append(sample)
    last_sample = sample
    if persist and sample.get("source") not in {"esp32-stale", "esp32-offline"}:
        _persist_sample(sample)
    return sample


def sampling_worker():
    while not stop_event.is_set():
        try:
            get_latest_sample(persist=True)
        except Exception:
            pass
        sleep_ms = state.get("refresh_ms", 2000)
        stop_event.wait(max(0.5, sleep_ms / 1000.0))


def _forward_control_to_esp32(params: dict) -> None:
    if not ESP32_BASE_URL:
        return
    requests.post(f"{ESP32_BASE_URL}/api/control", json=params, timeout=REQUEST_TIMEOUT)


def _daily_report_for(days: int = 7):
    conn = _db_conn()
    rows = conn.execute(
        """
        SELECT substr(ts,1,10) day,
               AVG(aqi) avg_aqi,
               MAX(aqi) peak_aqi,
               MIN(aqi) min_aqi,
               AVG(voltage) avg_voltage,
               SUM(CASE WHEN fan_on=1 THEN 1 ELSE 0 END) fan_on_samples,
               COUNT(*) samples
        FROM readings
        WHERE ts >= datetime('now', ?)
        GROUP BY substr(ts,1,10)
        ORDER BY day DESC
        """,
        (f"-{days} day",),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _latest_stats():
    conn = _db_conn()
    row = conn.execute(
        """
        SELECT COUNT(*) total_samples,
               AVG(aqi) avg_aqi,
               MAX(aqi) peak_aqi,
               AVG(voltage) avg_voltage
        FROM readings
        WHERE ts >= datetime('now', '-1 day')
        """
    ).fetchone()
    conn.close()
    return dict(row)


def _chatbot_answer(msg: str) -> str:
    text = msg.lower().strip()
    stats = _latest_stats()
    avg_aqi = int(stats.get("avg_aqi") or 0)
    peak = int(stats.get("peak_aqi") or 0)
    sample = last_sample or get_latest_sample(persist=False)
    aqi = int(sample.get("aqi", 0))
    fan = "ON" if sample.get("fan_on") else "OFF"
    mode = str(sample.get("mode", "auto")).upper()
    voltage = float(sample.get("voltage", 0.0))

    if aqi <= 50:
        risk = "good"
        action = "Current air is healthy. Keep purifier on LOW/AUTO for maintenance."
    elif aqi <= 100:
        risk = "moderate"
        action = "Air is moderate. AUTO mode is recommended."
    elif aqi <= 150:
        risk = "unhealthy"
        action = "Air is unhealthy for sensitive groups. Keep fan HIGH and reduce indoor pollutants."
    else:
        risk = "hazardous"
        action = "Air quality is hazardous. Run purifier high, ventilate, and avoid exposure."

    if any(k in text for k in ["status", "now", "current"]):
        return (
            f"Current AQI is {aqi} ({sample['aqi_label']}). "
            f"Voltage is {voltage:.2f}V. Fan is {fan} in {mode} mode. "
            f"Risk level: {risk.upper()}. {action}"
        )
    if "report" in text or "daily" in text:
        return (
            f"Daily report summary: 24h average AQI is {avg_aqi}, peak AQI is {peak}. "
            f"Current AQI is {aqi} ({sample['aqi_label']}). "
            f"Open Reports page for day-wise trend and fan runtime analysis."
        )
    if "recommend" in text or "what should i do" in text:
        return (
            f"My recommendation now: {action} "
            f"Current mode is {mode}; fan is {fan}. "
            f"If AQI stays above 100 for long periods, check filter and room ventilation."
        )
    if "improve" in text or "tips" in text:
        return (
            "Top improvements: keep purifier in AUTO near breathing-zone height, "
            "avoid indoor smoke/aerosols, clean dust sources weekly, replace filters on schedule, "
            "and ventilate briefly when outdoor air is better than indoor air."
        )
    if "fan" in text:
        return (
            f"Fan is currently {fan} in {mode} mode. "
            "In AUTO, fan follows threshold voltage. In MANUAL, admin can force ON/OFF from Controls page."
        )
    return (
        "I can help with live status, daily reports, fan recommendations, and air-quality optimization. "
        "Try: 'current status', 'daily report', or 'fan recommendation now'."
    )


@app.route("/")
def root():
    if "user" in session:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if "user" in session:
        return redirect(url_for("dashboard"))

    if request.method == "GET":
        return render_template("login.html")

    username = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""

    if username == ADMIN_USER and password == ADMIN_PASS:
        session["user"] = username
        session["role"] = "admin"
        return redirect(url_for("dashboard"))
    if username == VIEWER_USER and password == VIEWER_PASS:
        session["user"] = username
        session["role"] = "viewer"
        return redirect(url_for("dashboard"))

    return render_template("login.html", error="Invalid username or password")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/dashboard")
@require_login
def dashboard():
    return render_template("dashboard.html", user=session.get("user"), role=session.get("role"))


@app.route("/reports")
@require_login
def reports_page():
    return render_template("reports.html", user=session.get("user"), role=session.get("role"))


@app.route("/controls")
@require_login
def controls_page():
    return render_template("controls.html", user=session.get("user"), role=session.get("role"))


@app.route("/chatbot")
@require_login
def chatbot_page():
    return render_template("chatbot.html", user=session.get("user"), role=session.get("role"))


@app.route("/api/live")
@require_api_login
def api_live():
    # Force a fresh read for better OLED/web sync.
    sample = get_latest_sample(persist=False)
    return jsonify(sample)


@app.route("/api/predict")
@require_api_login
def api_predict():
    horizon = int(request.args.get("horizon", 12))
    horizon = max(3, min(horizon, 24))
    return jsonify({"points": _predict_aqi_points(horizon)})


@app.route("/api/filter-health")
@require_api_login
def api_filter_health():
    return jsonify({
        "health_pct": round(filter_state["health_pct"], 1),
        "runtime_hours": round(filter_state["runtime_hours"], 2),
        "load_score": round(filter_state["load_score"], 1),
        "status": filter_state["status"],
        "last_reset": filter_state["last_reset"],
    })


@app.route("/api/filter/reset", methods=["POST"])
@require_api_login
@require_admin_api
def api_filter_reset():
    filter_state["health_pct"] = 100.0
    filter_state["runtime_hours"] = 0.0
    filter_state["load_score"] = 0.0
    filter_state["status"] = "Excellent"
    filter_state["last_reset"] = _iso_now()
    return jsonify({"ok": True})


@app.route("/api/stream")
@require_api_login
def api_stream():
    def event_stream():
        while True:
            sample = get_latest_sample(persist=False)
            payload = json.dumps(sample)
            yield f"retry: 2000\n"
            yield f"data: {payload}\n\n"
            sleep_ms = state.get("refresh_ms", 2000)
            time.sleep(max(0.5, sleep_ms / 1000.0))

    return Response(
        event_stream(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/api/history")
@require_api_login
def api_history():
    points = int(request.args.get("points", 60))
    points = max(10, min(points, 600))
    return jsonify(list(history)[-points:])


@app.route("/api/settings", methods=["GET", "POST"])
@require_api_login
def api_settings():
    if request.method == "GET":
        with state_lock:
            return jsonify(dict(state))

    if session.get("role") != "admin":
        return jsonify({"error": "Forbidden: admin only"}), 403

    payload = request.get_json(silent=True) or {}
    updates = {}

    with state_lock:
        if "mode" in payload:
            mode = str(payload["mode"]).lower()
            if mode in {"auto", "manual"}:
                state["mode"] = mode
                updates["mode"] = mode

        if "threshold_voltage" in payload:
            threshold = float(payload["threshold_voltage"])
            threshold = max(0.2, min(3.0, threshold))
            state["threshold_voltage"] = threshold
            updates["threshold_voltage"] = threshold

        if "refresh_ms" in payload:
            refresh_ms = int(payload["refresh_ms"])
            refresh_ms = max(500, min(10000, refresh_ms))
            state["refresh_ms"] = refresh_ms

        if "fan_on" in payload:
            fan_on = bool(payload["fan_on"])
            state["fan_on"] = fan_on
            updates["fan_on"] = fan_on

        new_state = dict(state)

    if updates:
        try:
            _forward_control_to_esp32(updates)
        except Exception:
            pass

    return jsonify(new_state)


@app.route("/api/fan", methods=["POST"])
@require_api_login
@require_admin_api
def api_fan():
    payload = request.get_json(silent=True) or {}
    on = bool(payload.get("on", False))

    with state_lock:
        if state["mode"] == "manual":
            state["fan_on"] = on
        new_state = dict(state)

    try:
        _forward_control_to_esp32({"fan_on": on})
    except Exception:
        pass

    return jsonify(new_state)


@app.route("/api/reports/daily")
@require_api_login
def api_reports_daily():
    days = int(request.args.get("days", 7))
    days = max(1, min(days, 30))
    return jsonify(_daily_report_for(days))


@app.route("/api/reports/summary")
@require_api_login
def api_reports_summary():
    return jsonify(_latest_stats())


@app.route("/api/chat", methods=["POST"])
@require_api_login
def api_chat():
    payload = request.get_json(silent=True) or {}
    msg = str(payload.get("message", "")).strip()
    if not msg:
        return jsonify({"reply": "Please type a question."})
    return jsonify({"reply": _chatbot_answer(msg)})


init_storage()
if last_sample is None:
    try:
        get_latest_sample(persist=True)
    except Exception:
        pass

worker_thread = threading.Thread(target=sampling_worker, daemon=True)
worker_thread.start()

if __name__ == "__main__":
    host = os.getenv("FLASK_HOST", "127.0.0.1")
    port = int(os.getenv("FLASK_PORT", "5000"))
    app.run(host=host, port=port, debug=True, use_reloader=False)
