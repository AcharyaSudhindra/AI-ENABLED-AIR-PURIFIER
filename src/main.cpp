#include <WiFi.h>
#include <WebServer.h>
#include <ArduinoJson.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>

#define SCREEN_WIDTH 128
#define SCREEN_HEIGHT 64
Adafruit_SSD1306 display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, -1);

#define MQ135_PIN 34
#define RELAY_PIN 25
#define GP2Y_VO_PIN 35
#define GP2Y_LED_PIN 26

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

float readDustPM25() {
  // GP2Y1010 timing sequence
  digitalWrite(GP2Y_LED_PIN, LOW);
  delayMicroseconds(280);
  int raw = analogRead(GP2Y_VO_PIN);
  delayMicroseconds(40);
  digitalWrite(GP2Y_LED_PIN, HIGH);
  delayMicroseconds(9680);

  float vo = (raw / 4095.0f) * 3.3f;
  float dust = (vo - 0.6f) / 0.005f; // ug/m3 approximation
  if (dust < 0.0f) dust = 0.0f;
  return dust;
}

void setFan(bool on) {
  fanOn = on;
  digitalWrite(RELAY_PIN, fanOn ? HIGH : LOW);
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
  DynamicJsonDocument doc(256);
  doc["adc"] = latestAdc;
  doc["voltage"] = latestVoltage;
  doc["aqi"] = latestAqi;
  doc["pm25"] = latestPm25;
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

  DynamicJsonDocument doc(256);
  DeserializationError err = deserializeJson(doc, server.arg("plain"));
  if (err) {
    server.send(400, "application/json", "{\"error\":\"Invalid JSON\"}");
    return;
  }

  if (doc.containsKey("mode")) {
    String mode = doc["mode"].as<String>();
    mode.toLowerCase();
    autoMode = (mode == "auto");
  }

  if (doc.containsKey("threshold_voltage")) {
    float t = doc["threshold_voltage"].as<float>();
    if (t >= 0.2f && t <= 3.0f) {
      thresholdVoltage = t;
    }
  }

  if (doc.containsKey("fan_on") && !autoMode) {
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
  display.print("PM2.5:");
  display.print(latestPm25, 1);
  display.println("ug");

  display.setCursor(0, 50);
  display.print("F:");
  display.print(fanOn ? "ON " : "OFF");
  display.print(" A:");
  display.print(aqi);
  display.print(" ");
  display.print(autoMode ? "A" : "M");

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

  pinMode(RELAY_PIN, OUTPUT);
  pinMode(GP2Y_LED_PIN, OUTPUT);
  digitalWrite(GP2Y_LED_PIN, HIGH);
  setFan(false);

  if (!display.begin(SSD1306_SWITCHCAPVCC, 0x3C)) {
    Serial.println("SSD1306 allocation failed");
    for (;;) {}
  }

  analogReadResolution(12);
  latestVoltage = readSmoothedVoltage();
  latestAdc = (int)((latestVoltage / 3.3f) * 4095.0f);
  latestAqi = voltageToAQI(latestVoltage);
  latestPm25 = readDustPM25();
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
  latestPm25 = readDustPM25();
  updateControl(voltage);

  Serial.print("Voltage: ");
  Serial.print(voltage, 3);
  Serial.print(" V | Fan: ");
  Serial.print(fanOn ? "ON" : "OFF");
  Serial.print(" | PM2.5: ");
  Serial.println(latestPm25, 1);

  if (millis() - lastDisplayMs > 1000) {
    drawOLED(voltage);
    lastDisplayMs = millis();
  }

  delay(250);
}
