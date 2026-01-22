import streamlit as st
import pandas as pd
from st_aggrid import AgGrid, GridOptionsBuilder, JsCode

st.set_page_config(layout="wide")
st.title("Price Change Demo")

# Load CSVs
icb_df = pd.read_csv("icbpricechanges.csv")
vmpp_df = pd.read_csv("vmpppricechanges.csv")

# --- filter by name (UI only, not shown in table) ---
names = ["(All)"] + sorted(icb_df["name"].dropna().unique().tolist())
selected_name = st.selectbox("Integrated Care Board", names)

if selected_name != "(All)":
    filtered_df = icb_df[icb_df["name"] == selected_name].copy()
else:
    filtered_df = icb_df.copy()

# --- aggregate ---
@st.cache_data
def compute_master(df: pd.DataFrame):
    df = df.copy()
    df["price_difference"] = pd.to_numeric(
        df["price_difference"], errors="coerce"
    ).fillna(0)

    master = (
        df.groupby(["bnf_name", "bnf_code"], as_index=False)
          .agg(price_difference_sum=("price_difference", "sum"))
          .sort_values("price_difference_sum", ascending=True)  # ASC
          .reset_index(drop=True)
    )

    # rename + select only what we show
    master = master.rename(columns={
        "bnf_name": "BNF name",
        "price_difference_sum": "Price difference"
    })[["BNF name", "Price difference"]]

    return master

master_df = compute_master(filtered_df)

# --- display ---
st.subheader("Price difference by BNF")

st.dataframe(
    master_df.style.format({
        "Price difference": "£{:,.2f}"
    }),
    use_container_width=True,
    hide_index=True
)