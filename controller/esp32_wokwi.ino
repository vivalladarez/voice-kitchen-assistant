/**
 * Voice Kitchen Assistant — ESP32 Wokwi controller
 *
 * Hardware (see diagram.json):
 *   DHT22  GPIO 15
 *   OLED   I2C SDA 21, SCL 22 (SSD1306 0x3C)
 *   LED    GPIO 2
 *   Buzzer GPIO 4
 *
 * MQTT (test.mosquitto.org:1883):
 *   kitchen/temperature  publish JSON every 5 s
 *   kitchen/command      subscribe: start | next | alert
 *   kitchen/status       publish JSON status
 */

#include <WiFi.h>
#include <PubSubClient.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include "DHTesp.h"

// --- Pins ---
static const int PIN_DHT = 15;
static const int PIN_LED = 2;
static const int PIN_BUZZER = 4;
static const int I2C_SDA = 21;
static const int I2C_SCL = 22;

// --- WiFi (Wokwi simulation) ---
static const char *WIFI_SSID = "Wokwi-GUEST";
static const char *WIFI_PASS = "";

// --- MQTT ---
static const char *MQTT_BROKER = "test.mosquitto.org";
static const uint16_t MQTT_PORT = 1883;
static const char *TOPIC_TEMP = "kitchen/temperature";
static const char *TOPIC_CMD = "kitchen/command";
static const char *TOPIC_STATUS = "kitchen/status";

// --- OLED ---
static const int SCREEN_W = 128;
static const int SCREEN_H = 64;
static Adafruit_SSD1306 display(SCREEN_W, SCREEN_H, &Wire, -1);

static DHTesp dht;
static WiFiClient wifiClient;
static PubSubClient mqtt(wifiClient);

static String lastCommand = "-";
static unsigned long lastTempMs = 0;
static const unsigned long TEMP_INTERVAL_MS = 5000;

static bool ledOn = false;
static bool alertMode = false;
static unsigned long lastAlertBeepMs = 0;

static void connectWiFi();
static void connectMQTT();
static void mqttCallback(char *topic, byte *payload, unsigned int length);
static void handleCommand(const String &cmd);
static void publishTemperature();
static void publishStatus(const char *status);
static void refreshOled(float tempC);
static void beepAck();

void setup() {
  Serial.begin(115200);

  pinMode(PIN_LED, OUTPUT);
  pinMode(PIN_BUZZER, OUTPUT);
  digitalWrite(PIN_LED, LOW);
  noTone(PIN_BUZZER);

  Wire.begin(I2C_SDA, I2C_SCL);
  if (!display.begin(SSD1306_SWITCHCAPVCC, 0x3C)) {
    Serial.println(F("SSD1306 init failed"));
    for (;;)
      delay(1000);
  }

  display.clearDisplay();
  display.setTextSize(1);
  display.setTextColor(SSD1306_WHITE);
  display.setCursor(0, 0);
  display.println(F("Voice Kitchen"));
  display.println(F("Booting..."));
  display.display();

  dht.setup(PIN_DHT, DHTesp::DHT22);

  mqtt.setServer(MQTT_BROKER, MQTT_PORT);
  mqtt.setCallback(mqttCallback);
  mqtt.setBufferSize(256);

  connectWiFi();
  connectMQTT();
  publishStatus("online");
  refreshOled(NAN);
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) {
    connectWiFi();
  }
  if (!mqtt.connected()) {
    connectMQTT();
  }
  mqtt.loop();

  const unsigned long now = millis();

  if (now - lastTempMs >= TEMP_INTERVAL_MS) {
    lastTempMs = now;
    publishTemperature();
  }

  if (alertMode) {
    if (now - lastAlertBeepMs >= 400) {
      lastAlertBeepMs = now;
      tone(PIN_BUZZER, 880, 120);
    }
    static unsigned long lastBlinkMs = 0;
    if (now - lastBlinkMs >= 250) {
      lastBlinkMs = now;
      ledOn = !ledOn;
      digitalWrite(PIN_LED, ledOn ? HIGH : LOW);
    }
  }
}

static void mqttCallback(char *topic, byte *payload, unsigned int length) {
  String msg;
  msg.reserve(length + 1);
  for (unsigned int i = 0; i < length; i++) {
    msg += static_cast<char>(payload[i]);
  }
  msg.trim();
  msg.toLowerCase();
  handleCommand(msg);
}

static void handleCommand(const String &cmd) {
  lastCommand = cmd;
  Serial.printf("MQTT cmd: %s\n", cmd.c_str());

  if (cmd == "start") {
    alertMode = false;
    noTone(PIN_BUZZER);
    ledOn = true;
    digitalWrite(PIN_LED, HIGH);
    beepAck();
    publishStatus("started");
  } else if (cmd == "next") {
    alertMode = false;
    noTone(PIN_BUZZER);
    ledOn = !ledOn;
    digitalWrite(PIN_LED, ledOn ? HIGH : LOW);
    beepAck();
    publishStatus("next");
  } else if (cmd == "alert") {
    alertMode = true;
    ledOn = true;
    digitalWrite(PIN_LED, HIGH);
    tone(PIN_BUZZER, 880, 300);
    publishStatus("alert");
  } else {
    publishStatus("unknown_command");
  }

  TempAndHumidity reading = dht.getTempAndHumidity();
  refreshOled(reading.isValid ? reading.temperature : NAN);
}

static void publishTemperature() {
  TempAndHumidity reading = dht.getTempAndHumidity();
  if (!reading.isValid) {
    Serial.println(F("DHT22 read failed"));
    publishStatus("dht_error");
    return;
  }

  char payload[80];
  snprintf(payload, sizeof(payload), "{\"temperature\":%.1f,\"humidity\":%.1f}",
           reading.temperature, reading.humidity);
  mqtt.publish(TOPIC_TEMP, payload);
  Serial.printf("Published %s\n", payload);

  refreshOled(reading.temperature);
}

static void publishStatus(const char *status) {
  char payload[96];
  snprintf(payload, sizeof(payload),
           "{\"status\":\"%s\",\"last_command\":\"%s\"}", status,
           lastCommand.c_str());
  mqtt.publish(TOPIC_STATUS, payload);
}

static void refreshOled(float tempC) {
  display.clearDisplay();
  display.setCursor(0, 0);
  display.println(F("Voice Kitchen"));
  display.drawLine(0, 10, 127, 10, SSD1306_WHITE);
  display.setCursor(0, 14);
  if (isnan(tempC)) {
    display.println(F("Temp:  --.- C"));
  } else {
    display.printf("Temp: %5.1f C\n", tempC);
  }
  display.println();
  display.print(F("Last cmd:"));
  display.println(lastCommand);
  if (alertMode) {
    display.println(F("!! ALERT !!"));
  }
  display.display();
}

static void beepAck() {
  tone(PIN_BUZZER, 523, 120);
  delay(130);
  noTone(PIN_BUZZER);
}

static void connectWiFi() {
  if (WiFi.status() == WL_CONNECTED) {
    return;
  }
  Serial.printf("WiFi: connecting to %s\n", WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);

  uint8_t attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 40) {
    delay(250);
    Serial.print('.');
    attempts++;
  }
  Serial.println();
  if (WiFi.status() == WL_CONNECTED) {
    Serial.print(F("WiFi OK, IP: "));
    Serial.println(WiFi.localIP());
  } else {
    Serial.println(F("WiFi failed"));
  }
}

static void connectMQTT() {
  while (!mqtt.connected()) {
    const String clientId =
        String("kitchen-esp32-") + String(random(0xffff), HEX);
    Serial.printf("MQTT: connecting as %s\n", clientId.c_str());
    if (mqtt.connect(clientId.c_str())) {
      Serial.println(F("MQTT connected"));
      mqtt.subscribe(TOPIC_CMD);
      publishStatus("mqtt_connected");
      return;
    }
    Serial.printf("MQTT failed, rc=%d\n", mqtt.state());
    delay(2000);
  }
}
