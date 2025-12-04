from flask import Flask, request, jsonify

# Flask app instance
app = Flask(__name__)

# Store latest data from ESP32 (Global in-memory storage)
latest_data = {
    "device_id": None, 
    "ip_address": None, 
    "temperature_C": None, 
    "humidity_percent": None, 
    "dew_point_C": None, 
    "heat_index_C": None, 
    "pms_ok": None, 
    "pm1_0_ugm3": None, 
    "pm2_5_ugm3": None, 
    "pm10_ugm3": None, 
    "aqi_index": None, 
    "aqi_category": None, 
    "co2_ppm": None, 
    "timestamp_ms": None
}

# --- 🛰️ ROUTE TO RECEIVE DATA (POST) ---
@app.route('/update', methods=['POST'])
def update():
    global latest_data
    try:
        # 1. Get JSON data from the request body
        data = request.get_json()
        
        if not data:
            return jsonify({"status": "error", "message": "No JSON received"}), 400

        # 2. Update latest_data with the received JSON payload
        latest_data = data 
        
        # Simple logging to confirm data receipt
        print("Received data from ESP32:", latest_data)
        
        return jsonify({"status": "success", "message": "Data updated successfully"}), 200
   
    except Exception as e:
        print("Error receiving data:", e)
        # Log the full exception for debugging
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/data', methods=['GET'])
def data():
    """Returns the current state of the latest_data dictionary."""
    return jsonify(latest_data)

if __name__ == "__main__":
    # Note: Using port 443 (HTTPS) requires valid SSL certificate files 
    # ('cert.pem' and 'key.pem') to be in the same directory.
    # If testing without SSL, remove the ssl_context parameter and use port 80 or 5000.
    
    print("Starting Flask server...")
    
    app.run(
        host='0.0.0.0', 
        port=443, 
        ssl_context=('cert.pem', 'key.pem')
    )