import streamlit as st
import pandas as pd
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode, JsCode
from datetime import datetime

from db import get_duckdb_connection, get_latest_dates, _bq_client, _latest_bq_month

import logging
logging.basicConfig(level=logging.INFO)

# Set wide layout
st.set_page_config(layout="wide")

st.image("OpenPrescribing.svg")

st.info(
    """##### Hello!  This is a **very** early prototype of estimating the impact of drug tariff changes.  
Please let us know what you think, and what you'd like to see.  Email us at [bennett@phc.ox.ac.uk](mailto:bennett@phc.ox.ac.uk)"""
)

st.title("Drug Tariff price change estimator")

from db import _bq_client, _latest_bq_month, get_duckdb_connection

if st.button("Test DuckDB connection"):
    try:
        conn = get_duckdb_connection()
        tables = [r[0] for r in conn.execute("SHOW TABLES").fetchall()]
        st.success(f"DuckDB connected, tables: {tables}")
    except Exception as e:
        st.error(f"DuckDB connection failed: {e}")



if st.button("Test table data"):
    conn = get_duckdb_connection()
    st.subheader("Prescribing")
    st.dataframe(conn.execute("SELECT * FROM prescribing LIMIT 5").df())
    st.subheader("Tariff price changes")
    st.dataframe(conn.execute("SELECT * FROM tariff_price_changes LIMIT 5").df())
    st.subheader("VMPP changes")
    st.dataframe(conn.execute("SELECT * FROM vmpp_tariff_changes LIMIT 5").df())


from db import _gcs_client, GCS_DB_PATH, BUCKET_NAME

if st.button("Force rebuild"):
    client = _gcs_client()
    bucket = client.bucket(BUCKET_NAME)
    bucket.blob(GCS_DB_PATH).delete()
    st.cache_resource.clear()
    st.success("Cache cleared, reload the app to rebuild")




conn = get_duckdb_connection()

icb_df = conn.execute("""
    SELECT
        rx.icb_name,
        rx.bnf_name,
        rx.bnf_code,
        dt.tariff_cat,
        SUM(rx.quantity * dt.price_diff_pu * dt.is_max_price_diff_pu) AS price_difference
    FROM prescribing AS rx
    INNER JOIN tariff_price_changes AS dt
    ON rx.bnf_code = dt.bnf_code
    GROUP BY rx.icb_name, rx.bnf_name, rx.bnf_code, dt.tariff_cat
    """).df()


vmpp_df = conn.execute("""
    SELECT * FROM vmpp_tariff_changes
    """).df()


# Load data from SQL queries
#icb_data, vmpp_data = data_loader.get_fresh_data_if_needed()
#icb_df = pd.DataFrame(icb_data)
#vmpp_df = pd.DataFrame(vmpp_data)

# Get latest dates

#max_rx_date = pd.to_datetime(raw_max_rx_date, errors="coerce").strftime("%B %Y")
#max_rx_date = conn.execute("SELECT MAX(month) FROM prescribing").fetchone()[0]


dates = get_latest_dates()
max_rx_date = dates["prescribing"]
max_tariff_date  = dates["tariff"]
#raw_max_tariff_date = data_loader.get_cached_max_tariffdate()
#max_tariff_date = pd.to_datetime(raw_max_tariff_date, errors="coerce").strftime("%B %Y")
#max_tariff = conn.execute("SELECT MAX(date) FROM tariff_price_changes").fetchone()[0]

# calculate number of changes to vmpp

price = pd.to_numeric(vmpp_df["price_pence"], errors="coerce")
prev = pd.to_numeric(vmpp_df["previous_price_pence"], errors="coerce")

num_increased = (price > prev).sum()
num_decreased = (price < prev).sum()
num_unchanged = (price == prev).sum()



# GBP formatter (Python side)

def gbp(x):
    if pd.isna(x):
        return ""
    x = float(x)
    sign = "-" if x < 0 else ""
    return f"{sign}£{abs(x):,.0f}"

def gbp2f(x):
    if pd.isna(x):
        return ""
    x = float(x)
    sign = "-" if x < 0 else ""
    return f"{sign}£{abs(x):,.2f}"




# Top filter by ICB


with st.sidebar:
    st.markdown(f"### Drug Tariff month: {datetime.strptime(max_tariff_date, '%Y-%m-%d').strftime('%B %Y')}")
    st.markdown(f"### Prescribing data used for estimate: {datetime.strptime(max_rx_date, '%Y-%m-%d').strftime('%B %Y')}")

    # ICB Filter
    names = ["(All)"] + sorted(icb_df["icb_name"].dropna().unique().tolist())
    st.markdown("### Select Integrated Care Board")
    selected_name = st.selectbox("Select Integrated Care Board", names, label_visibility="collapsed")
    # Tariff Category Filter
    tariff_cats = ["(All)"] + sorted(icb_df["tariff_cat"].dropna().unique().tolist())
    st.markdown("### Select Tariff Category")
    selected_tariff_cat = st.selectbox("Select Tariff Category", tariff_cats, label_visibility="collapsed")
    
    # Apply both filters
    if selected_name != "(All)":
        filtered_icb = icb_df[icb_df["icb_name"] == selected_name].copy()
    else:
        filtered_icb = icb_df.copy()
    
    if selected_tariff_cat != "(All)":
        filtered_icb = filtered_icb[filtered_icb["tariff_cat"] == selected_tariff_cat].copy()

st.markdown (f"#### Total changes for {max_tariff_date}")