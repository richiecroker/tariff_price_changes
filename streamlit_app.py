import streamlit as st
import pandas as pd
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode, JsCode

# Set wide layout
st.set_page_config(layout="wide")

# Load CSVs (to be replaced with SQL)

icb_df = pd.read_csv("icbpricechanges.csv")
vmpp_df = pd.read_csv("vmpppricechanges.csv")

# GBP formatter (Python side)

def gbp(x):
    if pd.isna(x):
        return ""
    x = float(x)
    sign = "-" if x < 0 else ""
    return f"{sign}£{abs(x):,.2f}"

# Top filter by ICB

st.header("Drug Tariff price change estimator", divider ="blue")

names = ["(All)"] + sorted(icb_df["name"].dropna().unique().tolist())
st.markdown("### Select Integrated Care Board")
selected_name = st.selectbox("Select Integrated Care Board", names, label_visibility="collapsed")

if selected_name != "(All)":
    filtered_icb = icb_df[icb_df["name"] == selected_name].copy()
else:
    filtered_icb = icb_df.copy()

# Calculate and display total price change
total_difference = pd.to_numeric(filtered_icb["price_difference"], errors="coerce").fillna(0).sum()
st.markdown("#### Total estimated monthly price difference")
st.markdown(f"#### {gbp(total_difference)}")

# =======.======================
# Master aggregation with details
# =============================
@st.cache_data
def compute_master_with_details(icb_df: pd.DataFrame, vmpp_df: pd.DataFrame):
    icb_df = icb_df.copy()
    icb_df["price_difference"] = pd.to_numeric(
        icb_df["price_difference"], errors="coerce"
    ).fillna(0)

    master = (
        icb_df.groupby(["bnf_name", "bnf_code"], as_index=False)
          .agg(price_difference_sum=("price_difference", "sum"))
          .sort_values("price_difference_sum", ascending=True)
          .reset_index(drop=True)
    )

    # Add VMPP details for each BNF code
    expanded_rows = []
    for _, row in master.iterrows():
        # Add main row
        expanded_rows.append({
            "bnf_name": row["bnf_name"],
            "bnf_code": row["bnf_code"],
            "price_difference_sum": row["price_difference_sum"],
            "is_detail": False,
            "drill": ""
        })
        
        # Add detail rows (hidden by default)
        details = vmpp_df[vmpp_df["bnf_code"] == row["bnf_code"]].copy()
        for _, detail in details.iterrows():
            expanded_rows.append({
                "bnf_name": f"  → {detail.get('nm', '')}",
                "bnf_code": row["bnf_code"],
                "price_difference_sum": None,
                "is_detail": True,
                "drill": ""
            })
    
    return pd.DataFrame(expanded_rows)

master_df = compute_master_with_details(filtered_icb, vmpp_df)

# Price formatter for AgGrid

price_formatter = JsCode("""
function(params) {
    if (params.value == null || params.value === undefined) return '';
    const v = Number(params.value);
    if (isNaN(v)) return '';
    const sign = v < 0 ? '-' : '';
    const abs = Math.abs(v).toLocaleString('en-GB', {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
    });
    return sign + '£' + abs;
}
""")

# Build Master Grid with master-detail
# =============================
st.subheader("Estimated cost difference per presentation")

gb = GridOptionsBuilder.from_dataframe(master_df)

gb.configure_column("bnf_name", header_name="BNF name", sortable=True, flex=2)
gb.configure_column(
    "price_difference_sum",
    header_name="Est cost difference",
    sortable=True,
    type=["numericColumn"],
    valueFormatter=price_formatter,
    flex=1,
    cellStyle=JsCode("""
        function(p) {
            if (p.value == null) return {};
            if (p.value < 0) return {color: 'green'};
            if (p.value > 0) return {color: 'red'};
            return {};
        }
    """)
)

gb.configure_column("bnf_code", hide=True)
gb.configure_column("is_detail", hide=True)
gb.configure_column("drill", hide=True)

# Configure pagination
gb.configure_pagination(paginationAutoPageSize=False, paginationPageSize=30)

# Hide detail rows by default
gb.configure_grid_options(
    isExternalFilterPresent=JsCode("function() { return true; }"),
    doesExternalFilterPass=JsCode("""
        function(node) {
            return !node.data.is_detail;
        }
    """)
)

gb.configure_selection("single", use_checkbox=False)
grid_opts = gb.build()

grid_response = AgGrid(
    master_df,
    gridOptions=grid_opts,
    update_mode=GridUpdateMode.SELECTION_CHANGED,
    allow_unsafe_jscode=True,
    fit_columns_on_grid_load=True,
    height=420,
    theme='streamlit'
)

# Show details below when selected

selected = grid_response.get("selected_rows")

if selected is None:
    selected = []
elif isinstance(selected, pd.DataFrame):
    selected = selected.to_dict('records')
elif not isinstance(selected, list):
    selected = []

if len(selected) > 0:
    sel = selected[0]
    bnf_code = sel.get("bnf_code")
    bnf_name = sel.get("bnf_name")
    
    if bnf_code and not sel.get("is_detail"):
        # Get VMPP details
        details_df = vmpp_df[vmpp_df["bnf_code"] == bnf_code].copy()
        
        if not details_df.empty:
            details_df["price"] = pd.to_numeric(details_df["price_pence"], errors="coerce") / 100
            details_df["previous_price"] = pd.to_numeric(details_df["previous_price_pence"], errors="coerce") / 100
            
            st.subheader(f"Drug Tariff details for {bnf_name}")
            
            display_df = details_df[["nm", "price", "previous_price", "tariff_category"]].copy()
            display_df.columns = ["Name", "Price", "Previous Price", "Tariff Category"]
            
            st.dataframe(
                display_df.style.format({
                    "Price": gbp,
                    "Previous Price": gbp
                }),
                hide_index=True,
                use_container_width=True
            )

# Add download button for full dataset
csv_data = master_df[master_df["is_detail"] == False][["bnf_name", "bnf_code", "price_difference_sum"]].to_csv(index=False)
st.download_button(
    "Download full table as CSV",
    csv_data,
    file_name=f"bnf_prices_{selected_name.replace(' ', '_')}.csv",
    mime="text/csv"
)