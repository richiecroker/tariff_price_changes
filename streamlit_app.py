import streamlit as st
import pandas as pd
from st_aggrid import AgGrid, GridOptionsBuilder, JsCode

st.set_page_config(layout="wide")
st.title("Price Change Demo")

# Load CSVs
icb_df = pd.read_csv("icbpricechanges.csv")
vmpp_df = pd.read_csv("vmpppricechanges.csv")

# --- TOP FILTER ---
names = ["(All)"] + sorted(icb_df["name"].dropna().unique().tolist())
selected_name = st.selectbox("Integrated Care Board", names)   # fixed spelling optionally

if selected_name != "(All)":
    icb_df = icb_df[icb_df["name"] == selected_name]

grid_return = AgGrid(icb_df)
