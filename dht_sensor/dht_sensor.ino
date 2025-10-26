#include <ArduinoJson.h>
#include <ArduinoJson.hpp>


#include <WiFi.h>
#include <DHT.h>

// ----------- PMS5003 Setup -----------
HardwareSerial pmsSerial(2); // UART2

struct pms5003data {
  uint16_t framelen;
  uint16_t pm10_standard, pm25_standard, pm100_standard;
  uint16_t pm10_env, pm25_env, pm100_env;
  uint16_t particles_03um, particles_05um, particles_10um, particles_25um, particles_50um, particles_100um;
  uint16_t unused;
  uint16_t checksum;
};
pms5003data data;

// ----------- DHT11 Setup -------------
#define DHT_PIN 26
#define DHT_TYPE DHT11
DHT dht(DHT_PIN, DHT_TYPE);

// ----------- WiFi Setup --------------
const char* ssid = "____"; //wifi network name
const char* password = "____"; //wifi password

// ----------- Setup -------------------
void setup() {
  Serial.begin(115200);
  delay(1000);
  
  Serial.println("\n--- ESP32 IoT Node Booting ---");

  // DHT & PMS5003 init
  dht.begin();
  pmsSerial.begin(9600, SERIAL_8N1, 16, 17);

  // WiFi connection
  connectWiFi();

  Serial.println("Setup complete. Starting loop...\n");
}

// ----------- Loop -------------------
void loop() {
  unsigned long startTime = millis();

  // Read sensors
  float temp = dht.readTemperature();
  float humid = dht.readHumidity();
  bool pmsSuccess = readPMSdata(&pmsSerial);

  float heatIndexC = computeHeatIndex(temp, humid);
  int aqi = computeAQI(data.pm25_standard);

  unsigned long computation_time = millis() - startTime;

  if (isnan(temp) || isnan(humid)) {
    Serial.println("⚠️ DHT11 Error: Cannot read temperature/humidity.");
    delay(2000);
    return;
  }

  if (!pmsSuccess) {
    Serial.println("⚠️ PMS5003 Error: No valid data.");
    delay(2000);
    return;
  }

  // ----------- Build JSON -----------
  StaticJsonDocument<512> doc;
  doc["device_id"] = "esp32_node_01";
  doc["ip_address"] = WiFi.localIP().toString();
  doc["temperature_C"] = temp;
  doc["humidity_percent"] = humid;
  doc["pm1_0_ugm3"] = data.pm10_standard;
  doc["pm2_5_ugm3"] = data.pm25_standard;
  doc["pm10_ugm3"] = data.pm100_standard;
  doc["dew_point_C"] = dewPoint(temp, humid);
  doc["heat_index_C"] = heatIndexC;
  doc["aqi_index"] = aqi;
  doc["timestamp_ms"] = millis();
  doc["computation_time_ms"] = computation_time;

  // Create a temporary string to compute payload size
  String payload;
  serializeJson(doc, payload);
  size_t payload_size = payload.length();
  doc["payload_size_bytes"] = payload_size;

  // Print nicely formatted JSON
  serializeJsonPretty(doc, Serial);
  Serial.println();
  Serial.println("----------------------------\n");

  delay(3000);
}

// ----------- WiFi Connection -----------
void connectWiFi() {
  Serial.print("Connecting to WiFi ");
  Serial.print(ssid);
  Serial.println(" ...");
  WiFi.begin(ssid, password);

  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }

  Serial.println("\n✅ WiFi Connected!");
  Serial.print("IP Address: ");
  Serial.println(WiFi.localIP());
}

// ----------- PMS5003 Read Function -----------
bool readPMSdata(Stream *s) {
  if (!s->available()) return false;
  if (s->peek() != 0x42) {
    s->read();
    return false;
  }

  if (s->available() < 32) return false;

  uint8_t buffer[32];
  s->readBytes(buffer, 32);

  uint16_t sum = 0;
  for (uint8_t i = 0; i < 30; i++) sum += buffer[i];

  uint16_t buffer_u16[15];
  for (uint8_t i = 0; i < 15; i++) {
    buffer_u16[i] = buffer[2 + i * 2 + 1];
    buffer_u16[i] += (buffer[2 + i * 2] << 8);
  }

  memcpy((void *)&data, (void *)buffer_u16, 30);

  if (sum != data.checksum) {
    Serial.println("Checksum failure");
    return false;
  }

  return true;
}

float dewPoint(float temp, float humidity) {
  return temp - ((100 - humidity) / 5);
}

float computeHeatIndex(float tempC, float humidity) {
  // Convert Celsius to Fahrenheit for calculation
  float tempF = (tempC * 9.0 / 5.0) + 32.0;

  // NOAA formula for heat index
  float hiF = -42.379 + 2.04901523 * tempF + 10.14333127 * humidity
              - 0.22475541 * tempF * humidity - 6.83783e-3 * tempF * tempF
              - 5.481717e-2 * humidity * humidity
              + 1.22874e-3 * tempF * tempF * humidity
              + 8.5282e-4 * tempF * humidity * humidity
              - 1.99e-6 * tempF * tempF * humidity * humidity;

  // Convert back to Celsius
  float hiC = (hiF - 32.0) * 5.0 / 9.0;
  return hiC;
}

int computeAQI(float pm25) {
  struct AQIRange { float Clow, Chigh; int Ilow, Ihigh; };
  const AQIRange ranges[] = {
    {0.0, 9.0, 0, 50},
    {9.1, 35.4, 51, 100},
    {35.5, 55.4, 101, 150},
    {55.5, 125.4, 151, 200},
    {125.5, 225.4, 201, 300},
    {225.5, 500.4, 301, 500}
  };

  for (auto &r : ranges) {
    if (pm25 <= r.Chigh) {
      return (r.Ihigh - r.Ilow) * (pm25 - r.Clow) / (r.Chigh - r.Clow) + r.Ilow;
    }
  }
  return 500; // max cap
}

