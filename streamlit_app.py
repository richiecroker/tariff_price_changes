import streamlit as st
import pandas as pd
from st_aggrid import AgGrid, GridOptionsBuilder, JsCode

st.set_page_config(layout="wide")
st.title("Price Change Demo")

# Load CSV
df = pd.read_csv("pricechangedemo.csv")

# --- TOP FILTER ---
names = ["(All)"] + sorted(df["name"].dropna().unique().tolist())
selected_name = st.selectbox("Integrated Care Board", names)   # fixed spelling optionally

if selected_name != "(All)":
    df = df[df["name"] == selected_name]

gb = GridOptionsBuilder.from_dataframe(df)

# Return a numeric value (so sorting/filtering works)
js_value_getter = JsCode("""
function(params) {
    if (params.data && params.data.price_pence != null && !isNaN(params.data.price_pence)) {
        return params.data.price_pence / 100.0;  // numeric pounds value
    }
    return null;
}
""")

# Format display to 2 decimal places (keeps underlying value numeric)
js_value_formatter = JsCode("""
function(params) {
    if (params.value == null || params.value === '') return '';
    // params.value is numeric because valueGetter returns a number
    return params.value.toFixed(2);
}
""")

gb.configure_column(
    field="price_pence",
    header_name="Price (GBP)",
    valueGetter=js_value_getter,
    valueFormatter=js_value_formatter,
    sortable=True,
    filter=True,
    type=["numericColumn","numberColumnFilter"],
)

gridOptions = gb.build()

grid_return = AgGrid(
    df,
    gridOptions=gridOptions,
    enable_enterprise_modules=False,
    fit_columns_on_grid_load=True
)
