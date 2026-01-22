import streamlit as st
import pandas as pd
import numpy as np
from st_aggrid import AgGrid, GridOptionsBuilder

st.set_page_config(layout="wide")

st.title("Price Change Demo")

# Load CSV
df = pd.read_csv("pricechangedemo.csv")

# --- TOP FILTER ---
names = ["(All)"] + sorted(df["name"].dropna().unique().tolist())
selected_name = st.selectbox("Intergrated Care Board", names)

if selected_name != "(All)":
    df = df[df["name"] == selected_name]

gb = GridOptionsBuilder.from_dataframe(df)

# JsCode: convert pence -> pounds, formatted to 2 decimals
js_value_getter = JsCode("""
function(params) {
    if (params.data && params.data.price_pence != null && !isNaN(params.data.price_pence)) {
        var pounds = params.data.price_pence / 100.0;
        return pounds.toFixed(2);  // returns string for nice display
    }
    return null;
}
""")

# Configure column to use the JS valueGetter (display only)
gb.configure_column(
    field="price_pence",
    header_name="Price (GBP)",
    valueGetter=js_value_getter,
    sortable=True,
    filter=True
)

gridOptions = gb.build()

grid_return = AgGrid(
    df,
    gridOptions=gridOptions,
    enable_enterprise_modules=False,
    fit_columns_on_grid_load=True
)