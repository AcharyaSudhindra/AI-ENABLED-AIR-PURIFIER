#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>

#define SCREEN_WIDTH 128
#define SCREEN_HEIGHT 64
Adafruit_SSD1306 display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, -1);

// MQ135 connected to ADC pin (example: GPIO34)
#define MQ135_PIN 34

// Relay pin (to control fan/filter)
#define RELAY_PIN 25

// Threshold voltage for poor air quality (adjust after calibration)
#define THRESHOLD_VOLTAGE 1.2

void setup() {
  Serial.begin(115200);

  // OLED init
  if(!display.begin(SSD1306_SWITCHCAPVCC, 0x3C)) {
    Serial.println(F("SSD1306 allocation failed"));
    for(;;);
  }
  display.clearDisplay();

  // Relay init
  pinMode(RELAY_PIN, OUTPUT);
  digitalWrite(RELAY_PIN, LOW); // Fan OFF initially
}

void loop() {
  // Read MQ135 sensor
  int sensorValue = analogRead(MQ135_PIN);
  float voltage = (sensorValue / 4095.0) * 3.3;

  // Print to Serial
  Serial.print("ADC: ");
  Serial.print(sensorValue);
  Serial.print(" | Voltage: ");
  Serial.println(voltage);

  // Display on OLED
  display.clearDisplay();
  display.setTextSize(1);
  display.setTextColor(SSD1306_WHITE);

  display.setCursor(0,0);
  display.println("Air Purifier");

  display.setCursor(0,20);
  display.print("ADC: ");
  display.println(sensorValue);

  display.setCursor(0,35);
  display.print("Volt: ");
  display.print(voltage, 2);
  display.println(" V");

  // Relay control
  if(voltage > THRESHOLD_VOLTAGE) {
    display.setCursor(0,50);
    display.println("Fan: ON");
    digitalWrite(RELAY_PIN, HIGH);
  } else {
    display.setCursor(0,50);
    display.println("Fan: OFF");
    digitalWrite(RELAY_PIN, LOW);
  }

  display.display();
  delay(1000);
}
