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

#define PUBLISH_INTERVAL_MS (4000UL) // 4 seconds
#define DHT_MIN_INTERVAL_MS (2200UL) // DHT11 needs ~2s between reads

#define AWS_IOT_PORT 8883
#define AWS_IOT_PUBLISH_TOPIC "esp32/esp32-to-aws"

// ========================== SENSOR OBJECTS ==========================
DHT dht(DHT_PIN, DHT_TYPE);
HardwareSerial pmsSerial(2);
MQ135 gasSensor(MQ135_PIN, 10.0, 76.6); // Adjust RZERO after calibration if needed.

// PMS5003 data structure
struct pms5003data {
  uint16_t framelen;
  uint16_t pm10_standard, pm25_standard, pm100_standard;
  uint16_t pm10_env, pm25_env, pm100_env;
  uint16_t particles_03um, particles_05um, particles_10um, particles_25um, particles_50um, particles_100um;
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

// ========================== DECLARATIONS ==========================
void ensureWiFi();
void ensureAWS();
bool readPMSdata(Stream *s, pms5003data &out);
void sendToAWS();
float dewPoint(float tempC, float humidity);
float computeHeatIndex(float tempC, float humidity);
int computeAQI_PM25_US(float pm25);
String getAQICategory(int aqi);

// ========================== SETUP ==========================
void setup() {
  Serial.begin(115200);
  delay(1000);
  Serial.println("\nStarting ESP32 AWS IoT Environmental Node...");

  dht.begin();
  pmsSerial.begin(9600, SERIAL_8N1, PMS_RX, PMS_TX);

  ensureWiFi();
  ensureAWS();

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
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  unsigned long startAttempt = millis();
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
    if (millis() - startAttempt > 20000UL) {
      Serial.println("\nWiFi connect timeout, retrying...");
      WiFi.disconnect();
      WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
      startAttempt = millis();
    }
  }
  Serial.println("\nWiFi Connected!");
  Serial.print("IP Address: ");
  Serial.println(WiFi.localIP());
}

// ========================== AWS CONNECTION ==========================
void ensureAWS() {
  Serial.print("Connecting to AWS IoT Core");

  net.setCACert(AWS_CERT_CA);
  net.setCertificate(AWS_CERT_CRT);
  net.setPrivateKey(AWS_CERT_PRIVATE);

  client.begin(AWS_IOT_ENDPOINT, AWS_IOT_PORT, net);

  uint8_t attempts = 0;
  while (!client.connect(THINGNAME)) {
    Serial.print(".");
    delay(750);
    if (++attempts >= 30) {
      Serial.println("\nAWS IoT connection failed, will retry later.");
      return;
    }
  }
  Serial.println("\nConnected to AWS IoT Core!");
}

// ========================== PMS READER ==========================
bool readPMSdata(Stream *s, pms5003data &out) {
  if (!s->available()) return false;

  while (s->available() >= 32) {
    if (s->peek() != 0x42) { s->read(); continue; }
    if (s->available() < 2) return false;
    uint8_t h = s->read();
    if (s->peek() != 0x4D) continue;
    uint8_t m = s->read();

    uint8_t buffer[30];
    int readN = s->readBytes((char*)buffer, sizeof(buffer));
    if (readN != 30) return false;

    uint16_t sum = (uint16_t)h + (uint16_t)m;
    for (uint8_t i = 0; i < 28; i++) sum += buffer[i];

    uint16_t frame_u16[15];
    for (uint8_t i = 0; i < 15; i++) {
      frame_u16[i] = ((uint16_t)buffer[2 + i * 2] << 8);
      frame_u16[i] |= (uint16_t)buffer[2 + i * 2 + 1];
    }
    memcpy((void*)&out, (void*)frame_u16, 30);

    if (sum == out.checksum) return true;
  }
  return false;
}

// ========================== MATH HELPERS ==========================
float dewPoint(float tempC, float humidity) {
  return tempC - ((100.0f - humidity) / 5.0f);
}

float computeHeatIndex(float tempC, float humidity) {
  float T = (tempC * 9.0f / 5.0f) + 32.0f;
  float R = humidity;
  float hiF = -42.379f + 2.04901523f * T + 10.14333127f * R
             - 0.22475541f * T * R - 6.83783e-3f * T * T
             - 5.481717e-2f * R * R
             + 1.22874e-3f * T * T * R
             + 8.5282e-4f * T * R * R
             - 1.99e-6f * T * T * R * R;
  return (hiF - 32.0f) * 5.0f / 9.0f;
}

int computeAQI_PM25_US(float C) {
  struct Bp { float Clow, Chigh; int Ilow, Ihigh; };
  const Bp bp[] = {
    { 0.0f, 12.0f, 0, 50 },
    { 12.1f, 35.4f, 51, 100 },
    { 35.5f, 55.4f, 101, 150 },
    { 55.5f, 150.4f, 151, 200 },
    { 150.5f, 250.4f, 201, 300 },
    { 250.5f, 350.4f, 301, 400 },
    { 350.5f, 500.4f, 401, 500 }
  };
  for (auto &r : bp) {
    if (C <= r.Chigh)
      return (int)roundf(((r.Ihigh - r.Ilow) * (C - r.Clow) / (r.Chigh - r.Clow)) + r.Ilow);
  }
  return 500;
}

String getAQICategory(int aqi) {
  if (aqi <= 50) return "Good";
  else if (aqi <= 100) return "Moderate";
  else if (aqi <= 150) return "Unhealthy for Sensitive Groups";
  else if (aqi <= 200) return "Unhealthy";
  else if (aqi <= 300) return "Very Unhealthy";
  else return "Hazardous";
}

// ========================== PUBLISH ==========================
void sendToAWS() {
  const unsigned long start_us = micros();

  const unsigned long now = millis();
  if (now - lastDhtReadTime >= DHT_MIN_INTERVAL_MS || isnan(lastTempC) || isnan(lastHumid)) {
    lastTempC = dht.readTemperature();
    lastHumid = dht.readHumidity();
    lastDhtReadTime = now;
  }

  bool pmsSuccess = readPMSdata(&pmsSerial, data);
  float co2_ppm = gasSensor.getPPM();

  if (isnan(lastTempC) || isnan(lastHumid)) {
    Serial.println("DHT11 Error - skipping publish.");
    return;
  }

  float heatIndexC = computeHeatIndex(lastTempC, lastHumid);
  float dewPt = dewPoint(lastTempC, lastHumid);
  uint16_t pm25 = pmsSuccess ? data.pm25_standard : 0;
  int aqi = computeAQI_PM25_US(pm25);
  String aqiCat = getAQICategory(aqi);

  unsigned long elapsed_us = micros() - start_us;
  double elapsed_ms = (double)elapsed_us / 1000.0;

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

  String payload;
  serializeJson(doc, payload);

  bool ok = client.publish(AWS_IOT_PUBLISH_TOPIC, payload);

  Serial.println(ok ? "Published to AWS IoT:" : "Publish FAILED!");
  serializeJsonPretty(doc, Serial);
  Serial.print("\nPayload bytes: ");
  Serial.println(payload.length());
  Serial.println("-----------------------------------\n");
}
