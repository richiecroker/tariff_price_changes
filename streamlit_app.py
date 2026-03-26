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


from db import _gcs_client, GCS_DB_PATH, BUCKET_NAME

if st.button("Force rebuild"):
    client = _gcs_client()
    bucket = client.bucket(BUCKET_NAME)
    bucket.blob(GCS_DB_PATH).delete()
    st.cache_resource.clear()
    st.success("Cache cleared, reload the app to rebuild")




