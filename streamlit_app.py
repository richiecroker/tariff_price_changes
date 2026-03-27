import streamlit as st
import pandas as pd
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode, JsCode
from datetime import datetime

from db import get_duckdb_connection, get_latest_dates, _bq_client, _latest_bq_month

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

from db import _bq_client, _latest_bq_month, get_duckdb_connection

if st.button("Test DuckDB connection"):
    try:
        conn = get_duckdb_connection()
        tables = [r[0] for r in conn.execute("SHOW TABLES").fetchall()]
        st.success(f"DuckDB connected, tables: {tables}")
    except Exception as e:
        st.error(f"DuckDB connection failed: {e}")



if st.button("Test table data"):
    conn = get_duckdb_connection()
    st.subheader("Prescribing")
    st.dataframe(conn.execute("SELECT * FROM prescribing LIMIT 5").df())
    st.subheader("Tariff price changes")
    st.dataframe(conn.execute("SELECT * FROM tariff_price_changes LIMIT 5").df())
    st.subheader("VMPP changes")
    st.dataframe(conn.execute("SELECT * FROM vmpp_tariff_changes LIMIT 5").df())
    st.subheader("practices")
    st.dataframe(conn.execute("SELECT * FROM practices LIMIT 5").df())


from db import _gcs_client, GCS_DB_PATH, BUCKET_NAME

if st.button("Force rebuild"):
    client = _gcs_client()
    bucket = client.bucket(BUCKET_NAME)
    try:
        bucket.blob(GCS_DB_PATH).delete()
    except Exception:
        pass  # file doesn't exist in GCS, that's fine
    st.cache_resource.clear()
    st.success("Cache cleared, reload the app to rebuild")


if st.button("Test practices build"):
    conn = get_duckdb_connection()
    try:
        df = conn.execute("SELECT * FROM practices LIMIT 5").df()
        st.dataframe(df)
    except Exception as e:
        st.error(f"Error: {e}")

conn = get_duckdb_connection()

icb_df = conn.execute("""
    SELECT
        prac.icb_name,
        rx.bnf_name,
        rx.bnf_code,
        dt.tariff_cat,
        SUM(rx.quantity * dt.price_diff_pu * dt.is_max_price_diff_pu) AS price_difference
    FROM prescribing AS rx
    INNER JOIN tariff_price_changes AS dt
    ON rx.bnf_code = dt.bnf_code
    INNER JOIN practices AS prac
    ON
    rx.practice = prac.practice_code
    GROUP BY prac.icb_name, rx.bnf_name, rx.bnf_code, dt.tariff_cat
    """).df()


vmpp_df = conn.execute("""
    SELECT * FROM vmpp_tariff_changes
    """).df()


dates = get_latest_dates()
max_rx_date = dates["prescribing"]
max_tariff_date  = dates["tariff"]
#raw_max_tariff_date = data_loader.get_cached_max_tariffdate()
#max_tariff_date = pd.to_datetime(raw_max_tariff_date, errors="coerce").strftime("%B %Y")
#max_tariff = conn.execute("SELECT MAX(date) FROM tariff_price_changes").fetchone()[0]

# calculate number of changes to vmpp

price = pd.to_numeric(vmpp_df["price_pence"], errors="coerce")
prev = pd.to_numeric(vmpp_df["previous_price_pence"], errors="coerce")

num_increased = (price > prev).sum()
num_decreased = (price < prev).sum()
num_unchanged = (price == prev).sum()



# GBP formatter (Python side)

def gbp(x):
    if pd.isna(x):
        return ""
    x = float(x)
    sign = "-" if x < 0 else ""
    return f"{sign}£{abs(x):,.0f}"

def gbp2f(x):
    if pd.isna(x):
        return ""
    x = float(x)
    sign = "-" if x < 0 else ""
    return f"{sign}£{abs(x):,.2f}"




# Top filter by ICB

practices_df = conn.execute("SELECT * FROM practices").df()
with st.sidebar:
    st.markdown(f"### Drug Tariff month: {datetime.strptime(max_tariff_date, '%Y-%m-%d').strftime('%B %Y')}")
    st.markdown(f"### Prescribing data used for estimate: {datetime.strptime(max_rx_date, '%Y-%m-%d').strftime('%B %Y')}")

    # ICB Filter
    names = ["(All)"] + sorted(icb_df["icb_name"].dropna().unique().tolist())
    st.markdown("### Select Integrated Care Board")
    selected_name = st.selectbox("Select Integrated Care Board", names, label_visibility="collapsed")
    # Tariff Category Filter
    tariff_cats = ["(All)"] + sorted(icb_df["tariff_cat"].dropna().unique().tolist())
    st.markdown("### Select Tariff Category")
    selected_tariff_cat = st.selectbox("Select Tariff Category", tariff_cats, label_visibility="collapsed")
    
    # Apply both filters
    if selected_name != "(All)":
        filtered_icb = icb_df[icb_df["icb_name"] == selected_name].copy()
    else:
        filtered_icb = icb_df.copy()
    
    if selected_tariff_cat != "(All)":
        filtered_icb = filtered_icb[filtered_icb["tariff_cat"] == selected_tariff_cat].copy()




    st.header("Filters")
    st.info("Select an organisation at any level.")
    
    region_opts = sorted(practices_df["region_name"].dropna().unique().tolist())
    sel_regions = [v for v in st.session_state.get("sel_region", []) if v in region_opts]
    sel_regions = st.multiselect("Region", region_opts, default=sel_regions, key="sel_region")
    df_region = practices_df if not sel_regions else practices_df[practices_df["region_name"].isin(sel_regions)]

    icb_opts = sorted(df_region["icb_name"].dropna().unique().tolist())
    sel_icbs = [v for v in st.session_state.get("sel_icb", []) if v in icb_opts]
    sel_icbs = st.multiselect("ICB", icb_opts, default=sel_icbs, key="sel_icb")
    df_icb = df_region if not sel_icbs else df_region[df_region["icb_name"].isin(sel_icbs)]

    pcn_opts = sorted(df_icb["pcn_name"].dropna().unique().tolist())
    sel_pcns = [v for v in st.session_state.get("sel_pcn", []) if v in pcn_opts]
    sel_pcns = st.multiselect("PCN", pcn_opts, default=sel_pcns, key="sel_pcn")
    df_pcn = df_icb if not sel_pcns else df_icb[df_icb["pcn_name"].isin(sel_pcns)]

    practice_opts = sorted(df_pcn["practice_name"].dropna().unique().tolist())
    sel_practices = [v for v in st.session_state.get("sel_practice", []) if v in practice_opts]
    sel_practices = st.multiselect("Practice", practice_opts, default=sel_practices, key="sel_practice")
    df_selected = df_pcn if not sel_practices else df_pcn[df_pcn["practice_name"].isin(sel_practices)]

    selected_practice_codes = df_selected["practice_code"].unique().tolist()

st.markdown (f"#### Total changes for {max_tariff_date}")

# Coerce prices to numeric
price = pd.to_numeric(vmpp_df["price_pence"], errors="coerce")
prev = pd.to_numeric(vmpp_df["previous_price_pence"], errors="coerce")

# Only compare rows with both values present
df = vmpp_df.copy()
df["price"] = price
df["prev_price"] = prev

df = df[df["price"].notna() & df["prev_price"].notna()]

# Create change label
df["price_change"] = "unchanged"
df.loc[df["price"] > df["prev_price"], "price_change"] = "increase"
df.loc[df["price"] < df["prev_price"], "price_change"] = "decrease"

# Group by category + change
summary = (
    df.groupby(["tariff_category", "price_change"])
      .size()
      .unstack(fill_value=0)
      .reset_index()
)

for _, row in summary.iterrows():
    st.markdown(f"**Category: {row['tariff_category']}**")
    c1, c2, c3 = st.columns(3)
    c1.write(f"Increases: {row.get('increase', 0)}")
    c2.write(f"Decreases: {row.get('decrease', 0)}")
    c3.write(f"No change: {row.get('unchanged', 0)}")



# Calculate and display total price change
total_difference = pd.to_numeric(filtered_icb["price_difference"], errors="coerce").fillna(0).sum()
st.markdown(f"### Total estimated monthly price difference: {gbp(total_difference)}")


conn.register("selected_practices", df_selected)



st.dataframe(filtered_df)
filtered_df = conn.execute("""
    SELECT
        rx.bnf_name,
        rx.bnf_code,
        dt.tariff_cat,
        SUM(rx.quantity * dt.price_diff_pu * dt.is_max_price_diff_pu) AS price_difference
    FROM prescribing AS rx
    INNER JOIN tariff_price_changes AS dt
    ON rx.bnf_code = dt.bnf_code
    INNER JOIN selected_practices sp ON p.practice_code = sp.practice_code
    GROUP BY rx.bnf_name, rx.bnf_code, dt.tariff_cat
    """).df()

conn.unregister("selected_practices")





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

# =============================
# Top 10 Reductions and Increases
# =============================
# Get only the master rows (not detail rows)
master_only = master_df[master_df["is_detail"] == False].copy()

# Top 10 reductions (most negative values)
top_reductions = master_only.nsmallest(10, "price_difference_sum")[["bnf_name", "price_difference_sum"]].copy()
top_reductions.columns = ["BNF Name", "Price Difference"]

# Top 10 increases (most positive values)
top_increases = master_only.nlargest(10, "price_difference_sum")[["bnf_name", "price_difference_sum"]].copy()
top_increases.columns = ["BNF Name", "Price Difference"]

# Display side by side
col1, col2 = st.columns(2)

with col1:
    st.subheader("Top 10 estimated cost reductions")
    st.dataframe(
        top_reductions.style.format({"Price Difference": gbp}),
        hide_index=True,
        use_container_width=True
    )

with col2:
    st.subheader("Top 10 estimated cost increases")
    st.dataframe(
        top_increases.style.format({"Price Difference": gbp}),
        hide_index=True,
        use_container_width=True
    )


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
st.subheader("Estimated cost difference per presentation", divider="blue")
st.markdown("Click on product to see tariff details")

# Add search box for BNF name
search_term = st.text_input("Search BNF name", placeholder="Type to search...")

# Filter master_df based on search
if search_term:
    display_master_df = master_df[
        master_df["bnf_name"].str.contains(search_term, case=False, na=False)
    ].copy()
else:
    display_master_df = master_df.copy()

gb = GridOptionsBuilder.from_dataframe(display_master_df)

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
    display_master_df,
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
            
            st.subheader(f"Drug Tariff details for {bnf_name}", divider="blue")
            
            display_df = details_df[["nm", "price", "previous_price", "tariff_category"]].copy()
            display_df.columns = ["Name", "Price", "Previous Price", "Tariff Category"]
            
            st.dataframe(
                display_df.style.format({
                    "Price": gbp2f,
                    "Previous Price": gbp2f
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
