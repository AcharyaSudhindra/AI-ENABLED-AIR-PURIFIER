/*
 ╔══════════════════════════════════════════════════════════════════╗
 ║   AirGuard AI Assistant — ESP32-S3-N16R8                        ║
 ║   Board  : ESP32-S3 (16MB Flash, 8MB PSRAM)                     ║
 ║   Mic    : INMP441 I2S MEMS Microphone  (add when ready)        ║
 ║   Speaker: MAX98357A I2S Amplifier      (add when ready)        ║
 ║   Sensors: MQ135 (VOC/CO2) + GP2Y1010 (Dust/PM2.5)             ║
 ║   Display: SSD1306 OLED 128x64 via I2C                          ║
 ║   AI     : Claude API via WiFi → Python Cloud Bridge            ║
 ╚══════════════════════════════════════════════════════════════════╝

 PIN ASSIGNMENTS (ESP32-S3-N16R8):
 ┌─────────────────────────────────────────────────────┐
 │  SENSORS                                            │
 │   MQ135 AOUT      → GPIO 1  (ADC1_CH0)             │
 │   GP2Y1010 VO     → GPIO 2  (ADC1_CH1)             │
 │   GP2Y1010 LED    → GPIO 3  (PWM)                  │
 │                                                     │
 │  OLED (I2C)                                         │
 │   SDA             → GPIO 8                         │
 │   SCL             → GPIO 9                         │
 │                                                     │
 │  RELAY                                              │
 │   Relay IN        → GPIO 10                        │
 │                                                     │
 │  I2S MICROPHONE (INMP441) — add later               │
 │   WS / LRCLK     → GPIO 42                         │
 │   SCK / BCLK     → GPIO 41                         │
 │   SD / DATA      → GPIO 40                         │
 │                                                     │
 │  I2S SPEAKER (MAX98357A) — add later                │
 │   BCLK            → GPIO 39                        │
 │   LRC / WS        → GPIO 38                        │
 │   DIN             → GPIO 37                        │
 │                                                     │
 │  BUTTONS                                            │
 │   Push-to-Talk    → GPIO 0  (BOOT button works!)   │
 │   Mode Toggle     → GPIO 4                         │
 │                                                     │
 │  STATUS LEDs (optional WS2812 or plain LED)         │
 │   RGB LED         → GPIO 48 (built-in on some S3s) │
 └─────────────────────────────────────────────────────┘

 HARDWARE NEEDED (buy list):
   [x] ESP32-S3-N16R8 devkit      — you have this
   [ ] INMP441 I2S microphone     — ~$2 on AliExpress
   [ ] MAX98357A I2S amplifier    — ~$1.50 on AliExpress
   [ ] Small 8Ω 0.5W speaker      — ~$1
   [x] MQ135 gas sensor           — you have this
   [x] GP2Y1010 dust sensor       — you have this
   [x] SSD1306 OLED display       — you have this

 LIBRARIES (Arduino IDE → Library Manager):
   - ArduinoJson       (Benoit Blanchon)
   - Adafruit SSD1306  (Adafruit)
   - Adafruit GFX      (Adafruit)
   - ESP32-audioI2S    (schreibfaul1) — for audio playback
   - WiFiClientSecure  (built-in ESP32)
*/

// ─── Includes ──────────────────────────────────────────────────────────────
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <driver/i2s.h>
#include <esp_heap_caps.h>

// ─── WiFi & Server Config ──────────────────────────────────────────────────
#define WIFI_SSID        "YOUR_WIFI_SSID"
#define WIFI_PASSWORD    "YOUR_WIFI_PASSWORD"
#define CLOUD_SERVER_IP  "192.168.1.XXX"   // IP of your PC running cloud_server.py
#define CLOUD_SERVER_PORT 8765

// ─── Pin Definitions ───────────────────────────────────────────────────────
#define PIN_MQ135        1
#define PIN_GP2Y_VO      2
#define PIN_GP2Y_LED     3
#define PIN_OLED_SDA     8
#define PIN_OLED_SCL     9
#define PIN_RELAY        10
#define PIN_BTN_PTT      0    // Push-to-Talk (BOOT button)
#define PIN_BTN_MODE     4    // Mode switch

// I2S Microphone (INMP441) - uncomment when hardware is added
#define I2S_MIC_WS       42
#define I2S_MIC_SCK      41
#define I2S_MIC_SD       40
#define I2S_MIC_PORT     I2S_NUM_0

// I2S Speaker (MAX98357A) - uncomment when hardware is added
#define I2S_SPK_BCLK     39
#define I2S_SPK_WS       38
#define I2S_SPK_DATA     37
#define I2S_SPK_PORT     I2S_NUM_1

// ─── Constants ─────────────────────────────────────────────────────────────
#define OLED_WIDTH       128
#define OLED_HEIGHT      64
#define OLED_ADDR        0x3C

#define SAMPLE_RATE      16000
#define BITS_PER_SAMPLE  16
#define MAX_RECORD_SEC   8
#define AUDIO_BUF_SIZE   (SAMPLE_RATE * (BITS_PER_SAMPLE/8) * MAX_RECORD_SEC)
// 16000 * 2 * 8 = 256KB — fits easily in 8MB PSRAM

// ─── Global Objects ────────────────────────────────────────────────────────
Adafruit_SSD1306 display(OLED_WIDTH, OLED_HEIGHT, &Wire, -1);

// Audio buffer in PSRAM (critical — uses 8MB PSRAM of N16R8)
uint8_t* audioBuffer     = nullptr;
uint8_t* playbackBuffer  = nullptr;
size_t   audioLength     = 0;
size_t   playbackLength  = 0;

// State machine
enum State {
  STATE_IDLE,
  STATE_LISTENING,
  STATE_PROCESSING,
  STATE_SPEAKING,
  STATE_ERROR
};
State currentState = STATE_IDLE;

// Sensor data
struct SensorData {
  float aqi;
  float pm25;
  float pm10;
  float voc_ppm;
  float co2_ppm;
  float temperature;
  float humidity;
  bool  purifier_on;
  int   fan_speed;
  float filter_pct;
};
SensorData sensors;

// ─── OLED Helper ───────────────────────────────────────────────────────────
void oledShow(const char* line1, const char* line2 = "", const char* line3 = "") {
  display.clearDisplay();
  display.setTextColor(WHITE);

  display.setTextSize(1);
  display.setCursor(0, 0);
  display.println(line1);

  display.setCursor(0, 20);
  display.println(line2);

  display.setTextSize(1);
  display.setCursor(0, 45);
  display.println(line3);

  display.display();
}

void oledShowAQI(float aqi, const char* status, bool purifier_on) {
  display.clearDisplay();
  display.setTextColor(WHITE);

  // AQI big number
  display.setTextSize(2);
  display.setCursor(0, 0);
  display.print("AQI:");
  display.print((int)aqi);

  // Status
  display.setTextSize(1);
  display.setCursor(0, 20);
  display.print("Status: ");
  display.println(status);

  // Purifier state
  display.setCursor(0, 32);
  display.print("Purifier: ");
  display.println(purifier_on ? "ON" : "OFF");

  // Bottom bar
  display.drawLine(0, 52, 128, 52, WHITE);
  display.setCursor(0, 56);
  display.print("Hold BOOT to speak");

  display.display();
}

void oledAnimListening() {
  static int frame = 0;
  const char* frames[] = {"Listening .  ", "Listening .. ", "Listening ..."};
  display.clearDisplay();
  display.setTextSize(1);
  display.setCursor(0, 0);
  display.println("AirGuard AI");
  display.drawLine(0, 12, 128, 12, WHITE);
  display.setTextSize(1);
  display.setCursor(10, 28);
  display.println(frames[frame % 3]);
  display.setCursor(10, 44);
  display.println("Release to send");
  display.display();
  frame++;
}

void oledShowThinking() {
  static int dots = 0;
  char buf[32];
  snprintf(buf, sizeof(buf), "Thinking%s", dots == 0 ? "" : dots == 1 ? "." : dots == 2 ? ".." : "...");
  display.clearDisplay();
  display.setTextSize(1);
  display.setCursor(0, 0);
  display.println("AirGuard AI");
  display.drawLine(0, 12, 128, 12, WHITE);
  display.setTextSize(1);
  display.setCursor(10, 30);
  display.println(buf);
  display.display();
  dots = (dots + 1) % 4;
}

// ─── Sensor Reading ────────────────────────────────────────────────────────
float readDustPM25() {
  digitalWrite(PIN_GP2Y_LED, LOW);
  delayMicroseconds(280);
  int raw = analogRead(PIN_GP2Y_VO);
  delayMicroseconds(40);
  digitalWrite(PIN_GP2Y_LED, HIGH);
  float voltage = raw * (3.3f / 4095.0f);
  float dust = (voltage - 0.6f) / 0.005f;
  return max(0.0f, dust);
}

float readVOCPPM() {
  int raw = analogRead(PIN_MQ135);
  // Simplified — calibrate with clean air reference for accuracy
  // Rs/Ro ratio approach:
  float voltage = raw * (3.3f / 4095.0f);
  float rs = (3.3f - voltage) / voltage * 10.0f; // 10kΩ load
  float ppm = 116.6020682f * pow(rs / 76.63f, -2.769034857f);
  return max(0.0f, min(ppm, 1000.0f));
}

void updateSensors() {
  sensors.pm25        = readDustPM25();
  sensors.pm10        = sensors.pm25 * 1.7f;
  sensors.voc_ppm     = readVOCPPM();
  sensors.co2_ppm     = 400.0f + sensors.voc_ppm * 150.0f;
  sensors.temperature = 26.0f; // Add DHT11/22 on GPIO 5 for real temp
  sensors.humidity    = 55.0f; // Add DHT11/22 for real humidity

  // AQI from PM2.5 (EPA formula simplified)
  float pm = sensors.pm25;
  if      (pm <= 12.0f)  sensors.aqi = (pm / 12.0f) * 50.0f;
  else if (pm <= 35.4f)  sensors.aqi = 50.0f  + ((pm - 12.0f)  / 23.4f)  * 50.0f;
  else if (pm <= 55.4f)  sensors.aqi = 100.0f + ((pm - 35.4f)  / 20.0f)  * 50.0f;
  else if (pm <= 150.4f) sensors.aqi = 150.0f + ((pm - 55.4f)  / 95.0f)  * 50.0f;
  else                   sensors.aqi = 200.0f + ((pm - 150.4f) / 149.6f) * 100.0f;
}

const char* aqiLabel(float aqi) {
  if (aqi <= 50)  return "Good";
  if (aqi <= 100) return "Moderate";
  if (aqi <= 150) return "Unhealthy";
  return "Hazardous";
}

// ─── I2S Microphone Setup (INMP441) ───────────────────────────────────────
bool setupMicrophone() {
  i2s_config_t cfg = {
    .mode                 = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_RX),
    .sample_rate          = SAMPLE_RATE,
    .bits_per_sample      = I2S_BITS_PER_SAMPLE_32BIT, // INMP441 outputs 24-bit in 32-bit frame
    .channel_format       = I2S_CHANNEL_FMT_ONLY_LEFT,
    .communication_format = I2S_COMM_FORMAT_STAND_I2S,
    .intr_alloc_flags     = ESP_INTR_FLAG_LEVEL1,
    .dma_buf_count        = 4,
    .dma_buf_len          = 512,
    .use_apll             = false,
    .tx_desc_auto_clear   = false,
    .fixed_mclk           = 0
  };
  i2s_pin_config_t pins = {
    .mck_io_num   = I2S_PIN_NO_CHANGE,
    .bck_io_num   = I2S_MIC_SCK,
    .ws_io_num    = I2S_MIC_WS,
    .data_out_num = I2S_PIN_NO_CHANGE,
    .data_in_num  = I2S_MIC_SD
  };
  if (i2s_driver_install(I2S_MIC_PORT, &cfg, 0, NULL) != ESP_OK) return false;
  if (i2s_set_pin(I2S_MIC_PORT, &pins)                != ESP_OK) return false;
  i2s_zero_dma_buffer(I2S_MIC_PORT);
  return true;
}

// ─── I2S Speaker Setup (MAX98357A) ────────────────────────────────────────
bool setupSpeaker() {
  i2s_config_t cfg = {
    .mode                 = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_TX),
    .sample_rate          = SAMPLE_RATE,
    .bits_per_sample      = I2S_BITS_PER_SAMPLE_16BIT,
    .channel_format       = I2S_CHANNEL_FMT_ONLY_LEFT,
    .communication_format = I2S_COMM_FORMAT_STAND_I2S,
    .intr_alloc_flags     = ESP_INTR_FLAG_LEVEL1,
    .dma_buf_count        = 8,
    .dma_buf_len          = 512,
    .use_apll             = false,
    .tx_desc_auto_clear   = true,
    .fixed_mclk           = 0
  };
  i2s_pin_config_t pins = {
    .mck_io_num   = I2S_PIN_NO_CHANGE,
    .bck_io_num   = I2S_SPK_BCLK,
    .ws_io_num    = I2S_SPK_WS,
    .data_out_num = I2S_SPK_DATA,
    .data_in_num  = I2S_PIN_NO_CHANGE
  };
  if (i2s_driver_install(I2S_SPK_PORT, &cfg, 0, NULL) != ESP_OK) return false;
  if (i2s_set_pin(I2S_SPK_PORT, &pins)                != ESP_OK) return false;
  return true;
}

// ─── Audio Recording ───────────────────────────────────────────────────────
size_t recordAudio() {
  Serial.println("[MIC] Recording...");
  size_t totalBytes = 0;
  uint8_t* ptr = audioBuffer;

  // Read 32-bit I2S frames, convert to 16-bit PCM
  int32_t  i2sBuffer[256];
  int16_t* outBuf = (int16_t*)audioBuffer;
  size_t   outSamples = 0;
  size_t   maxSamples = AUDIO_BUF_SIZE / 2;

  unsigned long startMs = millis();
  while ((millis() - startMs) < (MAX_RECORD_SEC * 1000UL)
         && digitalRead(PIN_BTN_PTT) == LOW
         && outSamples < maxSamples) {
    size_t bytesRead = 0;
    i2s_read(I2S_MIC_PORT, i2sBuffer, sizeof(i2sBuffer), &bytesRead, portMAX_DELAY);
    int samplesRead = bytesRead / 4;
    for (int i = 0; i < samplesRead && outSamples < maxSamples; i++) {
      // INMP441: 24-bit value in upper 24 bits of 32-bit word
      outBuf[outSamples++] = (int16_t)(i2sBuffer[i] >> 14);
    }
  }

  audioLength = outSamples * 2; // bytes
  Serial.printf("[MIC] Recorded %u bytes (%.1f sec)\n",
                audioLength, (float)audioLength / (SAMPLE_RATE * 2));
  return audioLength;
}

// ─── Build WAV Header ──────────────────────────────────────────────────────
void buildWavHeader(uint8_t* header, uint32_t dataSize) {
  uint32_t fileSize   = dataSize + 44 - 8;
  uint32_t byteRate   = SAMPLE_RATE * 1 * (BITS_PER_SAMPLE / 8);
  uint16_t blockAlign = 1 * (BITS_PER_SAMPLE / 8);

  memcpy(header,      "RIFF", 4);
  memcpy(header + 4,  &fileSize,        4);
  memcpy(header + 8,  "WAVE", 4);
  memcpy(header + 12, "fmt ", 4);
  uint32_t fmtSize = 16; memcpy(header + 16, &fmtSize, 4);
  uint16_t audioFmt = 1; memcpy(header + 20, &audioFmt, 2);
  uint16_t channels = 1; memcpy(header + 22, &channels, 2);
  uint32_t sr = SAMPLE_RATE; memcpy(header + 24, &sr, 4);
  memcpy(header + 28, &byteRate,    4);
  memcpy(header + 30, &blockAlign,  2);
  uint16_t bps = BITS_PER_SAMPLE; memcpy(header + 34, &bps, 2);
  memcpy(header + 36, "data", 4);
  memcpy(header + 40, &dataSize, 4);
}

// ─── Send to Cloud & Get Response ─────────────────────────────────────────
bool sendToCloudAndGetResponse(bool textOnly = false, const char* textQuery = nullptr) {
  WiFiClient client;
  if (!client.connect(CLOUD_SERVER_IP, CLOUD_SERVER_PORT)) {
    Serial.println("[NET] Cannot connect to cloud server!");
    oledShow("ERROR", "Cannot reach", "cloud server");
    return false;
  }

  // Build JSON payload
  DynamicJsonDocument doc(512);
  doc["type"]       = textOnly ? "text_query" : "voice_audio";
  doc["aqi"]        = sensors.aqi;
  doc["pm25"]       = sensors.pm25;
  doc["pm10"]       = sensors.pm10;
  doc["voc"]        = sensors.voc_ppm;
  doc["co2"]        = sensors.co2_ppm;
  doc["temp"]       = sensors.temperature;
  doc["humidity"]   = sensors.humidity;
  doc["purifier"]   = sensors.purifier_on;
  doc["fan_speed"]  = sensors.fan_speed;
  doc["filter_pct"] = sensors.filter_pct;

  if (textOnly && textQuery) {
    doc["query"] = textQuery;
  }

  String jsonStr;
  serializeJson(doc, jsonStr);
  uint32_t jsonLen = jsonStr.length();

  if (textOnly) {
    // Send: [4-byte json_len][json]
    client.write((uint8_t*)&jsonLen, 4);
    client.print(jsonStr);
  } else {
    // Send: [4-byte json_len][json][4-byte audio_len][44-byte WAV header][audio_data]
    uint8_t wavHeader[44];
    buildWavHeader(wavHeader, audioLength);
    uint32_t totalAudio = 44 + audioLength;

    client.write((uint8_t*)&jsonLen, 4);
    client.print(jsonStr);
    client.write((uint8_t*)&totalAudio, 4);
    client.write(wavHeader, 44);

    // Stream audio in chunks (PSRAM → TCP)
    const size_t CHUNK = 1024;
    for (size_t sent = 0; sent < audioLength; sent += CHUNK) {
      size_t toSend = min(CHUNK, audioLength - sent);
      client.write(audioBuffer + sent, toSend);
    }
  }

  Serial.println("[NET] Sent to cloud, waiting for response...");
  oledShowThinking();

  // Read response: [4-byte type][payload]
  // type: 0 = text response, 1 = audio response
  unsigned long timeout = millis() + 15000;
  while (client.available() == 0 && millis() < timeout) {
    delay(50);
    oledShowThinking();
  }

  if (client.available() == 0) {
    oledShow("TIMEOUT", "No response", "from AI");
    client.stop();
    return false;
  }

  uint8_t responseType = 0;
  client.read(&responseType, 1);

  if (responseType == 0) {
    // Text response — show on OLED + scroll
    uint32_t textLen = 0;
    client.read((uint8_t*)&textLen, 4);
    String response = "";
    while (client.available() && response.length() < textLen) {
      response += (char)client.read();
    }
    Serial.println("[AI] " + response);
    displayScrollText(response.c_str());

    // Check for commands in response
    processAICommands(response.c_str());

  } else if (responseType == 1) {
    // Audio response — store in PSRAM playback buffer and play
    uint32_t audioLen = 0;
    client.read((uint8_t*)&audioLen, 4);
    playbackLength = min((uint32_t)(AUDIO_BUF_SIZE), audioLen);

    size_t received = 0;
    while (received < playbackLength && client.connected()) {
      if (client.available()) {
        received += client.read(playbackBuffer + received,
                                playbackLength - received);
      }
    }
    Serial.printf("[AUDIO] Received %u bytes for playback\n", received);
    playAudio(playbackBuffer, received);
  }

  client.stop();
  return true;
}

// ─── Audio Playback ────────────────────────────────────────────────────────
void playAudio(uint8_t* data, size_t length) {
  currentState = STATE_SPEAKING;
  oledShow("Speaking...", "AI Response", "");

  // Skip WAV header (44 bytes) if present
  uint8_t* pcmData = data;
  size_t   pcmLen  = length;
  if (length > 44 && memcmp(data, "RIFF", 4) == 0) {
    pcmData += 44;
    pcmLen  -= 44;
  }

  size_t bytesWritten = 0;
  const size_t CHUNK = 512;
  for (size_t i = 0; i < pcmLen; i += CHUNK) {
    size_t toWrite = min(CHUNK, pcmLen - i);
    i2s_write(I2S_SPK_PORT, pcmData + i, toWrite, &bytesWritten, portMAX_DELAY);
  }

  currentState = STATE_IDLE;
}

// ─── Display Scrolling Text ────────────────────────────────────────────────
void displayScrollText(const char* text) {
  // Show text in chunks of ~60 chars (fits 4 lines on OLED)
  int len    = strlen(text);
  int chunkSz = 90; // ~3 lines at textSize 1
  int start  = 0;

  while (start < len) {
    char buf[96] = {0};
    int end = min(start + chunkSz, len);
    // Don't cut in middle of word
    while (end < len && text[end] != ' ' && end > start + 60) end--;
    strncpy(buf, text + start, end - start);

    display.clearDisplay();
    display.setTextSize(1);
    display.setCursor(0, 0);
    display.print("[AI]: ");
    display.setTextWrap(true);
    display.setCursor(0, 10);
    display.println(buf);
    display.display();

    start = end + 1;
    delay(2500); // Show each chunk for 2.5s
  }
}

// ─── Process AI Commands ───────────────────────────────────────────────────
void processAICommands(const char* response) {
  String resp = String(response);
  resp.toLowerCase();

  if (resp.indexOf("turn on") >= 0 || resp.indexOf("start purifier") >= 0) {
    sensors.purifier_on = true;
    digitalWrite(PIN_RELAY, HIGH);
    Serial.println("[CMD] Purifier ON");
  }
  if (resp.indexOf("turn off") >= 0 || resp.indexOf("stop purifier") >= 0) {
    sensors.purifier_on = false;
    digitalWrite(PIN_RELAY, LOW);
    Serial.println("[CMD] Purifier OFF");
  }
  if (resp.indexOf("fan high") >= 0 || resp.indexOf("speed high") >= 0) {
    sensors.fan_speed = 3;
    // Add PWM logic here for multi-speed relay
  }
  if (resp.indexOf("fan low") >= 0 || resp.indexOf("speed low") >= 0) {
    sensors.fan_speed = 1;
  }
  if (resp.indexOf("fan medium") >= 0 || resp.indexOf("speed medium") >= 0) {
    sensors.fan_speed = 2;
  }
}

// ─── Send Sensor Data (HTTP endpoint for Streamlit) ───────────────────────
// This runs a minimal HTTP server on port 80
#include <WebServer.h>
WebServer httpServer(80);

void handleSensorsHTTP() {
  DynamicJsonDocument doc(512);
  doc["aqi"]        = sensors.aqi;
  doc["dust_pm25"]  = sensors.pm25;
  doc["dust_pm10"]  = sensors.pm10;
  doc["voc_ppm"]    = sensors.voc_ppm;
  doc["co2_ppm"]    = sensors.co2_ppm;
  doc["temperature"]= sensors.temperature;
  doc["humidity"]   = sensors.humidity;
  doc["purifier"]   = sensors.purifier_on;
  doc["fan_speed"]  = sensors.fan_speed;
  doc["filter_pct"] = sensors.filter_pct;

  String body;
  serializeJson(doc, body);
  httpServer.sendHeader("Access-Control-Allow-Origin", "*");
  httpServer.send(200, "application/json", body);
}

void handleRelayHTTP() {
  if (httpServer.hasArg("speed")) {
    int spd = httpServer.arg("speed").toInt();
    sensors.fan_speed = constrain(spd, 0, 3);
    sensors.purifier_on = (spd > 0);
    digitalWrite(PIN_RELAY, sensors.purifier_on ? HIGH : LOW);
  }
  if (httpServer.hasArg("purifier")) {
    bool on = httpServer.arg("purifier") == "1";
    sensors.purifier_on = on;
    digitalWrite(PIN_RELAY, on ? HIGH : LOW);
  }
  httpServer.send(200, "application/json", "{\"ok\":true}");
}

void handleStatusHTTP() {
  DynamicJsonDocument doc(256);
  doc["free_heap"]  = ESP.getFreeHeap();
  doc["free_psram"] = ESP.getFreePsram();
  doc["uptime_s"]   = millis() / 1000;
  doc["wifi_rssi"]  = WiFi.RSSI();
  doc["ip"]         = WiFi.localIP().toString();
  String body; serializeJson(doc, body);
  httpServer.send(200, "application/json", body);
}

// ─── Setup ─────────────────────────────────────────────────────────────────
void setup() {
  Serial.begin(115200);
  Serial.println("\n╔═══════════════════════════╗");
  Serial.println("║   AirGuard AI v1.0        ║");
  Serial.println("║   ESP32-S3-N16R8          ║");
  Serial.println("╚═══════════════════════════╝");

  // PSRAM check — critical for N16R8
  if (!psramFound()) {
    Serial.println("ERROR: PSRAM not found! Check board config.");
    Serial.println("In Arduino IDE: Tools → PSRAM → OPI PSRAM");
    while (1) delay(1000);
  }
  Serial.printf("PSRAM: %.1f MB free\n", ESP.getFreePsram() / 1048576.0f);

  // Allocate audio buffers in PSRAM
  audioBuffer    = (uint8_t*)heap_caps_malloc(AUDIO_BUF_SIZE, MALLOC_CAP_SPIRAM);
  playbackBuffer = (uint8_t*)heap_caps_malloc(AUDIO_BUF_SIZE, MALLOC_CAP_SPIRAM);
  if (!audioBuffer || !playbackBuffer) {
    Serial.println("ERROR: PSRAM allocation failed!");
    while (1) delay(1000);
  }
  Serial.printf("Audio buffers: 2 × %d KB in PSRAM\n", AUDIO_BUF_SIZE / 1024);

  // Pins
  pinMode(PIN_GP2Y_LED, OUTPUT);
  pinMode(PIN_RELAY, OUTPUT);
  pinMode(PIN_BTN_PTT, INPUT_PULLUP);
  pinMode(PIN_BTN_MODE, INPUT_PULLUP);
  digitalWrite(PIN_RELAY, LOW);

  // I2C + OLED
  Wire.begin(PIN_OLED_SDA, PIN_OLED_SCL);
  if (!display.begin(SSD1306_SWITCHCAPVCC, OLED_ADDR)) {
    Serial.println("OLED not found — continuing without display");
  } else {
    display.clearDisplay();
    display.setTextSize(1);
    display.setTextColor(WHITE);
    display.setCursor(0, 0);
    display.println("AirGuard AI");
    display.println("Initializing...");
    display.display();
  }

  // WiFi
  oledShow("Connecting WiFi", WIFI_SSID, "...");
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  int tries = 0;
  while (WiFi.status() != WL_CONNECTED && tries < 30) {
    delay(500);
    Serial.print(".");
    tries++;
  }
  if (WiFi.status() != WL_CONNECTED) {
    oledShow("WiFi FAILED", "Check SSID/Pass", "Restarting...");
    delay(3000);
    ESP.restart();
  }
  Serial.println("\nWiFi connected: " + WiFi.localIP().toString());
  oledShow("WiFi OK", WiFi.localIP().toString().c_str(), "Starting...");

  // I2S Microphone — comment out if not yet installed
  // if (!setupMicrophone()) Serial.println("WARN: Mic init failed");
  // else                    Serial.println("Microphone ready");

  // I2S Speaker — comment out if not yet installed
  // if (!setupSpeaker()) Serial.println("WARN: Speaker init failed");
  // else                 Serial.println("Speaker ready");

  // HTTP server for Streamlit integration
  httpServer.on("/sensors", handleSensorsHTTP);
  httpServer.on("/relay",   handleRelayHTTP);
  httpServer.on("/status",  handleStatusHTTP);
  httpServer.begin();
  Serial.println("HTTP server on port 80");

  // Initial sensor read
  updateSensors();
  sensors.purifier_on = true;
  sensors.fan_speed   = 1;
  sensors.filter_pct  = 85.0f;

  oledShowAQI(sensors.aqi, aqiLabel(sensors.aqi), sensors.purifier_on);
  Serial.println("Ready! Hold BOOT button to speak to AI.");
}

// ─── Main Loop ─────────────────────────────────────────────────────────────
unsigned long lastSensorUpdate = 0;
unsigned long lastOledUpdate   = 0;

void loop() {
  httpServer.handleClient();

  // Update sensors every 3 seconds
  if (millis() - lastSensorUpdate > 3000) {
    updateSensors();
    lastSensorUpdate = millis();

    // Auto fan control based on AQI
    if (sensors.purifier_on) {
      if      (sensors.aqi <= 50)  sensors.fan_speed = 1;
      else if (sensors.aqi <= 100) sensors.fan_speed = 2;
      else                         sensors.fan_speed = 3;
    }
  }

  // Update OLED every second (when idle)
  if (currentState == STATE_IDLE && millis() - lastOledUpdate > 1000) {
    oledShowAQI(sensors.aqi, aqiLabel(sensors.aqi), sensors.purifier_on);
    lastOledUpdate = millis();
  }

  // ── Push-to-Talk Button (BOOT = GPIO0) ──────────────────────────────────
  if (digitalRead(PIN_BTN_PTT) == LOW && currentState == STATE_IDLE) {
    delay(50); // debounce
    if (digitalRead(PIN_BTN_PTT) != LOW) return;

    Serial.println("[PTT] Button pressed — start recording");
    currentState = STATE_LISTENING;

    // Wait for mic hardware; for now send a text query with sensor context
    // Uncomment recordAudio() when INMP441 is connected:
    // recordAudio();

    // ── DEMO MODE (no mic) — sends text query with sensor data ─────────────
    // Simulates "what is the air quality?" query
    oledShow("Processing...", "Asking Claude AI", "");
    currentState = STATE_PROCESSING;

    sendToCloudAndGetResponse(true, "What is the current air quality and should I be concerned?");

    currentState = STATE_IDLE;
    Serial.println("[PTT] Done");
  }

  // ── Mode button (GPIO4) — cycle through preset queries ──────────────────
  static int queryMode = 0;
  if (digitalRead(PIN_BTN_MODE) == LOW && currentState == STATE_IDLE) {
    delay(50);
    if (digitalRead(PIN_BTN_MODE) != LOW) return;

    const char* queries[] = {
      "Is the air quality safe for exercise indoors?",
      "Should I open my windows right now?",
      "What fan speed do you recommend?",
      "How long until I need to replace the HEPA filter?",
      "Give me a summary of today's air quality",
      "Are there any dangerous pollutant levels?"
    };
    int numQueries = sizeof(queries) / sizeof(queries[0]);

    Serial.printf("[BTN] Preset query %d: %s\n", queryMode, queries[queryMode]);
    oledShow("Asking AI...", queries[queryMode], "");

    currentState = STATE_PROCESSING;
    sendToCloudAndGetResponse(true, queries[queryMode]);
    currentState = STATE_IDLE;

    queryMode = (queryMode + 1) % numQueries;
    delay(500);
  }

  // High AQI auto-alert (send alert to cloud every 5 min if hazardous)
  static unsigned long lastAutoAlert = 0;
  if (sensors.aqi > 150 && millis() - lastAutoAlert > 300000) {
    Serial.println("[AUTO] Hazardous AQI — sending auto alert");
    sendToCloudAndGetResponse(true, "AQI is hazardous. Give emergency advice and adjust purifier.");
    lastAutoAlert = millis();
  }

  delay(10);
}
