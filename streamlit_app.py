import streamlit as st
import pandas as pd
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode, JsCode


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


conn = get_duckdb_connection()

icb_df = conn.execute("""
    SELECT
        rx.name,
        rx.bnf_name,
        rx.bnf_code,
        dt.tariff_cat,
        SUM(rx.quantity * dt.price_diff_pu * rx.is_max_price_diff_pu) AS price_difference
    FROM prescribing AS rx
    INNER JOIN tariff_price_changes AS dt
    ON rx.bnf_code = dt.bnf_code
    GROUP BY rx.name, rx.bnf_name, rx.bnf_code, dt.tariff_cat
    """).df()

st.dataframe(icb_df)

# Load data from SQL queries
#icb_data, vmpp_data = data_loader.get_fresh_data_if_needed()
#icb_df = pd.DataFrame(icb_data)
#vmpp_df = pd.DataFrame(vmpp_data)

# Get latest dates
#raw_max_rx_date = data_loader.get_cached_max_rxdate()
#max_rx_date = pd.to_datetime(raw_max_rx_date, errors="coerce").strftime("%B %Y")

#raw_max_tariff_date = data_loader.get_cached_max_tariffdate()
#max_tariff_date = pd.to_datetime(raw_max_tariff_date, errors="coerce").strftime("%B %Y")