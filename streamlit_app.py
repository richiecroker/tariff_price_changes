import streamlit as st
import pandas as pd
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode, JsCode

# ---------- Load CSVs (assume done earlier) ----------
# icb_df = pd.read_csv("icbpricechanges.csv")
# vmpp_df = pd.read_csv("vmpppricechanges.csv")

# ---------- top filter by name (unchanged) ----------
names = ["(All)"] + sorted(icb_df["name"].dropna().unique().tolist())
selected_name = st.selectbox("Integrated Care Board", names)
if selected_name != "(All)":
    filtered_icb = icb_df[icb_df["name"] == selected_name].copy()
else:
    filtered_icb = icb_df.copy()

# ---------- GBP formatter for Python display (keep for non-AgGrid displays) ----------
def gbp(x):
    if pd.isna(x):
        return ""
    try:
        x = float(x)
    except Exception:
        return x
    sign = "-" if x < 0 else ""
    return f"{sign}£{abs(x):,.2f}"

# ---------- compute master (group by bnf_name + bnf_code) ----------
@st.cache_data
def compute_master(df: pd.DataFrame):
    df = df.copy()
    df["price_difference"] = pd.to_numeric(df.get("price_difference", 0), errors="coerce").fillna(0)
    grouped = (
        df.groupby(["bnf_name", "bnf_code"], as_index=False)
          .agg(price_difference_sum=("price_difference", "sum"),
               detail_count=("bnf_code", "count"))
          .sort_values("price_difference_sum", ascending=True)
          .reset_index(drop=True)
    )
    # Add a dummy col for the drill button (AgGrid will render it)
    grouped["drill"] = ""
    return grouped

master_df = compute_master(filtered_icb)

# ---------- small CSS for the button appearance ----------
st.markdown(
    """
    <style>
      .ag-theme-streamlit .drill-btn {
        background: transparent;
        border: none;
        font-size: 16px;
        cursor: pointer;
        padding: 4px 6px;
      }
      .ag-theme-streamlit .drill-btn:hover { background: rgba(0,0,0,0.05); border-radius:4px; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------- JS cell renderer that returns a button and selects the row when clicked ----------
drill_button_renderer = JsCode("""
function(params) {
    // create a small button with an arrow
    const btn = document.createElement('button');
    btn.className = 'drill-btn';
    btn.type = 'button';
    // Unicode triangle, you can change to ► or ◀ etc.
    btn.innerHTML = '▶';
    btn.title = 'Drill down';

    btn.addEventListener('click', function(e) {
        // Prevent the click from also causing row selection via rowClick
        e.stopPropagation();
        try {
            // Select this row in the grid. This makes the selected_rows available to Python.
            params.node.setSelected(true);
        } catch (err) {
            // fallback: do nothing
            console.warn(err);
        }
    });

    return btn;
}
""")

# ---------- Optional: JS valueFormatter to show arrow+currency in a column (not necessary if using the drill button) ----------
# (Left here as reference — use if you want the price column to also show ▲/▼ icons)
price_with_sign_formatter = JsCode("""
function(params) {
    if (params.value === null || params.value === undefined) {
        return '';
    }
    const v = Number(params.value);
    const sign = v < 0 ? '-' : '';
    const arrow = v === 0 ? '' : (v < 0 ? '▼ ' : '▲ ');
    const abs = Math.abs(v).toLocaleString('en-GB', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    return arrow + sign + '£' + abs;
}
""")

# ---------- Build the AgGrid with the drill column ----------
st.subheader("Master (aggregated by BNF) — click ▶ to drill down")

gb = GridOptionsBuilder.from_dataframe(master_df)

# visible columns
gb.configure_column("bnf_name", header_name="BNF name", sortable=True, resizable=True)
# show numeric but formatted with JS formatter so sign/arrow and currency show in-grid
gb.configure_column(
    "price_difference_sum",
    header_name="Price difference",
    type=["numericColumn"],
    sortable=True,
    valueFormatter=price_with_sign_formatter,
    # adjust cellStyle via JS if you want colouring:
    cellStyle=JsCode("""
        function(params) {
            if (params.value < 0) return {color: 'red'};
            if (params.value > 0) return {color: 'green'};
            return {};
        }
    """)
)

# the drill column: no header, small width, use our cellRenderer
gb.configure_column(
    "drill",
    header_name="",
    cellRenderer=drill_button_renderer,
    maxWidth=50,
    suppressSizeToFit=True,
    sortable=False,
    filter=False
)

# keep bnf_code hidden but available in selected row payload
gb.configure_column("bnf_code", hide=True)
gb.configure_column("detail_count", hide=True)

gb.configure_selection(selection_mode="single", use_checkbox=False)
grid_opts = gb.build()

grid_response = AgGrid(
    master_df,
    gridOptions=grid_opts,
    update_mode=GridUpdateMode.SELECTION_CHANGED,
    fit_columns_on_grid_load=True,
    allow_unsafe_jscode=True,
    height=420
)

# ---------- Robust selection handling (avoid pandas truthiness pitfall) ----------
selected = grid_response.get("selected_rows", None)

if selected is None:
    has_selection = False
elif isinstance(selected, (list, tuple)):
    has_selection = len(selected) > 0
elif hasattr(selected, "empty"):  # possible DataFrame/Series
    try:
        has_selection = not selected.empty
    except Exception:
        has_selection = False
else:
    try:
        has_selection = len(selected) > 0
    except Exception:
        has_selection = False

if not has_selection:
    st.info("Click the ▶ button for a BNF row to drill down.")
    st.stop()

# normalize to list-of-dicts if needed
if hasattr(selected, "to_dict"):
    try:
        selected = selected.to_dict(orient="records")
    except Exception:
        selected = [selected]

sel = selected[0]
sel_bnf_code = sel.get("bnf_code")
sel_bnf_name = sel.get("bnf_name")
sel_sum = sel.get("price_difference_sum")

# ---------- Show the aggregate nicely (using Python formatter) ----------
st.markdown(f"### Details for **{sel_bnf_name}**  — code **{sel_bnf_code}**")
st.write("Aggregate:")
st.dataframe(
    pd.DataFrame([{"BNF name": sel_bnf_name, "Price difference": sel_sum}])
      .style.format({"Price difference": gbp}),
    use_container_width=True,
    hide_index=True
)

# ---------- Fetch details from vmpp_df (your requested columns) ----------
@st.cache_data
def get_vmpp_details(vmpp_df: pd.DataFrame, bnf_code):
    if "bnf_code" not in vmpp_df.columns:
        return pd.DataFrame()
    df = vmpp_df[vmpp_df["bnf_code"] == bnf_code].copy()
    # Ensure pence cols exist
    for col in ["price_pence", "previous_price_pence"]:
        if col not in df.columns:
            df[col] = pd.NA
    # derive pounds for display/sorting but keep pence columns for download
    df["price"] = pd.to_numeric(df["price_pence"], errors="coerce") / 100.0
    df["previous_price"] = pd.to_numeric(df["previous_price_pence"], errors="coerce") / 100.0
    # pick the requested fields plus derived pounds
    out = df.loc[:, ["nm", "price_pence", "previous_price_pence", "price", "previous_price"]].copy()
    return out

details_df = get_vmpp_details(vmpp_df, sel_bnf_code)

if details_df.empty:
    st.warning("No matching detail rows found in vmpp_df for this BNF code.")
else:
    st.write(f"{len(details_df)} matching rows from `vmpp_df`")
    # display with gbp formatting on the pounds columns
    display_style = details_df.style.format({"price": gbp, "previous_price": gbp})
    st.dataframe(display_style, use_container_width=True, hide_index=True)

    # download CSV (pence + derived prices)
    csv = details_df.to_csv(index=False)
    st.download_button("Download details as CSV", data=csv, file_name=f"vmpp_details_{sel_bnf_code}.csv", mime="text/csv")

