import streamlit as st
import pandas as pd
from pyathena import connect
import os # Used for reading secrets

from keys import AWS_ACCESS_KEY, AWS_SECRET_KEY 

# 1. Configuration (Read from environment variables or Streamlit secrets)
AWS_REGION = os.environ.get("AWS_REGION", "eu-north-1") # Your AWS Region
S3_STAGING_DIR = os.environ.get("S3_STAGING_DIR", "s3://iot-air-quality-group01/esp32/esp32-to-aws/") 
DATABASE_NAME = "iot_air_quality" # The Glue database name

# 2. Connection Function (Cached Resource)
# Use st.cache_resource to cache the connection object itself
@st.cache_resource
def get_athena_connection():
    """Establishes and caches the PyAthena connection with explicit credentials."""
    conn = connect(
        aws_access_key_id=AWS_ACCESS_KEY,       # <-- Pass directly
        aws_secret_access_key=AWS_SECRET_KEY,   # <-- Pass directly
        s3_staging_dir=S3_STAGING_DIR,
        region_name=AWS_REGION
    )
    return conn

# 3. Data Query Function (Cached Data)
# Use st.cache_data to cache the results of the query for 1 minute (ttl=60)
@st.cache_data(ttl=60) 
def load_iot_data(sql_query):
    """Executes a SQL query on Athena and returns a Pandas DataFrame."""
    conn = get_athena_connection()
    df = pd.read_sql(sql_query, conn)
    return df

# 4. Streamlit Dashboard Layout
st.title("⚡ IoT Core Real-Time Dashboard")

# Example query to fetch sensor readings
query = f"""
    SELECT
        *
    FROM
        {DATABASE_NAME}.air_quality_iot_raw
"""

# Fetch data and handle potential errors
try:
    data_df = load_iot_data(query)

    st.subheader("Latest Sensor Readings")
    st.dataframe(data_df)

    # Simple line chart for temperature over time
    st.subheader("Temperature Trend")
    st.line_chart(data_df, x='temperature', y='temperature')
    
except Exception as e:
    st.error(f"Could not retrieve data from Athena. Check IAM permissions and S3 path. Error: {e}")

# Add a simple button to manually clear the cache and re-run the query
if st.button("Refresh Data (Rerun Athena Query)"):
    st.cache_data.clear()
    st.rerun()