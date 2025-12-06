import streamlit as st
import pandas as pd
from pyathena import connect
import altair as alt
import os
from datetime import datetime
from streamlit_autorefresh import st_autorefresh

# --- IMPORTANT: Ensure keys.py exists in the same directory! ---
# keys.py must contain: 
# AWS_ACCESS_KEY = "YOUR_ACCESS_KEY_ID"
# AWS_SECRET_KEY = "YOUR_SECRET_ACCESS_KEY"
from keys import AWS_ACCESS_KEY, AWS_SECRET_KEY

# --- Configuration for AWS Athena Connection ---
AWS_REGION = "eu-north-1" 
S3_STAGING_DIR = "s3://iot-air-quality-group01/node-data/" 
DATABASE_NAME = "iot_air_quality" 
TABLE_NAME = "air_quality_node_data3"      

st_autorefresh(interval=20000, key="data_refresh")

# Define color thresholds for AQI/CO2 alerts
AQI_COLORS = {
    "Good": "green",
    "Moderate": "orange", 
    "Unhealthy": "red",
    "Hazardous": "darkred"
}
CO2_THRESHOLD = 1000 # OSHA standard for poor ventilation


# --- 1. ATHENA CONNECTION AND CACHING ---

@st.cache_resource
def get_athena_connection():
    """Establishes and caches the PyAthena connection."""
    try:
        conn = connect(
            aws_access_key_id=AWS_ACCESS_KEY,
            aws_secret_access_key=AWS_SECRET_KEY,
            s3_staging_dir=S3_STAGING_DIR,
            region_name=AWS_REGION
        )
        return conn
    except Exception as e:
        st.error(f"Failed to connect to Athena: {e}")
        return None

# Latest data: always fetch fresh
def load_latest_data(sql_query):
    conn = get_athena_connection()
    if conn is None:
        return pd.DataFrame()
    
    try:
        df = pd.read_sql(sql_query, conn)
        if not df.empty:
            df['timestamp'] = pd.to_datetime(df['timestamp_ms'], unit='ms')
            for col in ['pm2_5_ugm3', 'co2_ppm', 'temperature_c', 'humidity_percent']:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        return df.sort_values('timestamp', ascending=False)
    except Exception as e:
        st.error(f"Query execution failed: {e}")
        return pd.DataFrame()

# Historical data: cached for speed
cache_time = 20

@st.cache_data(ttl=cache_time)
def load_historical_data(sql_query):
    conn = get_athena_connection()
    if conn is None:
        return pd.DataFrame()
    
    try:
        df = pd.read_sql(sql_query, conn)
        if not df.empty:
            df['timestamp'] = pd.to_datetime(df['timestamp_ms'], unit='ms')
            for col in ['pm2_5_ugm3', 'co2_ppm', 'temperature_c', 'humidity_percent']:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        return df.sort_values('timestamp', ascending=False)
    except Exception as e:
        st.error(f"Query execution failed: {e}")
        return pd.DataFrame()


# --- 2. QUERY DEFINITION ---
def get_data_queries():

    # time_limit_where_clause = """
    #     WHERE 
    #     from_unixtime(timestamp_ms / 1000) >= now() - interval '10' minute
    # """
    # Query for the last 24 hours of data for plotting
    # time_cutoff = int((datetime.now().timestamp() - 86400) * 1000) # 86400 seconds = 24 hours
    
    # Complete list of columns for the LATEST record query
    latest_select_cols = """
        device_id,
        ip_address,
        CAST(temperature_C AS DOUBLE) AS temperature_c,
        CAST(humidity_percent AS DOUBLE) AS humidity_percent,
        CAST(dew_point_C AS DOUBLE) AS dew_point_c,
        CAST(heat_index_C AS DOUBLE) AS heat_index_c,
        pms_ok,
        CAST(pm1_0_ugm3 AS DOUBLE) AS pm1_0_ugm3,
        CAST(pm2_5_ugm3 AS DOUBLE) AS pm2_5_ugm3,
        CAST(pm10_ugm3 AS DOUBLE) AS pm10_ugm3,
        aqi_index,
        aqi_category,
        CAST(co2_ppm AS DOUBLE) AS co2_ppm,
        CAST(timestamp_ms AS BIGINT) AS timestamp_ms,
        CAST(computation_time_ms AS DOUBLE) AS computation_time_ms,
        mode
    """
    
    # Historical query selects only relevant plotting columns
    historical_query = f"""
        SELECT 
            CAST(timestamp_ms AS BIGINT) AS timestamp_ms, 
            CAST(temperature_C AS DOUBLE) AS temperature_c,
            CAST(humidity_percent AS DOUBLE) AS humidity_percent,
            CAST(pm2_5_ugm3 AS DOUBLE) AS pm2_5_ugm3,
            CAST(co2_ppm AS DOUBLE) AS co2_ppm
        FROM 
            {DATABASE_NAME}.{TABLE_NAME}
        ORDER BY timestamp_ms DESC LIMIT 100
    """
    
    latest_query = f"""
        SELECT {latest_select_cols}
        FROM {DATABASE_NAME}.{TABLE_NAME} 
        ORDER BY timestamp_ms DESC LIMIT 10
    """
    #20 most recent entries
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
df_latest = load_latest_data(latest_query)
df_history = load_historical_data(historical_query)

# Handle missing latest data
if df_latest.empty:
    st.info("Waiting for data from AWS Athena. Please check your AWS credentials and Glue Table setup.")
    st.stop()


# Get latest values for KPIs
latest_row = df_latest.iloc[0]

# Extracting values safely
current_aqi = latest_row.get('aqi_index', 'N/A')
aqi_cat = latest_row.get('aqi_category', 'N/A')
current_temp = latest_row.get('temperature_c', 0.0)
current_co2 = latest_row.get('co2_ppm', 0.0)
latest_time = latest_row.get('timestamp', datetime.now())
heat_index = latest_row.get('heat_index_c', 0.0)
dew_point = latest_row.get('dew_point_c', 0.0)


# --- Row 1: KPI Cards (Air Quality, Comfort, Status) ---
st.subheader("Key Environmental Metrics")
# Use 5 columns for more density
cols_kpi = st.columns([1, 1, 1, 1, 1], gap="small") 

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
    help="Current Ambient Temperature"
)

# 3. Humidity
cols_kpi[2].metric(
    "Humidity (%)",
    f"{latest_row['humidity_percent']:.1f} %",
    help="Current Relative Humidity"
)

# 4. Comfort Metrics (Dew Point / Heat Index)
cols_kpi[3].metric(
    "Heat Index (°C)",
    f"{heat_index:.1f} °C",
    delta=f"{dew_point:.1f} °C (Dew Point)",
    delta_color="off",
    help="Heat Index reflects how hot it feels; Dew Point reflects atmospheric moisture."
)

# 5. Node Latency and Mode
cols_kpi[4].metric(
    f"Mode: {latest_row['mode']}",
    f"{latest_row.get('computation_time_ms', 0.0):.2f} ms",
    help="Time taken by the sensor node to process data."
)

st.divider()


# --- Row 2: Actuator Status & CO2 Threshold Alert ---
st.subheader("Actuator & System Status")
cols_actuator = st.columns([1, 1, 2], gap="medium")

# 1. Actuator State
with cols_actuator[0].container(border=True):
    st.markdown("#### Actuator State")
    
    # buzzer_icon = "🚨" if buzzer_state == 1 else "🔇"
    
    # st.markdown(f"**Buzzer:** {buzzer_icon} {'ON' if buzzer_state == 1 else 'OFF'}")
    st.markdown(f"**PMS Sensor:** **{'OK' if latest_row['pms_ok'] else 'ERROR ❌'}**")


# 2. CO2 Gauge and Alert Status
with cols_actuator[1].container(border=True):
    st.markdown("#### CO2 Threshold Alert")

    # Display progress against a maximum of 2000 ppm
    progress_val = min(current_co2 / 2000, 1.0)
    st.progress(progress_val, text=f"CO2 Level: **{current_co2:.0f} PPM**")
    
    if current_co2 > CO2_THRESHOLD:
        st.error(f"⚠️ DANGER: CO2 exceeds set threshold ({CO2_THRESHOLD} PPM).")
    elif current_co2 > 800:
        st.warning("⚠️ High CO2: Consider ventilation.")
    else:
        st.success("✅ CO2 levels are healthy.")


# 3. Device Info and Raw PM Data
with cols_actuator[2].container(border=True):
    st.markdown("#### Device Network & PM Breakdown")
    st.markdown(f"**Device ID:** `{latest_row['device_id']}` | **IP:** `{latest_row['ip_address']}`")
    st.markdown("---")
    
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
    st.altair_chart(pm_chart, width='stretch')


# --- Row 3: Historical Charts ---
st.subheader("24-Hour Historical Trends")
cols_charts = st.columns(2, gap="medium")

# Prepare historical data for plotting
if not df_history.empty:
    
    # CHART 1: PM2.5 and Temperature Overlay
    with cols_charts[0].container(border=True):
        st.markdown("#### PM2.5 and Temperature Trend")
        
        base = alt.Chart(df_history).encode(
            alt.X('timestamp', title='Time (24 Hours)', axis=alt.Axis(format="%H:%M"))
        ).properties(
            height=300
        ).interactive()

        # Layer 1: PM2.5 (Primary Y-axis)
        line_pm25 = base.mark_line(color='#1f77b4').encode(
            alt.Y('pm2_5_ugm3', title='PM2.5 (μg/m³)', axis=alt.Axis(titleColor='#1f77b4')),
            tooltip=[alt.Tooltip('timestamp', format="%H:%M"), 'pm2_5_ugm3']
        )

        # Layer 2: Temperature (Secondary Y-axis)
        line_temp = base.mark_line(color='#ff7f0e').encode(
            alt.Y('temperature_c', title='Temperature (°C)', axis=alt.Axis(titleColor='#ff7f0e')),
            tooltip=[alt.Tooltip('timestamp', format="%H:%M"), 'temperature_c']
        )
        
        st.altair_chart(alt.layer(line_pm25, line_temp).resolve_scale(y='independent'), use_container_width=True)

    # CHART 2: CO2 Concentration (PPM)
    with cols_charts[1].container(border=True):
        st.markdown("#### CO2 Concentration (PPM)")

        co2_chart = alt.Chart(df_history).mark_line(point=True, color='#2ca02c').encode(
            x=alt.X('timestamp', title='Time (24 Hours)', axis=alt.Axis(format="%H:%M")),
            y=alt.Y('co2_ppm', title='CO2 (PPM)', scale=alt.Scale(zero=False)),
            tooltip=['timestamp', 'co2_ppm']
        ).properties(
            height=300
        )
        # Add a horizontal rule for the unhealthy threshold (1000 ppm)
        co2_chart += alt.Chart(pd.DataFrame({'y': [CO2_THRESHOLD]})).mark_rule(color='red', strokeDash=[5, 5]).encode(y='y')

        st.altair_chart(co2_chart, use_container_width=True)

# --- Row 4: Raw Data & Refresh ---
st.subheader("Data Inspector")
cols_raw = st.columns([3, 1])

with cols_raw[0].container(border=True):
    st.markdown("#### Last 10 Raw Records")
    # Display the top 10 historical records
    # Drop timestamp_ms as 'timestamp' is the clean datetime object
    columns_to_show = [
        'dew_point_c',
        'pm1_0_ugm3',
        'pm2_5_ugm3',
        'pm10_ugm3',
        'co2_ppm'
    ]

    # Only return columns that actually exist in df_latest
    columns_to_show = [c for c in columns_to_show if c in df_latest.columns]

    st.dataframe(df_latest[columns_to_show].tail(10), use_container_width=True)

with cols_raw[1].container(border=True):
    st.markdown("#### Refresh Data")
    st.markdown(f"Data is auto-cached for {cache_time} seconds.")
    # Add a simple button to manually clear the cache and re-run the query
    if st.button("Force Refresh", width='stretch'):
        st.cache_data.clear()
        st.rerun()