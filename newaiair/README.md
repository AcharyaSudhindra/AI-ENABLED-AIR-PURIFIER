# AirGuard AI Assistant — Complete Build Guide

## System Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         YOUR HOME NETWORK                           │
│                                                                     │
│  ┌──────────────────────┐         ┌────────────────────────────┐   │
│  │   ESP32-S3-N16R8     │  TCP    │   PC / Laptop              │   │
│  │                      │◄───────►│   cloud_server.py          │   │
│  │  • MQ135 (VOC/CO₂)  │  :8765  │                            │   │
│  │  • GP2Y1010 (Dust)   │         │   ┌─────────────────────┐  │   │
│  │  • OLED Display      │  HTTP   │   │  Anthropic Claude   │  │   │
│  │  • Relay (Fan)       │◄───────►│   │  API (cloud)        │  │   │
│  │  • [INMP441 mic]*    │  :80    │   └─────────────────────┘  │   │
│  │  • [MAX98357 spkr]*  │         │                            │   │
│  └──────────────────────┘         │   Streamlit Dashboard      │   │
│         * = add later             │   + AI Chat Tab            │   │
│                                   └────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Files in this project

| File | Purpose |
|------|---------|
| `esp32_firmware/airguard_ai.ino` | ESP32-S3 Arduino firmware |
| `cloud_server/cloud_server.py`   | Python bridge server (TCP + HTTP) |
| `cloud_server/ai_assistant_tab.py` | Streamlit AI chat tab |

---

## Phase 1 — NOW (No mic/speaker needed)

### What works today:
- ✅ Sensors (MQ135 + GP2Y1010) → readings on OLED
- ✅ HTTP server on ESP32 → Streamlit dashboard live data
- ✅ Push BOOT button → sends preset queries to Claude AI
- ✅ Push GPIO4 button → cycles through 6 air quality questions
- ✅ AI response scrolls on OLED display
- ✅ Auto-alert when AQI > 150 (sends to Claude every 5 min)
- ✅ Streamlit AI chat tab → type questions, get Claude responses

### Setup steps:

**1. Arduino IDE setup:**
```
Tools → Board → ESP32S3 Dev Module
Tools → PSRAM → OPI PSRAM         ← CRITICAL for N16R8
Tools → Flash Size → 16MB
Tools → Partition Scheme → 16M Flash (2MB APP/12.5MB FATFS)
Tools → Upload Speed → 921600
```

**2. Install Arduino libraries:**
- ArduinoJson (Benoit Blanchon) — v6.x
- Adafruit SSD1306
- Adafruit GFX Library

**3. Edit firmware config:**
```cpp
// In airguard_ai.ino, update:
#define WIFI_SSID        "your_wifi_name"
#define WIFI_PASSWORD    "your_wifi_password"
#define CLOUD_SERVER_IP  "192.168.1.XXX"  // your PC's IP
```

**4. Start cloud server:**
```bash
pip install anthropic flask requests
export ANTHROPIC_API_KEY=sk-ant-your-key-here
python cloud_server/cloud_server.py
```

**5. Upload firmware to ESP32-S3:**
- Hold BOOT, press RESET, release BOOT (enter flash mode)
- Upload from Arduino IDE
- Open Serial Monitor at 115200 baud

---

## Wiring — Current Setup (No mic/speaker)

```
ESP32-S3-N16R8          MQ135 Gas Sensor
──────────────          ────────────────
GPIO 1  ──────────────► AOUT
3.3V    ──────────────► VCC
GND     ──────────────► GND
(also connects to 5V heater — use 5V for best accuracy)

ESP32-S3-N16R8          GP2Y1010AU0F Dust Sensor
──────────────          ─────────────────────────
GPIO 2  ──────────────► V-LED output (VO)
GPIO 3  ──────────────► LED control (connect via 150Ω resistor)
3.3V    ──────────────► VCC
GND     ──────────────► GND
                        Add 220µF cap between VCC and GND!

ESP32-S3-N16R8          SSD1306 OLED (I2C)
──────────────          ──────────────────
GPIO 8  ──────────────► SDA
GPIO 9  ──────────────► SCL
3.3V    ──────────────► VCC
GND     ──────────────► GND

ESP32-S3-N16R8          Relay Module
──────────────          ────────────
GPIO 10 ──────────────► IN1
5V      ──────────────► VCC
GND     ──────────────► GND
                        Fan connects to relay NO/COM

BUTTONS
──────────────────────────────────────────
GPIO 0  = BOOT button (already on board!) → Push-to-Talk / Send Query
GPIO 4  → Tactile button → GND            → Cycle preset questions
```

---

## Phase 2 — Add Microphone (INMP441) — ~₹200

### Buy:
- INMP441 I2S MEMS microphone module
- Price: ₹150–250 on Amazon India / Robu.in

### Wiring:
```
ESP32-S3-N16R8          INMP441 Microphone
──────────────          ─────────────────
GPIO 42 ──────────────► WS  (Word Select / LRCLK)
GPIO 41 ──────────────► SCK (Bit Clock)
GPIO 40 ──────────────► SD  (Serial Data)
3.3V    ──────────────► VDD
GND     ──────────────► GND
GND     ──────────────► L/R (left channel select)
```

### Enable in firmware:
In `airguard_ai.ino`, uncomment:
```cpp
if (!setupMicrophone()) Serial.println("WARN: Mic init failed");
else                    Serial.println("Microphone ready");
```
And in loop(), replace text query with:
```cpp
recordAudio();  // records from INMP441 into PSRAM
sendToCloudAndGetResponse(false);  // sends WAV to cloud
```

### Enable STT in cloud_server.py:
```bash
pip install openai
export OPENAI_API_KEY=sk-your-openai-key  # for Whisper STT
```

---

## Phase 3 — Add Speaker (MAX98357A) — ~₹150

### Buy:
- MAX98357A I2S amplifier module
- Small 8Ω 0.5W speaker
- Price: ₹100–200 for both

### Wiring:
```
ESP32-S3-N16R8          MAX98357A Amplifier
──────────────          ──────────────────
GPIO 39 ──────────────► BCLK
GPIO 38 ──────────────► LRC  (Word Clock)
GPIO 37 ──────────────► DIN  (Data In)
5V      ──────────────► VIN
GND     ──────────────► GND
GND     ──────────────► SD   (tie to GND = always on)
                        GAIN = float (9dB gain) or GND (6dB)
Speaker connects to + and - terminals
```

### Enable in firmware:
In `airguard_ai.ino`, uncomment:
```cpp
if (!setupSpeaker()) Serial.println("WARN: Speaker init failed");
else                 Serial.println("Speaker ready");
```

### Enable TTS in cloud_server.py:
```python
USE_TTS = True  # at top of cloud_server.py

# Option A: OpenAI TTS (best quality)
pip install openai
# Uncomment OpenAI TTS block in text_to_speech()

# Option B: gTTS (free)
pip install gtts
# Also needs ffmpeg installed:
# Windows: https://ffmpeg.org/download.html
# Linux: sudo apt install ffmpeg
```

---

## Cloud Server API Reference

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Server status check |
| `/sensors` | GET | Latest ESP32 sensor data |
| `/ask` | POST `{"query":"..."}` | Ask Claude AI |
| `/history` | GET | Conversation history |
| `/history/clear` | POST | Clear conversation |
| `/control` | POST `{"purifier":true, "fan_speed":2}` | Control purifier |

---

## Total Cost Estimate

| Component | Price (India) | Status |
|-----------|--------------|--------|
| ESP32-S3-N16R8 | ~₹800 | ✅ Have |
| MQ135 | ~₹150 | ✅ Have |
| GP2Y1010 | ~₹300 | ✅ Have |
| SSD1306 OLED | ~₹200 | ✅ Have |
| Relay module | ~₹80 | ✅ Have |
| Fan + HEPA filter | ~₹500 | ✅ Have |
| **INMP441 mic** | ~₹200 | Buy next |
| **MAX98357A + speaker** | ~₹200 | Buy after |
| **Total new cost** | **~₹400** | |

---

## Claude AI System Prompt Customization

Edit `SYSTEM_PROMPT` in `cloud_server.py` to:
- Change personality / language (Hindi support: add "respond in Hindi")
- Add custom AQI thresholds for your city
- Add family health context ("user has asthma")
- Add more sensor types as you expand

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| PSRAM not found | Arduino IDE → Tools → PSRAM → OPI PSRAM |
| Can't connect to server | Check PC IP, firewall, both on same WiFi |
| OLED blank | Check SDA/SCL pins, I2C address (try 0x3C or 0x3D) |
| Sensors reading 0 | ADC pins — ensure not using GPIO 0 for analog |
| Serial upload fails | Hold BOOT + press RESET before uploading |
