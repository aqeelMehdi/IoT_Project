import streamlit as st
import pandas as pd
from pyathena import connect
import altair as alt
import os
from datetime import datetime

from keys import AWS_ACCESS_KEY, AWS_SECRET_KEY

# --- Configuration for AWS Athena Connection ---
# REMINDER: For this to work locally, you must set these variables as environment 
# variables in your PowerShell/CMD window, or pass your credentials via AWS CLI config.
AWS_REGION = "eu-north-1"  # Replace with your AWS Region
S3_STAGING_DIR = "s3://iot-air-quality-group01/node-data/"  # Replace with your S3 path
DATABASE_NAME = "iot_air_quality"  # Replace with your Glue database name
TABLE_NAME = "air_quality_node_data"      # Replace with your Glue table name

# Define color thresholds for AQI/CO2 alerts
AQI_COLORS = {
    "Good": "green",
    "Moderate": "yellow",
    "Unhealthy": "red",
    "Hazardous": "darkred"
}
CO2_THRESHOLD = 1000 # OSHA standard for poor ventilation

# --- 1. ATHENA CONNECTION AND CACHING ---

# Use st.cache_resource to cache the connection object itself
@st.cache_resource
def get_athena_connection():
    """Establishes and caches the PyAthena connection."""
    # PyAthena will automatically look for AWS credentials (ACCESS_KEY/SECRET_KEY)
    # in environment variables or the local AWS config file.
    try:
        conn = connect(
            aws_access_key_id=AWS_ACCESS_KEY,       # <-- Pass directly
            aws_secret_access_key=AWS_SECRET_KEY,   # <-- Pass directly
            s3_staging_dir=S3_STAGING_DIR,
            region_name=AWS_REGION
        )
        return conn
    except Exception as e:
        st.error(f"Failed to connect to Athena. Check local AWS credentials and S3 staging path. Error: {e}")
        return None

# Use st.cache_data to cache the query results for 60 seconds (1 minute refresh rate)
@st.cache_data(ttl=60) 
def load_iot_data(sql_query):
    """Executes a SQL query on Athena and returns a Pandas DataFrame."""
    conn = get_athena_connection()
    if conn is None:
        return pd.DataFrame() # Return empty DataFrame on connection failure
        
    try:
        # Use pandas to read data directly from the SQL query
        df = pd.read_sql(sql_query, conn)
        
        # Clean up and type conversions:
        if not df.empty:
            # Convert timestamp_ms to datetime (assuming it's a Unix timestamp in milliseconds)
            # You might need to adjust this conversion based on your IoT node format
            df['timestamp_ms'] = pd.to_datetime(df['timestamp_ms'], unit='ms')
            
            # Ensure PM and CO2 are numerical, coercing errors to NaN
            for col in ['pm2_5_ugm3', 'co2_ppm', 'temperature_c']:
                df[col] = pd.to_numeric(df[col], errors='coerce')
                
        return df.sort_values('timestamp_ms', ascending=False)
        
    except Exception as e:
        st.error(f"Query Execution Failed in Streamlit: {e}")
        # Print the full error to the terminal for debugging PyAthena/IAM issues
        print(f"ATHENA QUERY ERROR: {e}")
        return pd.DataFrame()

# --- 2. QUERY DEFINITION ---
def get_data_queries():
    # Query for the last 24 hours of data for plotting
    time_cutoff = int((datetime.now().timestamp() - 86400) * 1000) # 86400 seconds = 24 hours
    
    # We select all key metrics and filter by a time window
    historical_query = f"""
        SELECT 
            CAST(timestamp_ms AS BIGINT) AS timestamp_ms, 
            CAST(temperature_C AS DOUBLE) AS temperature_C,
            CAST(humidity_percent AS DOUBLE) AS humidity_percent,
            CAST(pm2_5_ugm3 AS DOUBLE) AS pm2_5_ugm3,
            CAST(co2_ppm AS BIGINT) AS co2_ppm,
            aqi_index,
            aqi_category
        FROM 
            {DATABASE_NAME}.{TABLE_NAME}
        WHERE 
            CAST(timestamp_ms AS BIGINT) > {time_cutoff}
        ORDER BY 
            timestamp_ms DESC
    """
    
    # Query for the single latest record
    latest_query = f"SELECT * FROM {DATABASE_NAME}.{TABLE_NAME} ORDER BY timestamp_ms DESC LIMIT 1"
    
    return latest_query, historical_query

# --- 3. STREAMLIT LAYOUT ---

st.set_page_config(
    page_title="IoT Environmental Monitoring",
    page_icon="🏠",
    layout="wide",
)

st.title("🏡 Indoor Air Quality (IAQ) Dashboard")

# Get data
latest_query, historical_query = get_data_queries()
df_latest = load_iot_data(latest_query)
df_history = load_iot_data(historical_query)

# Handle cases where data fetching failed
if df_latest.empty and df_history.empty:
    st.info("Waiting for data from AWS Athena. Please check your AWS credentials and Glue Table setup.")
    # Add a refresh button to allow re-running the cache 
    if st.button("Attempt Manual Refresh"):
        st.cache_data.clear()
        st.rerun()
    st.stop()


# Get latest values for KPIs
latest_row = df_latest.iloc[0]
current_aqi = latest_row['aqi_index'] if 'aqi_index' in latest_row else 'N/A'
aqi_cat = latest_row['aqi_category'] if 'aqi_category' in latest_row else 'N/A'
current_temp = latest_row['temperature_C'] if 'temperature_C' in latest_row else 0
current_co2 = latest_row['co2_ppm'] if 'co2_ppm' in latest_row else 0
latest_time = latest_row['timestamp_ms'] if 'timestamp_ms' in latest_row else datetime.now()

# --- Row 1: KPI Cards ---
st.subheader("Key Status Metrics")
cols_kpi = st.columns(4, gap="medium")

# 1. AQI Index (Colored Gauge)
aqi_color = AQI_COLORS.get(aqi_cat, "blue")
cols_kpi[0].markdown(
    f"""
    <div style="text-align: center; border: 2px solid {aqi_color}; padding: 10px; border-radius: 10px; background-color: #f0f2f6;">
        <p style="font-size: 14px; color: #555;">AQI Index (Latest)</p>
        <h1 style="color: {aqi_color}; margin: 0; font-size: 3em;">{current_aqi}</h1>
        <p style="font-size: 18px; color: {aqi_color}; margin: 0;">{aqi_cat.upper()}</p>
    </div>
    """,
    unsafe_allow_html=True
)

# 2. Temperature
cols_kpi[1].metric(
    "Temperature (°C)",
    f"{current_temp:.1f} °C",
    delta=f"{latest_row['heat_index_c']:.1f} °C (Heat Index)",
    delta_color="off" # Turning off delta color for Heat Index as it's a comparison
)

# 3. Humidity
cols_kpi[2].metric(
    "Humidity",
    f"{latest_row['humidity_percent']:.1f} %",
    delta=f"{latest_row['dew_point_c']:.1f} °C (Dew Point)",
    delta_color="off"
)

# 4. CO2 PPM (Use progress bar for quick visualization of threshold)
co2_bar_color = "red" if current_co2 > CO2_THRESHOLD else "green"
co2_status_icon = "⚠️" if current_co2 > CO2_THRESHOLD else "✅"

cols_kpi[3].markdown(f"**CO2 Level (PPM)** {co2_status_icon}", unsafe_allow_html=True)
cols_kpi[3].metric(
    "", # No label needed here
    f"{current_co2} PPM",
    delta_color="off"
)
# Display progress against a max (e.g., 2000 ppm)
cols_kpi[3].progress(min(current_co2 / 2000, 1.0), text=f"Limit: {CO2_THRESHOLD} PPM")


# --- Row 2: Charts for Time-Series Data ---
st.subheader("24-Hour Trend Analysis")

cols_charts = st.columns(2, gap="medium")

with cols_charts[0].container(border=True):
    st.markdown("#### PM2.5 Concentration (μg/m³)")
    
    # Altair chart for PM2.5 over time
    pm25_chart = alt.Chart(df_history).mark_line(point=True).encode(
        x=alt.X('timestamp_ms', title='Time', axis=alt.Axis(format="%H:%M")),
        y=alt.Y('pm2_5_ugm3', title='PM2.5 (μg/m³)', scale=alt.Scale(zero=False)),
        tooltip=['timestamp_ms', 'pm2_5_ugm3']
    ).properties(
        height=300
    ).interactive() # Enable zoom and pan

    st.altair_chart(pm25_chart, use_container_width=True)

with cols_charts[1].container(border=True):
    st.markdown("#### CO2 Concentration (PPM)")

    # Altair chart for CO2 over time
    co2_chart = alt.Chart(df_history).mark_line(point=True, color='orange').encode(
        x=alt.X('timestamp_ms', title='Time', axis=alt.Axis(format="%H:%M")),
        y=alt.Y('co2_ppm', title='CO2 (PPM)', scale=alt.Scale(zero=False)),
        tooltip=['timestamp_ms', 'co2_ppm']
    ).properties(
        height=300
    )
    # Add a horizontal rule for the unhealthy threshold (1000 ppm)
    co2_chart += alt.Chart(pd.DataFrame({'y': [CO2_THRESHOLD]})).mark_rule(color='red').encode(y='y')

    st.altair_chart(co2_chart, use_container_width=True)


# --- Row 3: Utility and Device Info ---
st.subheader("Device and System Status")
cols_utility = st.columns([1, 1, 2], gap="medium")

with cols_utility[0].container(border=True):
    st.markdown("#### Device Info")
    st.json({
        "ID": latest_row['device_id'],
        "IP": latest_row['ip_address'],
        "PMS Status": "OK" if (latest_row['pms_ok'] == "true") else "Error"
    })
    st.markdown(f"Last updated: **{latest_time.strftime('%Y-%m-%d %H:%M:%S')}**")

with cols_utility[1].container(border=True):
    st.markdown("#### Particle Breakdown (Latest)")
    # Prepare data for PM bar chart comparison
    pm_data = pd.DataFrame({
        'Particle': ['PM1.0', 'PM2.5', 'PM10'],
        'Concentration': [latest_row['pm1_0_ugm3'], latest_row['pm2_5_ugm3'], latest_row['pm10_ugm3']]
    })
    
    pm_chart = alt.Chart(pm_data).mark_bar().encode(
        x=alt.X('Particle', title=None),
        y=alt.Y('Concentration', title='μg/m³'),
        color=alt.Color('Particle')
    ).properties(
        height=180
    )
    st.altair_chart(pm_chart, use_container_width=True)
    
with cols_utility[2].container(border=True):
    st.markdown("#### Raw Data Inspector")
    st.dataframe(df_history.head(10), use_container_width=True)