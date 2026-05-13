AirGuard Pro - ESP32 Smart Air Purifier Dashboard

AirGuard Pro is a smart air quality monitoring and purifier control platform using an ESP32 + Flask web dashboard.

FEATURES

- Live ESP32 sensor monitoring (AQI, ADC, Voltage, Fan status)
- OLED + Web synchronization
- Real-time dashboard (SSE stream + polling fallback)
- Auto/manual purifier control
- Predictive AQI forecast (next 2 hours)
- Filter Health Intelligence (runtime/load based)
- Daily AQI reports
- Role-based login (admin/viewer)
- Chat assistant for recommendations
- Persistent logging to SQLite + CSV

PROJECT STRUCTURE

ai_based air purifier/
|- app.py
|- requirements.txt
|- platformio.ini
|- src/
|  |- main.cpp
|- templates/
|  |- base.html
|  |- login.html
|  |- dashboard.html
|  |- reports.html
|  |- controls.html
|  \- chatbot.html
|- static/
|  |- styles.css
|  |- dashboard.js
|  |- reports.js
|  |- controls.js
|  \- chatbot.js
|- data/
|  \- airguard.db
\- logs/
   \- air_readings.csv

HARDWARE

- ESP32 board
- MQ135 gas sensor (analog)
- Relay module (fan control)
- SSD1306 OLED (128x64 I2C)
- GP2Y101 Dust sensor


FIRMWARE SETUP (VS CODE + PLATFORMIO)

1. Install VS Code extension: PlatformIO IDE
2. Open this project folder
3. Update Wi-Fi in src/main.cpp:
   const char* WIFI_SSID = "YOUR_WIFI";
   const char* WIFI_PASSWORD = "YOUR_PASSWORD";
4. Build and Upload in PlatformIO
5. Open Serial Monitor (115200) and note ESP32 IP

WEB APP SETUP

1. Install dependencies:
   pip install -r requirements.txt

2. Run with ESP32 IP:
   PowerShell:
   $env:ESP32_BASE_URL="http://192.168.x.x"
   python app.py

3. Open:
   http://127.0.0.1:5000/login

DEFAULT LOGIN

- Admin: admin / admin123
- Viewer: viewer / viewer123

Recommended Env Overrides:
- AIRGUARD_ADMIN_USER
- AIRGUARD_ADMIN_PASS
- AIRGUARD_VIEWER_USER
- AIRGUARD_VIEWER_PASS
- FLASK_SECRET_KEY

API ENDPOINTS

Core:
- GET /api/live
- GET /api/stream
- GET /api/history?points=60
- GET /api/settings
- POST /api/settings (admin)
- POST /api/fan (admin)

Intelligence:
- GET /api/reports/summary
- GET /api/reports/daily?days=7
- GET /api/predict?horizon=12
- GET /api/filter-health
- POST /api/filter/reset (admin)

Chat:
- POST /api/chat
  body: { "message": "current status" }

DATA STORAGE

- SQLite DB: data/airguard.db
- CSV log: logs/air_readings.csv

SOURCE STATUS MEANING

- esp32 -> live board data
- esp32-stale -> last known board sample
- esp32-offline -> board unreachable / URL not configured

TROUBLESHOOTING

Dashboard not syncing with OLED:
- Re-upload firmware
- Set correct ESP32_BASE_URL
- Restart Flask
- Hard refresh browser (Ctrl+F5)
- Test board endpoint: http://<ESP32_IP>/api/status

ESP32 Wi-Fi fails:
- Use 2.4 GHz Wi-Fi/hotspot
- Recheck SSID/password (case sensitive)
- Keep board near router/phone hotspot

SECURITY NOTES

- Change default credentials
- Set FLASK_SECRET_KEY
- For HTTPS deployments set COOKIE_SECURE=1

LICENSE

Add your license file (LICENSE) - MIT recommended.
