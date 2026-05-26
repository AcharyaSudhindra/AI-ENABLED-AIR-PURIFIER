#include <WiFi.h>
#include <WebServer.h>
#include <ArduinoJson.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <DHT.h>

#define SCREEN_WIDTH 128
#define SCREEN_HEIGHT 64
Adafruit_SSD1306 display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, -1);

#define MQ135_PIN 5
#define RELAY_PIN 25
#define GP2Y_VO_PIN 6
#define GP2Y_LED_PIN 26
#define DHT_PIN 4
#define DHT_TYPE DHT11
// Set to 1 for active-LOW relay modules, 0 for active-HIGH modules.
#define RELAY_ACTIVE_LOW 1

DHT dht(DHT_PIN, DHT_TYPE);

const char* WIFI_SSID = "Sudhindra";
const char* WIFI_PASSWORD = "sudhindra2024@";

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

float readSmoothedVoltage() {
  int raw = analogRead(MQ135_PIN);
  float voltage = (raw / 4095.0f) * 3.3f;

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

int voltageToAQI(float voltage) {
  int aqi = (int)((voltage / 3.3f) * 500.0f);
  if (aqi < 0) return 0;
  if (aqi > 500) return 500;
  return aqi;
}

float readDustPM25Raw() {
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
}

void calibrateGp2yBaseline() {
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
  int adc = (int)((voltage / 3.3f) * 4095.0f);
  int aqi = voltageToAQI(voltage);

  display.clearDisplay();
  display.setTextSize(1);
  display.setTextColor(SSD1306_WHITE);

  display.setCursor(0, 0);
  display.println("Air Purifier ESP32");

  display.setCursor(0, 14);
  display.print("ADC: ");
  display.println(adc);

  display.setCursor(0, 26);
  display.print("Volt: ");
  display.print(voltage, 2);
  display.println("V");

  display.setCursor(0, 38);
  display.print("PM:");
  display.print(latestPm25, 1);
  display.println("ug");

  display.setCursor(0, 50);
  bool showClimate = ((millis() / 2000UL) % 2UL) == 0UL;
  if (showClimate) {
    display.print("T:");
    display.print(latestTempC, 1);
    display.print("C H:");
    display.print(latestHumidity, 0);
    display.print("%");
  } else {
    display.print("F:");
    display.print(fanOn ? "ON " : "OFF");
    display.print(" AqI:");
    display.print(aqi);
    display.print(" ");
    display.print(autoMode ? "A" : "M");
  }

  display.display();
}

void connectWiFi() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  Serial.print("Connecting WiFi");
  int retries = 0;
  while (WiFi.status() != WL_CONNECTED && retries < 30) {
    delay(500);
    Serial.print(".");
    retries++;
  }
  Serial.println();

  if (WiFi.status() == WL_CONNECTED) {
    Serial.print("Connected. IP: ");
    Serial.println(WiFi.localIP());
  } else {
    Serial.println("WiFi not connected. Running local only.");
  }
}

void setup() {
  Serial.begin(115200);
  bootMs = millis();
  Serial.print("Relay polarity: ");
  Serial.println(RELAY_ACTIVE_LOW ? "ACTIVE_LOW" : "ACTIVE_HIGH");

  pinMode(RELAY_PIN, OUTPUT);
  pinMode(GP2Y_LED_PIN, OUTPUT);
  digitalWrite(GP2Y_LED_PIN, HIGH);
  dht.begin();
  setFan(false);

  if (!display.begin(SSD1306_SWITCHCAPVCC, 0x3C)) {
    Serial.println("SSD1306 allocation failed");
    for (;;) {}
  }

  analogReadResolution(12);
  analogSetPinAttenuation(MQ135_PIN, ADC_11db);
  analogSetPinAttenuation(GP2Y_VO_PIN, ADC_11db);
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
