#include <DHT.h>

#define DHT_PIN 26
#define DHT_TYPE DHT11
DHT dht(DHT_PIN, DHT_TYPE); 

void setup() {
  // put your setup code here, to run once:
  dht.begin();
  delay(2000);

  Serial.begin(115200);
}

void loop() {
  // put your main code here, to run repeatedly:
  float temp=dht.readTemperature();
  float humid=dht.readHumidity();
  Serial.println("------ SENSOR READINGS ------"); 


  if (isnan(temp) || isnan(humid)) { 

  Serial.println("Temp & Humidity: Error reading from DHT11"); 

  } else { 

  Serial.print("Temp: "); 

  Serial.print(temp); 

  Serial.println(" C"); 

  

  Serial.print("Humidity: "); 

  Serial.print(humid); 

  Serial.println(" %"); 

  delay(2000);
}
}