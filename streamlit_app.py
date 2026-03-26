import streamlit as st
import pandas as pd
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode, JsCode
from db import _bq_client

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





from db import _bq_client, _latest_bq_month

st.title("Connection Test")

if st.button("Test BQ Connection"):
    try:
        bq = _bq_client()
        result = bq.query("SELECT 1").result()
        st.success("BQ connection OK")
    except Exception as e:
        st.error(f"BQ connection failed: {e}")

if st.button("Test latest dates"):
    prescribing = _latest_bq_month("hscic.normalised_prescribing", "month")
    tariff = _latest_bq_month("dmd.tariffprice", "date")
    st.write(f"Latest prescribing month: {prescribing}")
    st.write(f"Latest tariff date: {tariff}")











