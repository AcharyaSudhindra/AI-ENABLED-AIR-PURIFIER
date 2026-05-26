# ESP32-S3 Firmware Guide — AirGuard

## Sensor Wiring

| Sensor         | ESP32-S3 Pin |
|----------------|--------------|
| MQ135 AOUT     | GPIO 5 (ADC) |
| GP2Y1010 VO    | GPIO 6 (ADC) |
| GP2Y1010 LED   | GPIO 26      |
| OLED SDA       | GPIO 8       |
| OLED SCL       | GPIO 9       |
| Relay          | GPIO 25      |
| DHT Sensor     | GPIO 4       |

## Required Libraries (Arduino IDE)
- `WiFi.h` (built-in)
- `WebServer.h` (built-in)
- `Adafruit_SSD1306`
- `ArduinoJson`
- `MQ135` (or custom ADC read)

## Firmware Sketch (ESP32-S3 Arduino)

```cpp
#include <WiFi.h>
#include <WebServer.h>
#include <ArduinoJson.h>
#include <Wire.h>
#include <Adafruit_SSD1306.h>

const char* ssid     = "YOUR_SSID";
const char* password = "YOUR_PASSWORD";

// Pin definitions
#define MQ135_PIN     5
#define GP2Y_VO_PIN   6
#define GP2Y_LED_PIN  26
#define RELAY_PIN     25
#define DHT_PIN       4

WebServer server(80);
Adafruit_SSD1306 display(128, 64, &Wire);

float readDustPM25() {
  digitalWrite(GP2Y_LED_PIN, LOW);      // LED ON
  delayMicroseconds(280);
  float vo = analogRead(GP2Y_VO_PIN) * (3.3 / 4095.0);
  delayMicroseconds(40);
  digitalWrite(GP2Y_LED_PIN, HIGH);     // LED OFF
  float dust = (vo - 0.6) / 0.005;     // µg/m³
  return max(0.0f, dust);
}

float readVOC() {
  int raw = analogRead(MQ135_PIN);
  return raw * (5.0 / 4095.0);         // Simplified — calibrate for accuracy
}

void handleSensors() {
  float dust = readDustPM25();
  float voc  = readVOC();
  int aqi    = (int)(dust * 2.1);      // Simplified AQI estimate

  DynamicJsonDocument doc(256);
  doc["aqi"]        = aqi;
  doc["dust_pm25"]  = dust;
  doc["dust_pm10"]  = dust * 1.7;
  doc["voc_ppm"]    = voc;
  doc["co2_ppm"]    = 400 + aqi * 2;
  doc["temperature"]= 26.0;            // Add DHT11/22 for real values
  doc["humidity"]   = 55.0;

  String body;
  serializeJson(doc, body);
  server.sendHeader("Access-Control-Allow-Origin", "*");
  server.send(200, "application/json", body);
}

void handleRelay() {
  if (server.hasArg("speed")) {
    int speed = server.arg("speed").toInt();
    // speed: 0=off, 1=low, 2=med, 3=high
    // Implement PWM or multi-relay logic here
    analogWrite(RELAY_PIN, speed * 85);
  }
  server.send(200, "text/plain", "OK");
}

void setup() {
  Serial.begin(115200);
  pinMode(GP2Y_LED_PIN, OUTPUT);
  pinMode(RELAY_PIN, OUTPUT);

  WiFi.begin(ssid, password);
  while (WiFi.status() != WL_CONNECTED) delay(500);
  Serial.println("IP: " + WiFi.localIP().toString());

  display.begin(SSD1306_SWITCHCAPVCC, 0x3C);
  display.clearDisplay();
  display.setTextColor(WHITE);
  display.setCursor(0, 0);
  display.println("AirGuard Online");
  display.println(WiFi.localIP().toString());
  display.display();

  server.on("/sensors", handleSensors);
  server.on("/relay",   handleRelay);
  server.begin();
}

void loop() {
  server.handleClient();
  // Update OLED every 2s
  static unsigned long last = 0;
  if (millis() - last > 2000) {
    float dust = readDustPM25();
    display.clearDisplay();
    display.setCursor(0,0);
    display.printf("PM2.5: %.1f ug/m3\n", dust);
    display.printf("AQI:   %d\n", (int)(dust * 2.1));
    display.display();
    last = millis();
  }
}
```

## Connect Streamlit to ESP32
In `app.py`, update `get_sensor_data()`:
```python
def get_sensor_data():
    try:
        resp = requests.get('http://192.168.1.100/sensors', timeout=2)
        return resp.json()
    except:
        return {}  # fallback to last known values
```

## Control Fan from Dashboard
```python
requests.get(f'http://192.168.1.100/relay?speed={fan_speed}')
```
