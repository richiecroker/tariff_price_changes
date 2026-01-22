import streamlit as st
import pandas as pd
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

# Show filtered raw data
st.subheader("Raw data")
st.dataframe(df)

# 1) Aggregate price_difference at BNF (drug) level
parent_agg = (
    df.groupby("bnf_name", as_index=False)["price_difference"]
      .sum()
)

parent_rows = [
    {"path": [r["bnf_name"]], "price_difference": r["price_difference"]}
    for _, r in parent_agg.iterrows()
]

# 2) Child rows: packs only (no cost)
child_rows = [
    {"path": [row["bnf_name"], row["nm"]], "price_difference": np.nan}
    for _, row in df.iterrows()
]

tree_df = pd.DataFrame(parent_rows + child_rows)

# Ensure parents appear before children
tree_df["depth"] = tree_df["path"].apply(len)
tree_df = tree_df.sort_values("depth").drop(columns="depth")

# 3) AgGrid configuration
gb = GridOptionsBuilder.from_dataframe(tree_df)

gb.configure_column(
    "path",
    header_name="Item",
    cellRenderer="agGroupCellRenderer"
)

gb.configure_column(
    "price_difference",
    header_name="Price difference",
    type=["numericColumn"],
    valueFormatter="x == null ? '' : x.toLocaleString()"
)

gb.configure_grid_options(
    treeData=True,
    getDataPath="function(data) { return data.path; }",
    autoGroupColumnDef={
        "headerName": "BNF / Pack",
        "cellRendererParams": {"suppressCount": True},
    },
)

AgGrid(
    tree_df,
    gridOptions=gb.build(),
    fit_columns_on_grid_load=True,
    height=350,
)