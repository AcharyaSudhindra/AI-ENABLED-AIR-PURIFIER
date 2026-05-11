from flask import Flask, jsonify, render_template, request, redirect, url_for, session
from collections import deque
from datetime import datetime, timedelta
from functools import wraps
import csv
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
    "source": "mock" if not ESP32_BASE_URL else "esp32",
}

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
        sample = _read_esp32_payload() if ESP32_BASE_URL else _mock_sensor_payload()
    except Exception:
        sample = _mock_sensor_payload()
        sample["source"] = "mock-fallback"

    with state_lock:
        state["source"] = sample["source"]

    history.append(sample)
    last_sample = sample
    if persist:
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

    if any(k in text for k in ["status", "now", "current"]):
        sample = last_sample or get_latest_sample(persist=False)
        return f"Current AQI is {sample['aqi']} ({sample['aqi_label']}). Fan is {'ON' if sample['fan_on'] else 'OFF'} in {sample['mode'].upper()} mode."
    if "report" in text or "daily" in text:
        return f"In the last 24h, average AQI is {avg_aqi} and peak AQI is {peak}. Open Reports page for day-wise breakdown."
    if "improve" in text or "tips" in text:
        return "Keep windows briefly open in early morning, replace filters on schedule, avoid indoor smoke/aerosols, and keep purifier in AUTO mode near breathing zone height."
    if "fan" in text:
        return "In AUTO mode the fan responds to threshold voltage. In MANUAL mode, only admin can force Fan ON/OFF from Controls page."
    return "I can help with current air status, daily reports, fan behavior, and indoor air improvement tips. Try: 'current status' or 'daily report'."


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
    sample = last_sample or get_latest_sample(persist=False)
    return jsonify(sample)


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
