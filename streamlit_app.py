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

st.set_page_config(layout="wide")
st.title("BNF → Pack drilldown (memory-friendly)")

@st.cache_data
def load_and_prepare_tree(path="pricechangedemo.csv", nrows=None, max_parents=50):
    """Load data and build tree structure with limited rows"""
    # Load data
    df = pd.read_csv(
        path, 
        usecols=["bnf_name", "nm", "price_difference"],
        dtype={"bnf_name": "str", "nm": "str"},
        nrows=nrows
    )
    
    # Convert to numeric
    df["price_difference"] = pd.to_numeric(df["price_difference"], errors="coerce").astype("float32")
    
    # Aggregate at BNF level for parent rows
    parent_agg = (
        df.groupby("bnf_name", as_index=False)["price_difference"]
        .sum()
    )
    
    # Get top N parents by absolute price difference
    parent_agg["abs_pd"] = parent_agg["price_difference"].abs()
    top_parents = parent_agg.nlargest(max_parents, "abs_pd")["bnf_name"].tolist()
    
    # Get unique packs for those top parents only
    pack_list = (
        df[df["bnf_name"].isin(top_parents)]
        [["bnf_name", "nm"]]
        .drop_duplicates()
    )
    
    # Filter parent data to top only
    parent_subset = parent_agg[parent_agg["bnf_name"].isin(top_parents)].copy()
    
    # Build tree structure efficiently with list operations
    # Parent rows - create paths as lists
    parent_paths = [[bnf] for bnf in parent_subset["bnf_name"].tolist()]
    parent_prices = parent_subset["price_difference"].tolist()
    
    # Child rows - create paths efficiently
    child_paths = [[bnf, pack] for bnf, pack in zip(pack_list["bnf_name"], pack_list["nm"])]
    child_prices = [np.nan] * len(child_paths)
    
    # Create final tree dataframe
    all_paths = parent_paths + child_paths
    all_prices = parent_prices + child_prices
    
    tree_df = pd.DataFrame({
        "path": all_paths,
        "price_difference": all_prices
    })
    
    # Sort by first element of path (BNF name) and depth
    tree_df["_sort"] = tree_df["path"].str[0]
    tree_df["_depth"] = tree_df["path"].str.len()
    tree_df = tree_df.sort_values(["_sort", "_depth"]).drop(columns=["_sort", "_depth"])
    
    return tree_df.reset_index(drop=True)

# User input
max_parents = st.number_input(
    "Max number of BNF (parents) to show", 
    min_value=10, 
    max_value=200,  # Hard cap to prevent crashes
    value=30,  # Conservative default
    step=10
)

# Load data with the specified limit
tree_df = load_and_prepare_tree(max_parents=max_parents)

st.write(f"Displaying {len(tree_df):,} total rows")

# Validate
if len(tree_df) == 0:
    st.error("No data to display")
    st.stop()

# Configure AgGrid with tree data
gb = GridOptionsBuilder.from_dataframe(tree_df)

# Don't configure the path column separately - let autoGroupColumnDef handle it

# Configure price difference column
gb.configure_column(
    "price_difference",
    header_name="Price Difference",
    type=["numericColumn"],
    valueFormatter="x == null ? '' : '£' + x.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})",
    cellStyle={
        "styleConditions": [
            {
                "condition": "params.value > 0",
                "style": {"color": "#d32f2f", "fontWeight": "600"}
            },
            {
                "condition": "params.value < 0",
                "style": {"color": "#388e3c", "fontWeight": "600"}
            }
        ]
    }
)

# Configure tree data
gb.configure_grid_options(
    treeData=True,
    animateRows=False,
    groupDefaultExpanded=-1,  # -1 means start collapsed, user clicks to expand
    autoGroupColumnDef={
        "headerName": "BNF / Pack",
        "minWidth": 400,
        "cellRendererParams": {
            "suppressCount": True
        }
    },
    getDataPath="function(data) { var path = data.path; return path; }",
)

# Add pagination to limit rendered rows
gb.configure_pagination(
    paginationAutoPageSize=False,
    paginationPageSize=50  # Only render 50 rows at a time
)

# Build options
grid_options = gb.build()

# Display grid
AgGrid(
    tree_df,
    gridOptions=grid_options,
    height=600,
    theme="streamlit",
    enable_enterprise_modules=False,
    allow_unsafe_jscode=True,
    fit_columns_on_grid_load=True,
    update_mode="NO_UPDATE"
)

# Show warning if at max
if max_parents >= 200:
    st.warning("⚠️ At maximum display limit. Showing more rows may cause browser memory issues.")