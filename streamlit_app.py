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
from st_aggrid import AgGrid, GridOptionsBuilder, JsCode

st.set_page_config(layout="wide")
st.title("BNF → Pack drilldown (memory-friendly)")

import streamlit as st
import pandas as pd
import numpy as np
from st_aggrid import AgGrid, GridOptionsBuilder, JsCode

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
    
    # Build parent rows
    parent_df = pd.DataFrame({
        "orgHierarchy": parent_subset["bnf_name"].tolist(),
        "price_difference": parent_subset["price_difference"].tolist()
    })
    
    # Build child rows with hierarchy path
    child_df = pd.DataFrame({
        "orgHierarchy": [f"{bnf}|{pack}" for bnf, pack in zip(pack_list["bnf_name"], pack_list["nm"])],
        "price_difference": [np.nan] * len(pack_list)
    })
    
    # Combine
    tree_df = pd.concat([parent_df, child_df], ignore_index=True)
    
    return tree_df

# User input
max_parents = st.number_input(
    "Max number of BNF (parents) to show", 
    min_value=10, 
    max_value=200,
    value=30,
    step=10
)

# Load data
tree_df = load_and_prepare_tree(max_parents=max_parents)

st.write(f"Displaying {len(tree_df):,} total rows")

# Debug: show sample data
with st.expander("Debug: View sample data"):
    st.dataframe(tree_df.head(10))

# Add a simple name column extracted from hierarchy
tree_df["name"] = tree_df["orgHierarchy"].apply(lambda x: x.split('|')[-1])

# JavaScript function to parse the hierarchy
getDataPath = JsCode("""
function(data) {
    return data.orgHierarchy.split('|');
}
""")

# Configure AgGrid
gb = GridOptionsBuilder.from_dataframe(tree_df)

# Hide the orgHierarchy column but show name
gb.configure_column("orgHierarchy", hide=True)
gb.configure_column("name", hide=True)  # Will be shown via autoGroupColumnDef

# Configure price difference
gb.configure_column(
    "price_difference",
    header_name="Price Difference",
    type=["numericColumn"],
    valueFormatter=JsCode("""
    function(params) {
        if (params.value == null) return '';
        return '£' + params.value.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2});
    }
    """),
    cellStyle=JsCode("""
    function(params) {
        if (params.value == null) return null;
        if (params.value > 0) return {color: '#d32f2f', fontWeight: '600'};
        if (params.value < 0) return {color: '#388e3c', fontWeight: '600'};
        return null;
    }
    """)
)

# Configure tree grid
gb.configure_grid_options(
    treeData=True,
    animateRows=False,
    getDataPath=getDataPath,
    autoGroupColumnDef={
        "headerName": "BNF / Pack",
        "minWidth": 400,
        "field": "name",
        "cellRendererParams": {"suppressCount": True}
    },
    groupDefaultExpanded=-1,  # Start collapsed
)

# Pagination
gb.configure_pagination(
    paginationAutoPageSize=False,
    paginationPageSize=50
)

# Display
AgGrid(
    tree_df,
    gridOptions=gb.build(),
    height=600,
    allow_unsafe_jscode=True,
    theme="streamlit",
    fit_columns_on_grid_load=True
)

if max_parents >= 200:
    st.warning("⚠️ At maximum display limit. Showing more rows may cause browser memory issues.")