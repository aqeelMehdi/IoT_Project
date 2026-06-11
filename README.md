# Indoor Air Quality Monitoring System

This project hosts a telemetry pipeline that makes use of AWS Cloud services to implement the 4 layer IoT architecture.

Data ingestion is done from a ESP32-S3 sensor node which detects particulate dust matter (PM 2.5) using PMS5003, temperature and humidity using DHT22, and Carbon Dioxide concentration using MQ135. Raw data and air quality metrics like AQI are computed on the edge.

The data is transmitted over MQTT using WiFi to AWS IoT Core and then forwarded to AWS S3 for storage.

AWS Athena is used to query and fetch the data from S3 buckets and transmit it to Streamlit for visualization.
