from flask import Flask, jsonify, render_template, request
from collections import deque
from datetime import datetime
import math
import os
import random
import requests
import threading
import time

app = Flask(__name__)

ESP32_BASE_URL = os.getenv("ESP32_BASE_URL", "").strip()
REQUEST_TIMEOUT = 2.0

state_lock = threading.Lock()
state = {
    "mode": "auto",
    "threshold_voltage": 1.20,
    "fan_on": False,
    "refresh_ms": 2000,
    "source": "mock" if not ESP32_BASE_URL else "esp32",
}

history = deque(maxlen=600)
last_sample = None


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


def get_latest_sample() -> dict:
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
    return sample


def _forward_control_to_esp32(params: dict) -> None:
    if not ESP32_BASE_URL:
        return
    requests.post(f"{ESP32_BASE_URL}/api/control", json=params, timeout=REQUEST_TIMEOUT)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/live")
def api_live():
    sample = get_latest_sample()
    return jsonify(sample)


@app.route("/api/history")
def api_history():
    points = int(request.args.get("points", 60))
    points = max(10, min(points, 600))
    return jsonify(list(history)[-points:])


@app.route("/api/settings", methods=["GET", "POST"])
def api_settings():
    if request.method == "GET":
        with state_lock:
            return jsonify(dict(state))

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


if __name__ == "__main__":
    host = os.getenv("FLASK_HOST", "127.0.0.1")
    port = int(os.getenv("FLASK_PORT", "5000"))
    app.run(host=host, port=port, debug=True, use_reloader=False)
