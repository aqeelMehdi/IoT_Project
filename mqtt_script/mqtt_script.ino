#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <MQTTClient.h>
#include <ArduinoJson.h>
#include <DHT.h>
#include "MQ135.h"
#include "secrets.h"

// ========================== CONFIGURATION ==========================
#define DHT_PIN 26
#define DHT_TYPE DHT11
#define MQ135_PIN 34
#define PMS_RX 16
#define PMS_TX 17

#define BUZZER_PIN 5   // Actuator pin
#define GREEN_LED_PIN 18
#define RED_LED_PIN 19

#define PUBLISH_INTERVAL_MS (4000UL)
#define DHT_MIN_INTERVAL_MS (2200UL)

#define AWS_IOT_PORT 8883
#define AWS_IOT_PUBLISH_TOPIC "esp32/esp32-to-aws"
#define AWS_IOT_SUB_TOPIC     "esp32/commands"

// ========================== SENSOR OBJECTS ==========================
DHT dht(DHT_PIN, DHT_TYPE);
HardwareSerial pmsSerial(2);
MQ135 gasSensor(MQ135_PIN, 10.0, 76.6);

// PMS5003 data structure
struct pms5003data {
  uint16_t framelen;
  uint16_t pm10_standard, pm25_standard, pm100_standard;
  uint16_t pm10_env, pm25_env, pm100_env;
  uint16_t particles_03um, particles_05um, particles_10um;
  uint16_t particles_25um, particles_50um, particles_100um;
  uint16_t unused;
  uint16_t checksum;
};
pms5003data data;

// ========================== AWS MQTT CLIENT ==========================
WiFiClientSecure net;
MQTTClient client(1024);

// ========================== GLOBALS ================================
unsigned long lastPublishTime = 0;
unsigned long lastDhtReadTime = 0;
float lastTempC = NAN, lastHumid = NAN;

// CLOUD OVERRIDE LOGIC
bool cloudOverride = false;   // AUTO mode = false
bool overrideState = false;   // ON or OFF when cloud override = true

// ========================== FORWARD DECLARATIONS ====================
void ensureWiFi();
void ensureAWS();
bool readPMSdata(Stream *s, pms5003data &out);
void sendToAWS();
float dewPoint(float t, float h);
float computeHeatIndex(float t, float h);
int computeAQI_PM25_US(float pm25);
String getAQICategory(int aqi);

// ========================== MQTT MESSAGE HANDLER ====================
void messageHandler(String &topic, String &payload) {
  Serial.println("\n=== AWS Command Received ===");
  Serial.println("Topic: " + topic);
  Serial.println("Payload: " + payload);

  if (payload == "BUZZER_ON") {
    cloudOverride = true;
    overrideState = true;
    digitalWrite(BUZZER_PIN, HIGH);
    Serial.println("Cloud Override → Buzzer ON");
  }
  else if (payload == "BUZZER_OFF") {
    cloudOverride = true;
    overrideState = false;
    digitalWrite(BUZZER_PIN, LOW);
    Serial.println("Cloud Override → Buzzer OFF");
  }
  else if (payload == "AUTO") {
    cloudOverride = false;
    Serial.println("Switched to AUTO mode → Local Logic Active");
  }
  else {
    Serial.println("Unknown command.");
  }
}

// ========================== SETUP ==========================
void setup() {
  Serial.begin(115200);
  delay(1000);
  Serial.println("\nStarting ESP32 AWS IoT Environmental Node...");

  pinMode(BUZZER_PIN, OUTPUT);
  digitalWrite(BUZZER_PIN, LOW);
  pinMode(GREEN_LED_PIN, OUTPUT);
  pinMode(RED_LED_PIN, OUTPUT);

  digitalWrite(GREEN_LED_PIN, LOW);
  digitalWrite(RED_LED_PIN,LOW);
  dht.begin();
  pmsSerial.begin(9600, SERIAL_8N1, PMS_RX, PMS_TX);

  ensureWiFi();
  ensureAWS();

  client.onMessage(messageHandler);
  client.subscribe(AWS_IOT_SUB_TOPIC);

  Serial.println("Setup complete!\n");
}

// ========================== LOOP ==========================
void loop() {
  client.loop();

  ensureWiFi();
  if (!client.connected()) ensureAWS();

  unsigned long now = millis();
  if (now - lastPublishTime >= PUBLISH_INTERVAL_MS) {
    sendToAWS();
    lastPublishTime = now;
  }
}

// ========================== WIFI ==========================
void ensureWiFi() {
  if (WiFi.status() == WL_CONNECTED) return;

  Serial.print("Connecting to WiFi ");
  Serial.println(WIFI_SSID);

  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }

  Serial.println("\nWiFi Connected!");
  Serial.println("IP: " + WiFi.localIP().toString());
}

// ========================== AWS CONNECTION ==========================
void ensureAWS() {
  Serial.print("Connecting to AWS IoT Core");

  net.setCACert(AWS_CERT_CA);
  net.setCertificate(AWS_CERT_CRT);
  net.setPrivateKey(AWS_CERT_PRIVATE);

  client.begin(AWS_IOT_ENDPOINT, AWS_IOT_PORT, net);

  while (!client.connect(THINGNAME)) {
    Serial.print(".");
    delay(750);
  }

  Serial.println("\nConnected to AWS IoT Core!");
  client.subscribe(AWS_IOT_SUB_TOPIC);
}

// ========================== PMS READER ==========================
bool readPMSdata(Stream *s, pms5003data &out) {
  if (!s->available()) return false;

  while (s->available() >= 32) {
    if (s->peek() != 0x42) { s->read(); continue; }
    if (s->available() < 32) return false;

    uint8_t h = s->read();
    if (s->peek() != 0x4D) continue;
    uint8_t m = s->read();

    uint8_t buf[30];
    if (s->readBytes((char*)buf, 30) != 30) return false;

    uint16_t sum = h + m;
    for (int i = 0; i < 28; i++) sum += buf[i];

    uint16_t frame[15];
    for (int i = 0; i < 15; i++)
      frame[i] = (buf[2 + 2*i] << 8) | buf[2 + 2*i + 1];

    memcpy(&out, frame, 30);
    return (sum == out.checksum);
  }
  return false;
}

// ========================== MATH HELPERS ==========================
float dewPoint(float t, float h) {
  return t - ((100.0 - h) / 5.0);
}

float computeHeatIndex(float t, float h) {
  return t + 0.33 * h - 0.7;
}

int computeAQI_PM25_US(float C) {
  struct Bp { float Clow, Chigh; int Ilow, Ihigh; };
  const Bp bp[] = {
    { 0, 12, 0, 50 },
    { 12.1, 35.4, 51, 100 },
    { 35.5, 55.4, 101, 150 },
    { 55.5, 150.4, 151, 200 },
    { 150.5, 250.4, 201, 300 },
    { 250.5, 350.4, 301, 400 },
    { 350.5, 500.4, 401, 500 }
  };

  for (auto &r : bp) {
    if (C <= r.Chigh)
      return (int)(((r.Ihigh - r.Ilow) * (C - r.Clow) / (r.Chigh - r.Clow)) + r.Ilow);
  }
  return 500;
}

String getAQICategory(int aqi) {
  if (aqi <= 50) return "Good";
  if (aqi <= 100) return "Moderate";
  if (aqi <= 150) return "Unhealthy for SG";
  if (aqi <= 200) return "Unhealthy";
  if (aqi <= 300) return "Very Unhealthy";
  return "Hazardous";
}

// ========================== PUBLISH + LOCAL LOGIC ==========================
void sendToAWS() {
  const unsigned long start_us = micros();

  // Read DHT
  if (millis() - lastDhtReadTime >= DHT_MIN_INTERVAL_MS) {
    lastTempC = dht.readTemperature();
    lastHumid = dht.readHumidity();
    lastDhtReadTime = millis();
  }

  bool pmsSuccess = readPMSdata(&pmsSerial, data);
  float co2_ppm = gasSensor.getPPM();
  float dewPt = dewPoint(lastTempC, lastHumid);
  float heatIndexC = computeHeatIndex(lastTempC, lastHumid);

  uint16_t pm25 = pmsSuccess ? data.pm25_standard : 0;
  int aqi = computeAQI_PM25_US(pm25);
  String aqiCat = getAQICategory(aqi);

  // ====================== LOCAL SAFETY LOGIC ======================
  if (!cloudOverride) {
    if (aqi > 150 || co2_ppm > 0.001) {
      digitalWrite(BUZZER_PIN, HIGH);
      digitalWrite(RED_LED_PIN, HIGH);
      digitalWrite(GREEN_LED_PIN, LOW);
      Serial.println("LOCAL ALERT → Buzzer ON,RED LED ON");
    } else {
      digitalWrite(BUZZER_PIN, LOW);
      digitalWrite(RED_LED_PIN, LOW);
      digitalWrite(GREEN_LED_PIN, HIGH);
      Serial.println("LOCAL Normal → Buzzer OFF,GREEN LED ON");
    }
  }
  else {
    digitalWrite(BUZZER_PIN, overrideState ? HIGH : LOW);
    if (aqi > 150 || co2_ppm > 0.001) {
        digitalWrite(RED_LED_PIN, HIGH);
        digitalWrite(GREEN_LED_PIN, LOW);
    } else {
        digitalWrite(RED_LED_PIN, LOW);
        digitalWrite(GREEN_LED_PIN,HIGH);
}
  }

  unsigned long elapsed_us = micros() - start_us;
  double elapsed_ms = (double)elapsed_us / 1000.0;

  // ========================== JSON PAYLOAD ==========================
  StaticJsonDocument<1024> doc;

  doc["device_id"] = THINGNAME;
  doc["ip_address"] = WiFi.localIP().toString();
  doc["temperature_C"] = lastTempC;
  doc["humidity_percent"] = lastHumid;
  doc["dew_point_C"] = dewPt;
  doc["heat_index_C"] = heatIndexC;

  doc["pms_ok"] = pmsSuccess;
  doc["pm1_0_ugm3"] = pmsSuccess ? data.pm10_standard : 0;
  doc["pm2_5_ugm3"] = pmsSuccess ? data.pm25_standard : 0;
  doc["pm10_ugm3"] = pmsSuccess ? data.pm100_standard : 0;

  doc["aqi_index"] = aqi;
  doc["aqi_category"] = aqiCat;
  doc["co2_ppm"] = co2_ppm;

  doc["timestamp_ms"] = millis();
  doc["computation_time_us"] = elapsed_us;
  doc["computation_time_ms"] = elapsed_ms;
  doc["green_led"] = digitalRead(GREEN_LED_PIN);
  doc["red_led"] = digitalRead(RED_LED_PIN);

  // NEW FIELDS
  doc["buzzer_state"] = digitalRead(BUZZER_PIN);
  doc["mode"] = cloudOverride ? "CLOUD_OVERRIDE" : "AUTO";

  String json;
  serializeJson(doc, json);

  client.publish(AWS_IOT_PUBLISH_TOPIC, json);

  Serial.println("Published to AWS IoT:");
  serializeJsonPretty(doc, Serial);
  Serial.println("\n-----------------------------------\n");
}