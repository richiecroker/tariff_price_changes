import streamlit as st
import pandas as pd
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode, JsCode

# =============================
# Load CSVs FIRST
# =============================
icb_df = pd.read_csv("icbpricechanges.csv")
vmpp_df = pd.read_csv("vmpppricechanges.csv")

# =============================
# Top filter by name
# =============================
names = ["(All)"] + sorted(icb_df["name"].dropna().unique().tolist())
selected_name = st.selectbox("Integrated Care Board", names)

if selected_name != "(All)":
    filtered_icb = icb_df[icb_df["name"] == selected_name].copy()
else:
    filtered_icb = icb_df.copy()

# =============================
# GBP formatter (Python side)
# =============================
def gbp(x):
    if pd.isna(x):
        return ""
    x = float(x)
    sign = "-" if x < 0 else ""
    return f"{sign}£{abs(x):,.2f}"

# =============================
# Master aggregation
# =============================
@st.cache_data
def compute_master(df: pd.DataFrame):
    df = df.copy()
    df["price_difference"] = pd.to_numeric(
        df["price_difference"], errors="coerce"
    ).fillna(0)

    master = (
        df.groupby(["bnf_name", "bnf_code"], as_index=False)
          .agg(price_difference_sum=("price_difference", "sum"))
          .sort_values("price_difference_sum", ascending=True)
          .reset_index(drop=True)
    )

    # dummy column for drill button
    master["drill"] = ""
    return master

master_df = compute_master(filtered_icb)

# =============================
# CSS for drill button
# =============================
st.markdown(
    """
    <style>
      .ag-theme-streamlit .drill-btn {
        background: transparent;
        border: none;
        cursor: pointer;
        font-size: 14px;
        padding: 4px 6px;
      }
      .ag-theme-streamlit .drill-btn:hover {
        background: rgba(0,0,0,0.05);
        border-radius: 4px;
      }
    </style>
    """,
    unsafe_allow_html=True,
)

# =============================
# Drill button renderer (SAFE for React)
# =============================
drill_button_renderer = JsCode("""
function(params) {
    const id = 'drill-' + params.node.id;

    setTimeout(function() {
        const el = document.getElementById(id);
        if (!el || el.__bound) return;
        el.__bound = true;

        el.addEventListener('click', function(e) {
            e.stopPropagation();
            params.node.setSelected(true);
        });
    }, 0);

    return '<button id="' + id + '" class="drill-btn" title="Drill down">▶</button>';
}
""")

# =============================
# Price formatter for AgGrid
# =============================
price_formatter = JsCode("""
function(params) {
    if (params.value == null) return '';
    const v = Number(params.value);
    const sign = v < 0 ? '-' : '';
    const abs = Math.abs(v).toLocaleString('en-GB', {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
    });
    return sign + '£' + abs;
}
""")

# =============================
# Build Master Grid
# =============================
st.subheader("Master (aggregated by BNF)")

gb = GridOptionsBuilder.from_dataframe(master_df)

gb.configure_column("bnf_name", header_name="BNF name", sortable=True)
gb.configure_column(
    "price_difference_sum",
    header_name="Price difference",
    sortable=True,
    type=["numericColumn"],
    valueFormatter=price_formatter,
    cellStyle=JsCode("""
        function(p) {
            if (p.value < 0) return {color: 'red'};
            if (p.value > 0) return {color: 'green'};
            return {};
        }
    """)
)

gb.configure_column(
    "drill",
    header_name="",
    cellRenderer=drill_button_renderer,
    maxWidth=50,
    suppressSizeToFit=True,
    sortable=False,
    filter=False
)

# hidden but needed for drill
gb.configure_column("bnf_code", hide=True)

gb.configure_selection("single")
grid_opts = gb.build()

grid_response = AgGrid(
    master_df,
    gridOptions=grid_opts,
    update_mode=GridUpdateMode.SELECTION_CHANGED,
    allow_unsafe_jscode=True,
    fit_columns_on_grid_load=True,
    height=420
)

# =============================
# Robust selection handling
# =============================
selected = grid_response.get("selected_rows")

if not isinstance(selected, list) or len(selected) == 0:
    st.info("Click ▶ to drill down")
    st.stop()

sel = selected[0]
bnf_code = sel["bnf_code"]
bnf_name = sel["bnf_name"]
total = sel["price_difference_sum"]

# =============================
# Selected summary
# =============================
st.markdown(f"### Details for **{bnf_name}**")
st.dataframe(
    pd.DataFrame([{
        "BNF name": bnf_name,
        "Price difference": total
    }]).style.format({"Price difference": gbp}),
    hide_index=True,
    use_container_width=True
)

# =============================
# Detail rows from vmpp_df
# =============================
@st.cache_data
def get_vmpp_details(df: pd.DataFrame, bnf_code):
    d = df[df["bnf_code"] == bnf_code].copy()

    d["price"] = pd.to_numeric(d["price_pence"], errors="coerce") / 100
    d["previous_price"] = pd.to_numeric(d["previous_price_pence"], errors="coerce") / 100

    return d[[
        "nm",
        "price_pence",
        "previous_price_pence",
        "price",
        "previous_price"
    ]]

details_df = get_vmpp_details(vmpp_df, bnf_code)

if details_df.empty:
    st.warning("No matching rows in vmpp_df")
else:
    st.subheader("VMPP rows")
    st.dataframe(
        details_df.style.format({
            "price": gbp,
            "previous_price": gbp
        }),
        hide_index=True,
        use_container_width=True
    )

    st.download_button(
        "Download details as CSV",
        details_df.to_csv(index=False),
        file_name=f"vmpp_{bnf_code}.csv",
        mime="text/csv"
    )
