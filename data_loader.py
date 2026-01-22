import streamlit as st
import pandas as pd
from google.oauth2 import service_account
from google.cloud import bigquery
import os

# Create API client.
credentials = service_account.Credentials.from_service_account_info(
    st.secrets["gcp_service_account"]
)
client = bigquery.Client(credentials=credentials)

# Load SQL from file
def load_sql(path: str) -> str:
    if not os.path.exists(path):
        raise FileNotFoundError(f"SQL file '{path}' not found!")
    with open(path, "r") as file:
        return file.read()

# Load your specific queries
maxrxdate_sql = load_sql("sql/maxrxdate.sql")
maxtariffdate_sql = load_sql("sql/maxtariffdate.sql")
icbcostchanges_sql = load_sql("sql/icbcostchanges.sql")
vmpptariffchanges_sql = load_sql("sql/vmpptariffchanges.sql")

# Generic cached query runner
@st.cache_data
def run_query(query):
    query_job = client.query(query)
    rows = query_job.result()
    return [dict(row) for row in rows]

# Cache the latest known max dates from last fetch
@st.cache_data
def get_cached_max_rxdate():
    result = run_query(maxrxdate_sql)
    return result[0]["max_month"]

@st.cache_data
def get_cached_max_tariffdate():
    result = run_query(maxtariffdate_sql)
    return result[0]["max_month"]

# Main data loader that refreshes cache when either date changes
def get_fresh_data_if_needed():
    # Get cached max dates
    cached_max_rx = get_cached_max_rxdate()
    cached_max_tariff = get_cached_max_tariffdate()
    
    # Get current max dates directly from DB (not cached)
    current_max_rx = run_query(maxrxdate_sql)[0]["max_month"]
    current_max_tariff = run_query(maxtariffdate_sql)[0]["max_month"]
    
    # Check if either date has changed
    if current_max_rx != cached_max_rx or current_max_tariff != cached_max_tariff:
        st.cache_data.clear()  # Invalidate all cached data
        
        # Update cached max dates
        get_cached_max_rxdate()
        get_cached_max_tariffdate()
    
    # Fetch data (will use cache if available, fresh if we just cleared)
    icb_data = run_query(icbcostchanges_sql)
    vmpp_data = run_query(vmpptariffchanges_sql)
    
    return icb_data, vmpp_data