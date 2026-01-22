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

# Show filtered raw data
st.subheader("Raw data")
st.dataframe(df)

import streamlit as st
import pandas as pd
import numpy as np
from st_aggrid import AgGrid, GridOptionsBuilder
import gc

st.set_page_config(layout="wide")
st.title("BNF → Pack drilldown (memory-friendly)")

@st.cache_data
def load_csv(path="pricechangedemo.csv", nrows=None):
    # Read only required columns
    return pd.read_csv(
        path, 
        usecols=["bnf_name", "nm", "price_difference"],
        nrows=nrows,
        dtype={"bnf_name": "category", "nm": "category"}  # Use category for string columns
    )

# Load data
df = load_csv()

# Validate columns
required = {"bnf_name", "nm", "price_difference"}
if not required.issubset(set(df.columns)):
    st.error(f"CSV missing columns: {required - set(df.columns)}")
    st.stop()

# Convert price_difference to float32 (half the memory of float64)
df["price_difference"] = pd.to_numeric(df["price_difference"], errors="coerce").astype("float32")

# Aggregate packs - use observed=True to avoid empty categories
child_agg = (
    df.groupby(["bnf_name", "nm"], as_index=False, observed=True)["price_difference"]
      .sum()
)

# Clear original df from memory
del df
gc.collect()

# Aggregate parent totals
parent_agg = (
    child_agg.groupby("bnf_name", as_index=False, observed=True)["price_difference"]
             .sum()
)

# User input for top N
max_parents = st.number_input(
    "Max number of BNF (parents) to show", 
    min_value=10, 
    max_value=1000,  # Reduced max for safety
    value=100,  # Lower default
    step=10
)

# Get top parents efficiently
top_parents = (
    parent_agg
    .assign(abs_pd=lambda x: x["price_difference"].abs())
    .nlargest(max_parents, "abs_pd")["bnf_name"]
    .tolist()
)

# Filter to top parents only
parent_rows = parent_agg[parent_agg["bnf_name"].isin(top_parents)].copy()
child_rows = child_agg[child_agg["bnf_name"].isin(top_parents)].copy()

# Clear full aggregations from memory
del parent_agg, child_agg
gc.collect()

# Build tree structure more efficiently using list comprehension instead of apply
parent_paths = [[bnf] for bnf in parent_rows["bnf_name"]]
child_paths = [[bnf, nm] for bnf, nm in zip(child_rows["bnf_name"], child_rows["nm"])]

# Create tree dataframe
tree_df = pd.DataFrame({
    "path": parent_paths + child_paths,
    "price_difference": pd.concat([
        parent_rows["price_difference"].reset_index(drop=True),
        pd.Series([np.nan] * len(child_rows), dtype="float32")
    ], ignore_index=True)
})

# Clear intermediate data
del parent_rows, child_rows, parent_paths, child_paths
gc.collect()

# Sort efficiently
tree_df["_sort_key"] = tree_df["path"].str[0]  # First element as string
tree_df["_depth"] = tree_df["path"].str.len()
tree_df = tree_df.sort_values(["_sort_key", "_depth"]).drop(columns=["_sort_key", "_depth"])

st.write(f"Rendering {len(tree_df):,} rows")

# AgGrid configuration
gb = GridOptionsBuilder.from_dataframe(tree_df)
gb.configure_column("path", header_name="BNF / Pack", hide=True)
gb.configure_column(
    "price_difference",
    header_name="Price difference",
    type=["numericColumn"],
    valueFormatter="x == null ? '' : '£' + x.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})"
)

gb.configure_grid_options(
    treeData=True,
    getDataPath="function(data) { return data.path; }",
    autoGroupColumnDef={
        "headerName": "Item", 
        "cellRendererParams": {"suppressCount": True},
        "minWidth": 300
    },
    animateRows=False,  # Disable animations
    suppressRowTransform=True,  # Reduce rendering overhead
)

# Pagination for large datasets
gb.configure_pagination(paginationAutoPageSize=False, paginationPageSize=100)

AgGrid(
    tree_df,
    gridOptions=gb.build(),
    fit_columns_on_grid_load=True,
    height=600,
    theme="streamlit",
    enable_enterprise_modules=False,  # Disable unused features
    update_mode="NO_UPDATE"  # Read-only mode
)