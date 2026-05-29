#include <WiFi.h>
#include <WiFiManager.h>
#include <WebServer.h>
#include <ArduinoJson.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <DHT.h>
#include <ESPmDNS.h>

#define SCREEN_WIDTH 128
#define SCREEN_HEIGHT 64
Adafruit_SSD1306 display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, -1);

#define MQ135_PIN 5
#define RELAY_PIN 2
#define DHT_PIN 4
#define DHT_TYPE DHT11

// Set to 1 to enable the GP2Y1010 dust sensor, 0 to disable
#define ENABLE_GP2Y1010 0
#define GP2Y_VO_PIN 6
#define GP2Y_LED_PIN 7

// Set to 1 for active-LOW relay modules, 0 for active-HIGH modules.
#define RELAY_ACTIVE_LOW 1

DHT dht(DHT_PIN, DHT_TYPE);

WebServer server(80);

float thresholdVoltage = 1.20f;
int aqiFanThreshold = 175;
bool autoMode = true;
bool fanOn = false;

const int SAMPLE_COUNT = 12;
float sampleBuffer[SAMPLE_COUNT];
int sampleIndex = 0;
bool samplesReady = false;

unsigned long lastDisplayMs = 0;
unsigned long bootMs = 0;
float latestVoltage = 0.0f;
int latestAdc = 0;
int latestAqi = 0;
float latestPm25 = 0.0f;
float latestTempC = 0.0f;
float latestHumidity = 0.0f;
float pm25Filtered = 0.0f;
float gp2yBaseVoltage = 0.45f; // initial baseline; tune from serial debug output
bool gp2yDebug = true;
int lastGp2yRaw = 0;
float lastGp2yVo = 0.0f;

String getAQICategory(int aqi) {
  if (aqi <= 50)  return "GOOD";
  if (aqi <= 100) return "MODERATE";
  if (aqi <= 150) return "UNHEALTHY*";
  if (aqi <= 200) return "UNHEALTHY";
  if (aqi <= 300) return "VERY UNHLT";
  return "HAZARDOUS";
}

float readSmoothedVoltage() {
  int raw = analogRead(MQ135_PIN);
  float voltage = analogReadMilliVolts(MQ135_PIN) / 1000.0f;

  sampleBuffer[sampleIndex] = voltage;
  sampleIndex = (sampleIndex + 1) % SAMPLE_COUNT;
  if (sampleIndex == 0) {
    samplesReady = true;
  }

  int count = samplesReady ? SAMPLE_COUNT : sampleIndex;
  if (count == 0) {
    return voltage;
  }

  float sum = 0.0f;
  for (int i = 0; i < count; i++) {
    sum += sampleBuffer[i];
  }
  return sum / count;
}

// Set this to the voltage your sensor outputs in normal/clean air
float mq135BaseVoltage = 1.0f;

int voltageToAQI(float voltage) {
  float diff = voltage - mq135BaseVoltage;
  if (diff <= 0.0f) return 0;
  
  // Map a 1.5V increase above baseline to a maximum of 500 AQI
  int aqi = (int)((diff / 1.5f) * 500.0f);
  if (aqi > 500) return 500;
  return aqi;
}

float readDustPM25Raw() {
#if ENABLE_GP2Y1010
  // GP2Y1010 timing sequence
  digitalWrite(GP2Y_LED_PIN, LOW);
  delayMicroseconds(280);
  int raw = analogRead(GP2Y_VO_PIN);
  delayMicroseconds(40);
  digitalWrite(GP2Y_LED_PIN, HIGH);
  delayMicroseconds(9680);

  float vo = (raw / 4095.0f) * 3.3f;
  lastGp2yRaw = raw;
  lastGp2yVo = vo;
  float dust = (vo - gp2yBaseVoltage) / 0.005f; // ug/m3 approximation
  if (dust < 0.0f) dust = 0.0f;
  return dust;
#else
  return 0.0f;
#endif
}

void calibrateGp2yBaseline() {
#if ENABLE_GP2Y1010
  // Calibrate baseline from live pulses at boot so PM2.5 does not stick at 0 due to fixed offset.
  const int n = 30;
  float sumVo = 0.0f;
  for (int i = 0; i < n; i++) {
    digitalWrite(GP2Y_LED_PIN, LOW);
    delayMicroseconds(280);
    int raw = analogRead(GP2Y_VO_PIN);
    delayMicroseconds(40);
    digitalWrite(GP2Y_LED_PIN, HIGH);
    delayMicroseconds(9680);
    sumVo += (raw / 4095.0f) * 3.3f;
  }
  gp2yBaseVoltage = sumVo / n;
  Serial.print("GP2Y baseline calibrated: ");
  Serial.print(gp2yBaseVoltage, 3);
  Serial.println("V");
#else
  gp2yBaseVoltage = 0.0f;
  Serial.println("GP2Y sensor disabled.");
#endif
}

float readDustPM25Stable() {
  // Multi-sample median-ish averaging to reduce spikes.
  const int n = 5;
  float vals[n];
  for (int i = 0; i < n; i++) {
    vals[i] = readDustPM25Raw();
  }
  // Simple trimmed mean: drop min/max.
  float minv = vals[0], maxv = vals[0], sum = 0.0f;
  for (int i = 0; i < n; i++) {
    if (vals[i] < minv) minv = vals[i];
    if (vals[i] > maxv) maxv = vals[i];
    sum += vals[i];
  }
  float mean = (sum - minv - maxv) / (n - 2);

  // Exponential smoothing to prevent sudden drops to zero.
  const float alpha = 0.18f;
  pm25Filtered = (pm25Filtered * (1.0f - alpha)) + (mean * alpha);

  // Keep tiny values visible; avoid hard-clamping to zero.
  if (pm25Filtered < 0.0f) pm25Filtered = 0.0f;
  return pm25Filtered;
}

void setFan(bool on) {
  fanOn = on;
  if (RELAY_ACTIVE_LOW) {
    digitalWrite(RELAY_PIN, fanOn ? LOW : HIGH);
  } else {
    digitalWrite(RELAY_PIN, fanOn ? HIGH : LOW);
  }
}

void updateControl(float voltage) {
  if (!autoMode) return;

  // AQI-based auto control:
  // fan OFF below 175 AQI, ON at/above 175 AQI (with small hysteresis).
  int high = aqiFanThreshold;
  int low = aqiFanThreshold - 5;

  if (!fanOn && latestAqi >= high) {
    setFan(true);
  } else if (fanOn && latestAqi <= low) {
    setFan(false);
  }
}

void handleStatus() {
  JsonDocument doc;
  doc["adc"] = latestAdc;
  doc["voltage"] = latestVoltage;
  doc["aqi"] = latestAqi;
  doc["pm25"] = latestPm25;
  doc["temperature_c"] = latestTempC;
  doc["humidity"] = latestHumidity;
  doc["fan_on"] = fanOn;
  doc["mode"] = autoMode ? "auto" : "manual";
  doc["threshold_voltage"] = thresholdVoltage;
  doc["uptime_sec"] = (millis() - bootMs) / 1000;

  String body;
  serializeJson(doc, body);
  server.sendHeader("Access-Control-Allow-Origin", "*");
  server.send(200, "application/json", body);
}

void handleControl() {
  if (server.method() != HTTP_POST) {
    server.send(405, "application/json", "{\"error\":\"POST required\"}");
    return;
  }

  JsonDocument doc;
  DeserializationError err = deserializeJson(doc, server.arg("plain"));
  if (err) {
    server.send(400, "application/json", "{\"error\":\"Invalid JSON\"}");
    return;
  }

  if (doc["mode"].is<const char*>()) {
    String mode = doc["mode"].as<String>();
    mode.toLowerCase();
    autoMode = (mode == "auto");
  }

  if (doc["threshold_voltage"].is<float>() || doc["threshold_voltage"].is<int>()) {
    float t = doc["threshold_voltage"].as<float>();
    if (t >= 0.2f && t <= 3.0f) {
      thresholdVoltage = t;
    }
  }

  if ((doc["fan_on"].is<bool>() || doc["fan_on"].is<int>()) && !autoMode) {
    bool requested = doc["fan_on"].as<bool>();
    setFan(requested);
  }

  handleStatus();
}

void drawOLED(float voltage) {
  int aqi = voltageToAQI(voltage);

  display.clearDisplay();

  // ── Title Bar ──
  display.fillRect(0, 0, SCREEN_WIDTH, 12, SSD1306_WHITE);
  display.setTextColor(SSD1306_BLACK);
  display.setTextSize(1);
  display.setCursor(22, 2);
  display.print("AIR PURIFIER v1.0");

  // ── AQI Value (large) ──
  display.setTextColor(SSD1306_WHITE);
  display.setTextSize(2);
  display.setCursor(0, 16);
  display.print("AQI:");
  display.print(aqi);

  // ── AQI Category & PM2.5 ──
  display.setTextSize(1);
  display.setCursor(0, 36);
  display.print(getAQICategory(aqi));
  display.print(" PM:");
  display.print((int)latestPm25);

  // ── Divider ──
  display.drawLine(0, 46, SCREEN_WIDTH, 46, SSD1306_WHITE);

  // ── Temperature & Humidity ──
  display.setTextSize(1);
  display.setCursor(0, 50);
  display.print("T:");
  if (isnan(latestTempC)) {
    display.print("--");
  } else {
    display.print(latestTempC, 1);
    display.print("C");
  }

  display.setCursor(55, 50);
  display.print("H:");
  if (isnan(latestHumidity)) {
    display.print("--");
  } else {
    display.print(latestHumidity, 1);
    display.print("%");
  }

  // ── Fan Status (right side) ──
  display.setTextSize(1);
  if (fanOn) {
    display.fillRoundRect(88, 14, 40, 28, 4, SSD1306_WHITE);
    display.setTextColor(SSD1306_BLACK);
    display.setCursor(93, 18);
    display.print(" FAN");
    display.setCursor(95, 28);
    display.print(" ON");
    display.setTextColor(SSD1306_WHITE);
  } else {
    display.drawRoundRect(88, 14, 40, 28, 4, SSD1306_WHITE);
    display.setCursor(93, 18);
    display.print(" FAN");
    display.setCursor(94, 28);
    display.print(" OFF");
  }

  display.display();
}

void connectWiFi() {
  WiFiManager wm;
  // Set a 3-minute timeout for the captive portal
  wm.setConfigPortalTimeout(180);

  Serial.println("Starting WiFiManager...");
  // This will auto connect or start an AP named "AirPurifierSetup"
  bool res = wm.autoConnect("AirPurifierSetup");

  if (!res) {
    Serial.println("Failed to connect or hit timeout. Running local only.");
  } else {
    Serial.print("Connected! IP: ");
    Serial.println(WiFi.localIP());
  }
}

void setup() {
  Serial.begin(115200);
  bootMs = millis();
  Serial.print("Relay polarity: ");
  Serial.println(RELAY_ACTIVE_LOW ? "ACTIVE_LOW" : "ACTIVE_HIGH");

  pinMode(RELAY_PIN, OUTPUT);
#if ENABLE_GP2Y1010
  pinMode(GP2Y_LED_PIN, OUTPUT);
  digitalWrite(GP2Y_LED_PIN, HIGH);
#endif
  dht.begin();
  setFan(false);

  Wire.begin(8, 9); // ESP32-S3 default SDA=8, SCL=9
  if (!display.begin(SSD1306_SWITCHCAPVCC, 0x3C)) {
    Serial.println("SSD1306 allocation failed");
    for (;;) {}
  }

  analogReadResolution(12);
  // analogSetPinAttenuation is deprecated in ESP32 Core 3.x, and 11dB is the default.
  calibrateGp2yBaseline();
  latestVoltage = readSmoothedVoltage();
  latestAdc = (int)((latestVoltage / 3.3f) * 4095.0f);
  latestAqi = voltageToAQI(latestVoltage);
  latestPm25 = readDustPM25Stable();
  latestTempC = dht.readTemperature();
  latestHumidity = dht.readHumidity();
  if (isnan(latestTempC)) latestTempC = 0.0f;
  if (isnan(latestHumidity)) latestHumidity = 0.0f;
  connectWiFi();

  server.on("/api/status", HTTP_GET, handleStatus);
  server.on("/api/control", HTTP_POST, handleControl);
  server.begin();

  // Start mDNS so Xiaozhi can find us as "airpurifier.local"
  if (WiFi.status() == WL_CONNECTED) {
    if (MDNS.begin("airpurifier")) {
      MDNS.addService("http", "tcp", 80);
      Serial.println("mDNS started: airpurifier.local");
    } else {
      Serial.println("mDNS failed to start");
    }
  }

  display.clearDisplay();
  display.setTextSize(1);
  display.setCursor(0, 0);
  display.println("Air Purifier Ready");
  if (WiFi.status() == WL_CONNECTED) {
    display.println(WiFi.localIP());
  } else {
    display.println("No WiFi");
  }
  display.display();
  delay(1200);
}

void loop() {
  server.handleClient();

  float voltage = readSmoothedVoltage();
  latestVoltage = voltage;
  latestAdc = (int)((voltage / 3.3f) * 4095.0f);
  latestAqi = voltageToAQI(voltage);
  latestPm25 = readDustPM25Stable();
  float t = dht.readTemperature();
  float h = dht.readHumidity();
  if (!isnan(t)) latestTempC = t;
  if (!isnan(h)) latestHumidity = h;
  updateControl(voltage);

  Serial.print("Voltage: ");
  Serial.print(voltage, 3);
  Serial.print(" V | Fan: ");
  Serial.print(fanOn ? "ON" : "OFF");
  Serial.print(" | PM2.5: ");
  Serial.print(latestPm25, 1);
  Serial.print(" | T: ");
  Serial.print(latestTempC, 1);
  Serial.print("C | H: ");
  Serial.print(latestHumidity, 0);
  Serial.print("%");
  if (gp2yDebug) {
    Serial.print(" | GP2Y raw: ");
    Serial.print(lastGp2yRaw);
    Serial.print(" | VO: ");
    Serial.print(lastGp2yVo, 3);
    Serial.print("V | base: ");
    Serial.print(gp2yBaseVoltage, 3);
    Serial.print("V");
  }
  Serial.println();

  if (millis() - lastDisplayMs > 1000) {
    drawOLED(voltage);
    lastDisplayMs = millis();
  }

  delay(250);
}
