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
import smtplib
import sqlite3
import threading
import time
from email.message import EmailMessage

app = Flask(__name__)


def _load_dotenv(dotenv_path: str = ".env") -> None:
    if not os.path.exists(dotenv_path):
        return
    try:
        with open(dotenv_path, "r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if not s or s.startswith("#") or "=" not in s:
                    continue
                key, val = s.split("=", 1)
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = val
    except Exception:
        pass


_load_dotenv()
app.secret_key = os.getenv("FLASK_SECRET_KEY", "change-this-secret-in-production")
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.getenv("COOKIE_SECURE", "0") == "1",
)

def _resolve_esp32_base_url() -> str:
    raw = (
        os.getenv("ESP32_BASE_URL", "").strip()
        or os.getenv("ESP32_URL", "").strip()
        or os.getenv("ESP32_HOST", "").strip()
        or os.getenv("ESP32_IP", "").strip()
    )
    if not raw:
        return ""
    if not raw.startswith(("http://", "https://")):
        raw = f"http://{raw}"
    return raw.rstrip("/")


ESP32_BASE_URL = _resolve_esp32_base_url()
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

SMTP_HOST = os.getenv("AIRGUARD_SMTP_HOST", "").strip()
SMTP_PORT = int(os.getenv("AIRGUARD_SMTP_PORT", "587"))
SMTP_USER = os.getenv("AIRGUARD_SMTP_USER", "").strip()
SMTP_PASS = os.getenv("AIRGUARD_SMTP_PASS", "")
SMTP_FROM = os.getenv("AIRGUARD_SMTP_FROM", SMTP_USER or "airguard@localhost").strip()
SMTP_USE_TLS = os.getenv("AIRGUARD_SMTP_USE_TLS", "1").strip() != "0"
ALERT_EMAIL_TO = os.getenv("AIRGUARD_ALERT_EMAIL_TO", "sudhindramacharya@gmail.com").strip()
ALERT_AQI_THRESHOLD = max(50, min(500, int(os.getenv("AIRGUARD_ALERT_AQI_THRESHOLD", "150"))))
ALERT_AQI_HYSTERESIS = max(5, min(50, int(os.getenv("AIRGUARD_ALERT_AQI_HYSTERESIS", "10"))))
ALERT_COOLDOWN_SEC = max(60, int(os.getenv("AIRGUARD_ALERT_COOLDOWN_SEC", "1800")))
OFFLINE_ALERT_COOLDOWN_SEC = max(60, int(os.getenv("AIRGUARD_OFFLINE_ALERT_COOLDOWN_SEC", "1800")))

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
last_esp32_error = ""
chatbot_api_key = os.getenv("CHATBOT_API_KEY", "").strip()
notification_state = {
    "email_to": ALERT_EMAIL_TO,
    "aqi_threshold": ALERT_AQI_THRESHOLD,
    "enabled": bool(ALERT_EMAIL_TO and SMTP_HOST and SMTP_FROM),
    "last_error": "",
    "last_sent_at": "",
    "last_event": "",
    "last_offline_alert_ts": 0.0,
    "last_aqi_alert_ts": 0.0,
    "offline_latched": False,
    "aqi_latched": False,
}


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
        "pm25": round(max(0.0, aqi / 2.1), 1),
        "temperature_c": round(26.0 + random.uniform(-1.2, 1.2), 1),
        "humidity": round(52.0 + random.uniform(-6.0, 6.0), 1),
        "aqi_label": _aqi_label(aqi),
        "fan_on": fan_on,
        "mode": mode,
        "threshold_voltage": threshold,
        "timestamp": _iso_now(),
        "source": "mock",
    }


def _read_esp32_payload() -> dict:
    last_err = None
    raw = None
    # Support both current and older firmware endpoint shapes.
    for path in ("/api/status", "/status"):
        try:
            resp = requests.get(f"{ESP32_BASE_URL}{path}", timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            raw = resp.json()
            break
        except Exception as e:
            last_err = e
            continue

    if raw is None:
        raise RuntimeError(f"ESP32 status fetch failed: {last_err}")

    # Accept common legacy key names used in older sensor payloads.
    voltage = float(raw.get("voltage", raw.get("sensor_voltage", raw.get("mq135_voltage", 0.0))))
    adc = int(raw.get("adc", raw.get("raw_adc", 0)))
    aqi = int(raw.get("aqi", raw.get("aqi_index", _aqi_from_voltage(voltage))))

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
        "pm25": round(float(raw.get("pm25", raw.get("pm_2_5", raw.get("pm", 0.0)))), 1),
        "temperature_c": round(float(raw.get("temperature_c", raw.get("temp_c", raw.get("temperature", 0.0)))), 1),
        "humidity": round(float(raw.get("humidity", raw.get("rh", 0.0))), 1),
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


def _load_last_persisted_sample() -> dict | None:
    conn = _db_conn()
    row = conn.execute(
        """
        SELECT ts, adc, voltage, aqi, aqi_label, fan_on, mode, threshold_voltage, source
        FROM readings
        ORDER BY id DESC
        LIMIT 1
        """
    ).fetchone()
    conn.close()
    if not row:
        return None
    return {
        "adc": int(row["adc"]),
        "voltage": float(row["voltage"]),
        "aqi": int(row["aqi"]),
        "pm25": round(max(0.0, float(row["aqi"]) / 2.1), 1),
        "temperature_c": 0.0,
        "humidity": 0.0,
        "aqi_label": row["aqi_label"] or _aqi_label(int(row["aqi"])),
        "fan_on": bool(row["fan_on"]),
        "mode": row["mode"] or state["mode"],
        "threshold_voltage": float(row["threshold_voltage"]),
        "timestamp": row["ts"],
        "source": row["source"] or "esp32",
    }


def get_latest_sample(persist: bool = True) -> dict:
    global last_sample, last_esp32_error
    try:
        if not ESP32_BASE_URL:
            raise RuntimeError("ESP32_BASE_URL not configured")
        sample = _read_esp32_payload()
        last_esp32_error = ""
    except Exception as e:
        last_esp32_error = str(e)
        # If ESP32 mode is configured, do not inject mock values on transient errors.
        # Return the last real sample so OLED/web stay aligned.
        if ESP32_BASE_URL and last_sample is not None:
            sample = dict(last_sample)
            sample["source"] = "esp32-stale"
            sample["timestamp"] = _iso_now()
        elif ESP32_BASE_URL and last_sample is None:
            fallback = _load_last_persisted_sample()
            if fallback is not None:
                sample = dict(fallback)
                sample["source"] = "esp32-stale"
            else:
                sample = {
                    "adc": 0,
                    "voltage": 0.0,
                    "aqi": 0,
                    "pm25": 0.0,
                    "temperature_c": 0.0,
                    "humidity": 0.0,
                    "aqi_label": "No Data",
                    "fan_on": False,
                    "mode": state["mode"],
                    "threshold_voltage": state["threshold_voltage"],
                    "timestamp": _iso_now(),
                    "source": "esp32-offline",
                }
        else:
            fallback = _load_last_persisted_sample()
            if fallback is not None:
                sample = dict(fallback)
                sample["source"] = "esp32-stale"
            else:
                sample = {
                    "adc": 0,
                    "voltage": 0.0,
                    "aqi": 0,
                    "pm25": 0.0,
                    "temperature_c": 0.0,
                    "humidity": 0.0,
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
    sample["esp32_url"] = ESP32_BASE_URL
    if last_esp32_error:
        sample["esp32_error"] = last_esp32_error

    history.append(sample)
    last_sample = sample
    if persist and sample.get("source") not in {"esp32-stale", "esp32-offline"}:
        _persist_sample(sample)
    if persist:
        _maybe_send_notifications(sample)
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


def _coerce_range(range_key: str) -> tuple[str, str]:
    key = (range_key or "24h").strip().lower()
    mapping = {
        "1h": "-1 hour",
        "24h": "-1 day",
        "7d": "-7 day",
        "1m": "-30 day",
    }
    if key not in mapping:
        key = "24h"
    return key, mapping[key]


def _history_for_range(range_key: str, max_points: int = 500) -> dict:
    max_points = max(30, min(max_points, 3000))
    key, sqlite_window = _coerce_range(range_key)

    conn = _db_conn()
    rows = conn.execute(
        """
        SELECT ts, adc, voltage, aqi, aqi_label, fan_on, mode, threshold_voltage, source
        FROM readings
        WHERE replace(ts, 'T', ' ') >= datetime('now', ?)
        ORDER BY ts ASC
        """,
        (sqlite_window,),
    ).fetchall()

    stats_row = conn.execute(
        """
        SELECT COUNT(*) samples,
               MIN(aqi) min_aqi,
               MAX(aqi) max_aqi,
               AVG(aqi) avg_aqi,
               MIN(voltage) min_voltage,
               MAX(voltage) max_voltage,
               AVG(voltage) avg_voltage
        FROM readings
        WHERE replace(ts, 'T', ' ') >= datetime('now', ?)
        """,
        (sqlite_window,),
    ).fetchone()
    conn.close()

    points = []
    for row in rows:
        point = dict(row)
        point["aqi"] = int(point["aqi"])
        point["voltage"] = float(point["voltage"])
        point["fan_on"] = bool(point["fan_on"])
        point["pm25"] = round(max(0.0, point["aqi"] / 2.1), 1)
        points.append(point)

    if len(points) > max_points:
        stride = max(1, len(points) // max_points)
        points = points[::stride]
        if points and points[-1]["ts"] != rows[-1]["ts"]:
            point = dict(rows[-1])
            point["aqi"] = int(point["aqi"])
            point["voltage"] = float(point["voltage"])
            point["fan_on"] = bool(point["fan_on"])
            point["pm25"] = round(max(0.0, point["aqi"] / 2.1), 1)
            points.append(point)

    stats = dict(stats_row or {})
    samples = int(stats.get("samples") or 0)
    avg_aqi = float(stats.get("avg_aqi") or 0.0)
    min_aqi = int(stats.get("min_aqi") or 0)
    max_aqi = int(stats.get("max_aqi") or 0)
    avg_voltage = float(stats.get("avg_voltage") or 0.0)
    min_voltage = float(stats.get("min_voltage") or 0.0)
    max_voltage = float(stats.get("max_voltage") or 0.0)

    return {
        "range": key,
        "points": points,
        "stats": {
            "samples": samples,
            "avg_aqi": round(avg_aqi, 1) if samples else 0.0,
            "min_aqi": min_aqi if samples else 0,
            "max_aqi": max_aqi if samples else 0,
            "avg_pm25": round(max(0.0, avg_aqi / 2.1), 1) if samples else 0.0,
            "avg_voltage": round(avg_voltage, 3) if samples else 0.0,
            "min_voltage": round(min_voltage, 3) if samples else 0.0,
            "max_voltage": round(max_voltage, 3) if samples else 0.0,
        },
    }


def _smtp_ready() -> tuple[bool, str]:
    if not notification_state.get("enabled"):
        return False, "Email alerts are disabled."
    if not SMTP_HOST:
        return False, "AIRGUARD_SMTP_HOST is not configured."
    if not notification_state.get("email_to"):
        return False, "Recipient email is not configured."
    if not SMTP_FROM:
        return False, "Sender email is not configured."
    return True, ""


def _send_email_alert(subject: str, body: str) -> bool:
    ok, reason = _smtp_ready()
    if not ok:
        notification_state["last_error"] = reason
        return False

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = SMTP_FROM
    msg["To"] = notification_state["email_to"]
    msg.set_content(body)

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as smtp:
            smtp.ehlo()
            if SMTP_USE_TLS:
                smtp.starttls()
                smtp.ehlo()
            if SMTP_USER:
                smtp.login(SMTP_USER, SMTP_PASS)
            smtp.send_message(msg)
        notification_state["last_error"] = ""
        return True
    except Exception as e:
        notification_state["last_error"] = str(e)
        return False


def _mark_alert_attempt(event: str, ts_now: float, field_name: str) -> None:
    notification_state[field_name] = ts_now
    notification_state["last_event"] = event
    if notification_state["last_error"] == "":
        notification_state["last_sent_at"] = _iso_now()


def _try_send_event_alert(event: str, subject: str, body: str, ts_now: float, field_name: str) -> None:
    _send_email_alert(subject, body)
    _mark_alert_attempt(event, ts_now, field_name)


def _notification_status_payload() -> dict:
    ready, reason = _smtp_ready()
    return {
        "enabled": bool(notification_state.get("enabled")),
        "ready": ready,
        "reason": reason,
        "email_to": notification_state.get("email_to"),
        "aqi_threshold": int(notification_state.get("aqi_threshold", ALERT_AQI_THRESHOLD)),
        "last_event": notification_state.get("last_event", ""),
        "last_sent_at": notification_state.get("last_sent_at", ""),
        "last_error": notification_state.get("last_error", ""),
    }


def _maybe_send_notifications(sample: dict) -> None:
    if not notification_state.get("enabled"):
        return

    ts_now = time.time()
    source = str(sample.get("source", ""))
    is_offline = source in {"esp32-offline", "esp32-stale"}
    aqi = int(sample.get("aqi", 0))
    threshold = int(notification_state.get("aqi_threshold", ALERT_AQI_THRESHOLD))
    recovery_threshold = max(0, threshold - ALERT_AQI_HYSTERESIS)

    if is_offline:
        if (
            not notification_state.get("offline_latched")
            and ts_now - float(notification_state.get("last_offline_alert_ts", 0.0)) >= OFFLINE_ALERT_COOLDOWN_SEC
        ):
            err = sample.get("esp32_error") or last_esp32_error or "Unknown connection issue"
            subject = "AirGuard Alert: ESP32 appears offline"
            body = (
                "AirGuard could not reach your ESP32 sensor.\n\n"
                f"Time: {_iso_now()}\n"
                f"Source State: {source}\n"
                f"Last Error: {err}\n"
                f"Dashboard URL: http://127.0.0.1:5000/dashboard\n"
            )
            _try_send_event_alert("esp32_offline", subject, body, ts_now, "last_offline_alert_ts")
            notification_state["offline_latched"] = True
        return

    if notification_state.get("offline_latched"):
        subject = "AirGuard Recovery: ESP32 is reachable again"
        body = (
            "Your ESP32 feed is live again.\n\n"
            f"Time: {_iso_now()}\n"
            f"AQI: {aqi}\n"
            f"Mode: {sample.get('mode', 'auto')}\n"
            f"Fan: {'ON' if sample.get('fan_on') else 'OFF'}\n"
        )
        _try_send_event_alert("esp32_recovered", subject, body, ts_now, "last_offline_alert_ts")
        notification_state["offline_latched"] = False

    if aqi >= threshold:
        if (
            not notification_state.get("aqi_latched")
            and ts_now - float(notification_state.get("last_aqi_alert_ts", 0.0)) >= ALERT_COOLDOWN_SEC
        ):
            subject = f"AirGuard Alert: AQI reached {aqi}"
            body = (
                "Air quality crossed your configured alert threshold.\n\n"
                f"Time: {_iso_now()}\n"
                f"AQI: {aqi} ({sample.get('aqi_label', 'Unknown')})\n"
                f"PM2.5: {sample.get('pm25', 0)} ug/m3\n"
                f"Voltage: {sample.get('voltage', 0)} V\n"
                f"Threshold: {threshold}\n"
                f"Fan: {'ON' if sample.get('fan_on') else 'OFF'}\n"
            )
            _try_send_event_alert("aqi_high", subject, body, ts_now, "last_aqi_alert_ts")
            notification_state["aqi_latched"] = True
    elif aqi <= recovery_threshold and notification_state.get("aqi_latched"):
        subject = f"AirGuard Recovery: AQI back below {recovery_threshold}"
        body = (
            "AQI has dropped back into a safer range.\n\n"
            f"Time: {_iso_now()}\n"
            f"Current AQI: {aqi} ({sample.get('aqi_label', 'Unknown')})\n"
            f"Recovery Threshold: {recovery_threshold}\n"
        )
        _try_send_event_alert("aqi_recovered", subject, body, ts_now, "last_aqi_alert_ts")
        notification_state["aqi_latched"] = False


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


def _mask_key(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}{'*' * (len(value) - 8)}{value[-4:]}"


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


@app.route("/api/esp32-debug")
@require_api_login
def api_esp32_debug():
    status = {
        "esp32_url": ESP32_BASE_URL,
        "configured": bool(ESP32_BASE_URL),
        "last_source": state.get("source"),
        "last_error": last_esp32_error,
        "has_last_sample": last_sample is not None,
    }
    return jsonify(status)


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


@app.route("/api/reports/history")
@require_api_login
def api_reports_history():
    range_key = request.args.get("range", "24h")
    max_points = int(request.args.get("max_points", 500))
    return jsonify(_history_for_range(range_key, max_points=max_points))


@app.route("/api/notifications/status")
@require_api_login
def api_notifications_status():
    return jsonify(_notification_status_payload())


@app.route("/api/notifications/config", methods=["POST"])
@require_api_login
@require_admin_api
def api_notifications_config():
    payload = request.get_json(silent=True) or {}

    if "enabled" in payload:
        notification_state["enabled"] = bool(payload.get("enabled"))

    if "email_to" in payload:
        notification_state["email_to"] = str(payload.get("email_to") or "").strip()

    if "aqi_threshold" in payload:
        threshold = int(payload.get("aqi_threshold") or ALERT_AQI_THRESHOLD)
        notification_state["aqi_threshold"] = max(50, min(500, threshold))

    return jsonify(_notification_status_payload())


@app.route("/api/notifications/test", methods=["POST"])
@require_api_login
@require_admin_api
def api_notifications_test():
    payload = request.get_json(silent=True) or {}
    if "email_to" in payload:
        notification_state["email_to"] = str(payload.get("email_to") or "").strip()

    sample = last_sample or get_latest_sample(persist=False)
    subject = "AirGuard Test Alert: Email notifications are configured"
    body = (
        "This is a test email from AirGuard.\n\n"
        f"Time: {_iso_now()}\n"
        f"AQI: {sample.get('aqi', 0)} ({sample.get('aqi_label', 'Unknown')})\n"
        f"PM2.5: {sample.get('pm25', 0)} ug/m3\n"
        f"Source: {sample.get('source', 'unknown')}\n"
        f"Dashboard URL: http://127.0.0.1:5000/dashboard\n"
    )
    ok = _send_email_alert(subject, body)
    notification_state["last_event"] = "test_alert"
    if ok:
        notification_state["last_sent_at"] = _iso_now()
        return jsonify({"ok": True, "status": _notification_status_payload()})
    return jsonify({"ok": False, "status": _notification_status_payload()}), 500


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


@app.route("/api/chatbot/key", methods=["GET", "POST"])
@require_api_login
def api_chatbot_key():
    global chatbot_api_key
    if request.method == "GET":
        return jsonify({
            "configured": bool(chatbot_api_key),
            "masked": _mask_key(chatbot_api_key),
        })

    if session.get("role") != "admin":
        return jsonify({"error": "Forbidden: admin only"}), 403

    payload = request.get_json(silent=True) or {}
    key = str(payload.get("api_key", "")).strip()
    chatbot_api_key = key
    return jsonify({
        "ok": True,
        "configured": bool(chatbot_api_key),
        "masked": _mask_key(chatbot_api_key),
    })


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
