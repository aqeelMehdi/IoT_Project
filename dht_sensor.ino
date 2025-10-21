#include <DHT.h>


DHT dht(26, DHT11);
void setup() {
  // put your setup code here, to run once:
  dht.begin
  delay(2000)

  Serial.begin(115200)
}

void loop() {
  // put your main code here, to run repeatedly:
  float temp=dht.readTemperature();
  float humid=dht.readHumidity();
  Serial.print("Temp: ");
  Serial.print(temp);
  Serial.print(" C ");
  Serial.print("Humidity: ");
  Serial.print(humid);
  Serial.print(" % ");
  delay(2000);
}