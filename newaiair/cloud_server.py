"""
╔══════════════════════════════════════════════════════════════════╗
║   AirGuard Cloud Bridge Server                                  ║
║   Runs on your PC / Raspberry Pi on the same WiFi network       ║
║                                                                  ║
║   Flow:                                                          ║
║   ESP32 → [TCP JSON + audio] → THIS SERVER → Claude API         ║
║         ← [TTS audio / text] ←─────────────────────────         ║
║                                                                  ║
║   Also provides REST API for Streamlit dashboard                 ║
╚══════════════════════════════════════════════════════════════════╝

Install:
    pip install anthropic openai flask requests numpy

Run:
    python cloud_server.py

Make sure ANTHROPIC_API_KEY is set in environment or in config below.
"""

import asyncio
import socket
import struct
import json
import threading
import time
import io
import wave
import os
import logging
from datetime import datetime
from flask import Flask, jsonify, request

import anthropic

# ── Optional: OpenAI for TTS (or use gTTS for free) ──────────────────────────
# from openai import OpenAI
# from gtts import gTTS  # pip install gtts

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger("AirGuard")

# ─── Config ───────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY  = os.getenv("ANTHROPIC_API_KEY", "sk-ant-YOUR_KEY_HERE")
TCP_HOST           = "0.0.0.0"
TCP_PORT           = 8765       # ESP32 connects here
HTTP_PORT          = 5000       # Streamlit / dashboard REST API
USE_TTS            = False      # Set True when speaker is connected + OpenAI key ready
RESPONSE_AS_TEXT   = True       # Send text back (shown on OLED) when no speaker

# ─── Claude System Prompt ─────────────────────────────────────────────────────
SYSTEM_PROMPT = """You are AirGuard, an advanced AI assistant embedded in a smart home air purifier system.
You have real-time access to indoor air quality sensor data from an ESP32-S3 device.

Sensors available:
- MQ135: VOC (volatile organic compounds) and CO₂ levels in ppm
- GP2Y1010: Dust/particulate matter (PM2.5 and PM10) in µg/m³
- Calculated AQI (Air Quality Index, 0-500 scale)
- Temperature (°C) and Humidity (%)

AQI Scale:
- 0-50:   Good (Green) — Safe for everyone
- 51-100: Moderate (Yellow) — Acceptable, sensitive groups may be affected
- 101-150: Unhealthy for Sensitive Groups (Orange)
- 151-200: Unhealthy (Red) — Everyone affected
- 201+:   Very Unhealthy / Hazardous (Purple/Maroon)

You can control the purifier by including commands in your response:
- Include "TURN ON" to activate the purifier
- Include "TURN OFF" to deactivate
- Include "FAN HIGH", "FAN MEDIUM", "FAN LOW" to set speed

Keep responses concise (under 100 words) since they display on a small OLED screen.
Be practical, specific, and health-focused.
If AQI > 150, be urgent and clear about actions to take."""

# ─── In-memory state ──────────────────────────────────────────────────────────
latest_sensor_data = {}
conversation_history = []  # Multi-turn conversation memory
MAX_HISTORY = 10

# ─── Claude API Call ──────────────────────────────────────────────────────────
def call_claude(user_message: str, sensor_context: dict) -> str:
    global conversation_history

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    # Build sensor context string
    ctx = f"""Current sensor readings:
• AQI: {sensor_context.get('aqi', 'N/A')} ({aqi_label(sensor_context.get('aqi', 0))})
• PM2.5: {sensor_context.get('pm25', 'N/A')} µg/m³
• PM10: {sensor_context.get('pm10', 'N/A')} µg/m³
• VOC: {sensor_context.get('voc', 'N/A')} ppm
• CO₂: {sensor_context.get('co2', 'N/A')} ppm
• Temperature: {sensor_context.get('temp', 'N/A')}°C
• Humidity: {sensor_context.get('humidity', 'N/A')}%
• Purifier: {'ON' if sensor_context.get('purifier') else 'OFF'}
• Fan Speed: {['OFF','LOW','MEDIUM','HIGH'][int(sensor_context.get('fan_speed', 1))]}
• Filter Life: {sensor_context.get('filter_pct', 'N/A')}%

User query: {user_message}"""

    # Add to conversation history
    conversation_history.append({"role": "user", "content": ctx})
    if len(conversation_history) > MAX_HISTORY * 2:
        conversation_history = conversation_history[-(MAX_HISTORY * 2):]

    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=300,
            system=SYSTEM_PROMPT,
            messages=conversation_history
        )
        ai_text = response.content[0].text
        conversation_history.append({"role": "assistant", "content": ai_text})
        log.info(f"Claude response: {ai_text[:100]}...")
        return ai_text

    except Exception as e:
        log.error(f"Claude API error: {e}")
        return f"AI error: {str(e)[:80]}"


def aqi_label(aqi):
    try:
        aqi = float(aqi)
        if aqi <= 50:   return "Good"
        if aqi <= 100:  return "Moderate"
        if aqi <= 150:  return "Unhealthy"
        if aqi <= 200:  return "Very Unhealthy"
        return "Hazardous"
    except:
        return "Unknown"


# ─── Speech-to-Text (Whisper via OpenAI) ────────────────────────────────────
def transcribe_audio(wav_bytes: bytes) -> str:
    """Transcribe WAV audio using OpenAI Whisper API."""
    try:
        from openai import OpenAI
        client = OpenAI()  # uses OPENAI_API_KEY env var
        audio_file = io.BytesIO(wav_bytes)
        audio_file.name = "audio.wav"
        transcript = client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file,
            language="en"
        )
        text = transcript.text.strip()
        log.info(f"STT: '{text}'")
        return text
    except Exception as e:
        log.error(f"STT error: {e}")
        return ""


# ─── Text-to-Speech ───────────────────────────────────────────────────────────
def text_to_speech(text: str) -> bytes:
    """Convert text to WAV audio bytes for ESP32 playback."""
    try:
        # Option A: OpenAI TTS (high quality, needs API key)
        # from openai import OpenAI
        # client = OpenAI()
        # response = client.audio.speech.create(model="tts-1", voice="nova", input=text)
        # return response.content  # returns MP3, convert to WAV if needed

        # Option B: gTTS (free, needs internet)
        from gtts import gTTS
        import io, subprocess, tempfile, os
        tts = gTTS(text=text, lang='en', slow=False)
        mp3_buf = io.BytesIO()
        tts.write_to_fp(mp3_buf)
        mp3_buf.seek(0)

        # Convert MP3 → 16kHz 16-bit mono WAV using ffmpeg
        with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as f:
            f.write(mp3_buf.read())
            mp3_path = f.name
        wav_path = mp3_path.replace('.mp3', '.wav')
        subprocess.run([
            'ffmpeg', '-y', '-i', mp3_path,
            '-ar', '16000', '-ac', '1', '-acodec', 'pcm_s16le', wav_path
        ], capture_output=True)
        with open(wav_path, 'rb') as f:
            wav_bytes = f.read()
        os.unlink(mp3_path)
        os.unlink(wav_path)
        return wav_bytes

    except Exception as e:
        log.error(f"TTS error: {e}")
        return b""


# ─── Handle ESP32 TCP Connection ──────────────────────────────────────────────
def handle_esp32_client(conn: socket.socket, addr):
    log.info(f"ESP32 connected from {addr}")
    try:
        # Read: [4-byte json_len][json_data]
        json_len_bytes = recv_exact(conn, 4)
        if not json_len_bytes:
            return
        json_len = struct.unpack('<I', json_len_bytes)[0]
        json_data = recv_exact(conn, json_len)
        if not json_data:
            return

        payload = json.loads(json_data.decode('utf-8'))
        log.info(f"Received payload: {payload}")

        # Store latest sensor data
        global latest_sensor_data
        latest_sensor_data = {
            'aqi':        payload.get('aqi', 0),
            'pm25':       payload.get('pm25', 0),
            'pm10':       payload.get('pm10', 0),
            'voc':        payload.get('voc', 0),
            'co2':        payload.get('co2', 0),
            'temp':       payload.get('temp', 0),
            'humidity':   payload.get('humidity', 0),
            'purifier':   payload.get('purifier', False),
            'fan_speed':  payload.get('fan_speed', 1),
            'filter_pct': payload.get('filter_pct', 100),
            'timestamp':  datetime.now().isoformat()
        }

        query_type = payload.get('type', 'text_query')
        user_text = ""

        if query_type == 'voice_audio':
            # Read audio: [4-byte audio_len][wav_data]
            audio_len_bytes = recv_exact(conn, 4)
            if not audio_len_bytes:
                return
            audio_len = struct.unpack('<I', audio_len_bytes)[0]
            log.info(f"Receiving {audio_len} bytes of audio...")
            wav_data = recv_exact(conn, audio_len)
            if not wav_data:
                return
            log.info(f"Audio received: {len(wav_data)} bytes")

            # Transcribe
            user_text = transcribe_audio(wav_data)
            if not user_text:
                user_text = "Describe the current air quality."

        elif query_type == 'text_query':
            user_text = payload.get('query', 'What is the air quality?')

        log.info(f"Query: '{user_text}'")

        # Call Claude
        ai_response = call_claude(user_text, latest_sensor_data)

        # Send response back
        if USE_TTS:
            # Send audio response
            audio_bytes = text_to_speech(ai_response)
            if audio_bytes:
                conn.send(struct.pack('B', 1))                     # type = audio
                conn.send(struct.pack('<I', len(audio_bytes)))     # length
                conn.sendall(audio_bytes)
                log.info(f"Sent {len(audio_bytes)} bytes of audio")
                return

        # Send text response (RESPONSE_AS_TEXT or TTS failed)
        text_bytes = ai_response.encode('utf-8')
        conn.send(struct.pack('B', 0))                  # type = text
        conn.send(struct.pack('<I', len(text_bytes)))   # length
        conn.sendall(text_bytes)
        log.info(f"Sent text response ({len(text_bytes)} bytes)")

    except Exception as e:
        log.error(f"Client handler error: {e}", exc_info=True)
    finally:
        conn.close()
        log.info(f"ESP32 disconnected from {addr}")


def recv_exact(conn: socket.socket, n: int) -> bytes:
    """Reliably receive exactly n bytes."""
    data = b''
    while len(data) < n:
        chunk = conn.recv(n - len(data))
        if not chunk:
            return None
        data += chunk
    return data


# ─── TCP Server (for ESP32) ───────────────────────────────────────────────────
def run_tcp_server():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((TCP_HOST, TCP_PORT))
    server.listen(5)
    log.info(f"TCP server listening on {TCP_HOST}:{TCP_PORT}")

    while True:
        try:
            conn, addr = server.accept()
            thread = threading.Thread(
                target=handle_esp32_client, args=(conn, addr), daemon=True
            )
            thread.start()
        except Exception as e:
            log.error(f"TCP accept error: {e}")


# ─── Flask REST API (for Streamlit + direct queries) ─────────────────────────
app = Flask(__name__)

@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok", "version": "1.0", "time": datetime.now().isoformat()})

@app.route('/sensors', methods=['GET'])
def get_sensors():
    """Latest sensor data — Streamlit polls this."""
    return jsonify(latest_sensor_data)

@app.route('/ask', methods=['POST'])
def ask_ai():
    """Direct text query to Claude with sensor context."""
    data = request.get_json(force=True)
    query = data.get('query', '')
    if not query:
        return jsonify({"error": "No query provided"}), 400

    # Use latest sensor data or override with provided data
    ctx = {**latest_sensor_data, **data.get('sensors', {})}
    response = call_claude(query, ctx)
    return jsonify({
        "query":    query,
        "response": response,
        "sensors":  ctx,
        "time":     datetime.now().isoformat()
    })

@app.route('/history', methods=['GET'])
def get_history():
    """Return conversation history."""
    return jsonify({"history": conversation_history[-20:]})

@app.route('/history/clear', methods=['POST'])
def clear_history():
    global conversation_history
    conversation_history = []
    return jsonify({"ok": True})

@app.route('/control', methods=['POST'])
def control():
    """Send control commands (Streamlit → ESP32 via this server)."""
    data = request.get_json(force=True)
    # In a real setup, this would forward commands to ESP32 via TCP
    # For now, update local state
    if 'purifier' in data:
        latest_sensor_data['purifier'] = bool(data['purifier'])
    if 'fan_speed' in data:
        latest_sensor_data['fan_speed'] = int(data['fan_speed'])
    return jsonify({"ok": True, "state": latest_sensor_data})


# ─── Main ─────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    print("╔══════════════════════════════════════════════════╗")
    print("║   AirGuard Cloud Bridge Server                  ║")
    print(f"║   TCP  → ESP32    : port {TCP_PORT}                   ║")
    print(f"║   HTTP → Streamlit: port {HTTP_PORT}                  ║")
    print("╚══════════════════════════════════════════════════╝")

    if ANTHROPIC_API_KEY == "sk-ant-YOUR_KEY_HERE":
        print("\n⚠️  WARNING: Set your ANTHROPIC_API_KEY!")
        print("   export ANTHROPIC_API_KEY=sk-ant-xxxxx")
        print("   or edit ANTHROPIC_API_KEY in cloud_server.py\n")

    # Start TCP server in background thread
    tcp_thread = threading.Thread(target=run_tcp_server, daemon=True)
    tcp_thread.start()

    print(f"\n✅ TCP server running on port {TCP_PORT}")
    print(f"✅ HTTP API running on port {HTTP_PORT}")
    print(f"\n📱 On your ESP32, set:")
    print(f"   CLOUD_SERVER_IP  = <this computer's IP>")
    print(f"   CLOUD_SERVER_PORT = {TCP_PORT}\n")

    # Start Flask (HTTP) server
    app.run(host='0.0.0.0', port=HTTP_PORT, debug=False, threaded=True)
