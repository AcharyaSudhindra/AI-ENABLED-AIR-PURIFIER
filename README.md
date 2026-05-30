# 🌬️ AirGuard Pro - Smart Air Purifier & Monitor

[![Build Status](https://img.shields.io/badge/build-passing-brightgreen.svg)](https://github.com/AcharyaSudhindra/ai_based-air-purifier)
[![PlatformIO](https://img.shields.io/badge/PlatformIO-Compatible-orange)](https://platformio.org/)
[![Flask](https://img.shields.io/badge/Flask-Web%20App-lightgrey)](https://flask.palletsprojects.com/)

AirGuard Pro is an advanced, AI-enabled smart air quality monitoring and purifier control platform powered by an **ESP32** microcontroller and a **Flask** web dashboard. 

It provides real-time tracking, intelligent filtering recommendations, predictive AQI forecasting, and now features an integrated **XiaoZhi AI Voice Assistant** module for voice-activated interactions.

---

## ✨ Features

- **Live ESP32 Sensor Monitoring**: Tracks Air Quality Index (AQI), raw ADC values, voltage, and fan status in real-time.
- **Hardware Integration**: OLED display on the device stays perfectly synchronized with the web dashboard.
- **Real-Time Web Dashboard**: Built with SSE streams for live updates and fallback polling.
- **Automated Intelligence**: Auto/manual modes for the purifier with Filter Health Intelligence based on runtime and load.
- **Predictive Analytics**: AQI forecasting for the next 2 hours.
- **AI Voice Assistant**: An integrated conversational AI module (`ai_assistant/`) that allows users to interact with the system and control smart appliances using large language models.
- **Secure Access**: Role-based login system separating `admin` and `viewer` privileges.
- **Data Persistence**: Persistent logging to SQLite and CSV formats.

## 📁 Project Structure

```text
ai_based_air_purifier/
├── ai_assistant/        # Integrated XiaoZhi AI Voice Chatbot Module
├── src/                 # ESP32 C++ Firmware Source Code
├── templates/           # Flask HTML Templates
├── static/              # CSS, JS, and Frontend Assets
├── data/                # SQLite Database (airguard.db)
├── logs/                # CSV Data Logs
├── app.py               # Main Flask Backend Server
├── platformio.ini       # PlatformIO configuration
└── requirements.txt     # Python Dependencies
```

## 🛠️ Hardware Requirements

- **ESP32 Development Board**
- **MQ135 Gas Sensor (Analog)** - For detecting harmful gases and measuring overall AQI.
- **Relay Module** - For controlling the air purifier fan.
- **SSD1306 OLED Display (128x64 I2C)** - For on-device status readout.
- **GP2Y101 Dust Sensor** - For particulate matter measurement.
- *(Optional)* AI Voice Module Hardware (Refer to `ai_assistant/README.md`)

## 🚀 Getting Started

### 1. Firmware Setup (VS Code + PlatformIO)

1. Install the **PlatformIO IDE** extension in VS Code.
2. Open this project folder.
3. Update the Wi-Fi credentials in `src/main.cpp`:
   ```cpp
   const char* WIFI_SSID = "YOUR_WIFI";
   const char* WIFI_PASSWORD = "YOUR_PASSWORD";
   ```
4. Click **Build** and **Upload** in PlatformIO to flash the firmware.
5. Open the Serial Monitor (Baud rate: 115200) and note the ESP32 IP address.

### 2. Web Dashboard Setup

1. Install Python dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Set the Environment Variable for the ESP32 IP and run the app (PowerShell example):
   ```powershell
   $env:ESP32_BASE_URL="http://192.168.x.x"
   python app.py
   ```
3. Access the dashboard via your browser: `http://127.0.0.1:5000/login`

### 3. Default Login Credentials

| Role | Username | Password |
|------|----------|----------|
| **Admin** | `admin` | `admin123` |
| **Viewer** | `viewer` | `viewer123` |

> **Security Note**: It is highly recommended to override these default credentials using environment variables (`AIRGUARD_ADMIN_USER`, `AIRGUARD_ADMIN_PASS`, etc.) and to set a secure `FLASK_SECRET_KEY` before deployment.

---

## 📡 API Endpoints

### Core Dashboard
- `GET /api/live` - Fetch live sensor data.
- `GET /api/stream` - SSE stream endpoint.
- `GET /api/history?points=60` - Fetch historical readings.
- `GET /api/settings` - Retrieve current system configurations.
- `POST /api/settings` *(Admin)* - Update configurations.
- `POST /api/fan` *(Admin)* - Toggle the fan state manually.

### Intelligence & Reports
- `GET /api/reports/summary` - General air quality summary.
- `GET /api/reports/daily?days=7` - Daily breakdown over the last week.
- `GET /api/predict?horizon=12` - AQI predictions.
- `GET /api/filter-health` - Check current filter lifespan and load.
- `POST /api/filter/reset` *(Admin)* - Reset filter health tracking.

### Chat Assistant
- `POST /api/chat` - Interact with the built-in recommendation system.

---

## 🔧 Troubleshooting

**Dashboard not syncing with OLED?**
- Verify the `ESP32_BASE_URL` is correct.
- Hard refresh the browser (`Ctrl+F5`).
- Ensure the ESP32 is powered and reachable (`http://<ESP32_IP>/api/status`).

**ESP32 Wi-Fi fails to connect?**
- Ensure your network is `2.4GHz` (ESP32 does not support 5GHz).
- Double-check the exact spelling and casing of the SSID and password.

---

## 📄 License
This platform integrates multiple open-source components. For details regarding the AI Chatbot module licensing, see `ai_assistant/LICENSE`.
