import streamlit as st
import pandas as pd
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode

# ---------- Load CSVs ----------
icb_df = pd.read_csv("icbpricechanges.csv")
vmpp_df = pd.read_csv("vmpppricechanges.csv")

# ---------- UI: top filter by name ----------
names = ["(All)"] + sorted(icb_df["name"].dropna().unique().tolist())
selected_name = st.selectbox("Integrated Care Board", names)

if selected_name != "(All)":
    filtered_icb = icb_df[icb_df["name"] == selected_name].copy()
else:
    filtered_icb = icb_df.copy()

# ---------- GBP formatter (shows -£x.xx) ----------
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
    return grouped

master_df = compute_master(filtered_icb)

# ---------- Master grid (bnf_code hidden) ----------
st.subheader("Master (aggregated by BNF) — select a row to drill down")
gb = GridOptionsBuilder.from_dataframe(master_df)
gb.configure_column("bnf_name", header_name="BNF name", sortable=True, resizable=True)
gb.configure_column("price_difference_sum", header_name="Price difference (sum)", type=["numericColumn"], sortable=True)
gb.configure_column("bnf_code", hide=True)
gb.configure_column("detail_count", hide=True)
gb.configure_selection(selection_mode="single", use_checkbox=False)
grid_options = gb.build()

grid_response = AgGrid(
    master_df,
    gridOptions=grid_options,
    update_mode=GridUpdateMode.SELECTION_CHANGED,
    fit_columns_on_grid_load=True,
    height=400,
    allow_unsafe_jscode=True,
)

selected = grid_response["selected_rows"]
if not selected:
    st.info("No BNF selected. Select a row in the master grid to see the matching rows from the other table.")
    st.stop()

# ---------- when a master row is selected ----------
sel = selected[0]
sel_bnf_code = sel.get("bnf_code")
sel_bnf_name = sel.get("bnf_name")
sel_sum = sel.get("price_difference_sum")

st.markdown(f"### Details for **{sel_bnf_name}**  — code **{sel_bnf_code}**")
st.write("Aggregate:")
st.dataframe(
    pd.DataFrame([{"BNF name": sel_bnf_name, "Price difference": sel_sum}])
      .style.format({"Price difference": gbp}),
    use_container_width=True,
    hide_index=True
)

# ---------- fetch details from vmpp_df and show only nm, price_pence, previous_price_pence ----------
@st.cache_data
def get_vmpp_details(vmpp_df: pd.DataFrame, bnf_code):
    if "bnf_code" not in vmpp_df.columns:
        return pd.DataFrame()
    df = vmpp_df[vmpp_df["bnf_code"] == bnf_code].copy()
    # Ensure pence columns exist
    for col in ["price_pence", "previous_price_pence"]:
        if col not in df.columns:
            df[col] = pd.NA

    # Create numeric pound columns (keep original pence columns intact)
    # Divide by 100.0 to keep them floats (numeric)
    df["price"] = pd.to_numeric(df["price_pence"], errors="coerce") / 100.0
    df["previous_price"] = pd.to_numeric(df["previous_price_pence"], errors="coerce") / 100.0

    # Select only the columns the user asked for plus derived pound columns for nicer display & download
    out = df.loc[:, ["nm", "price_pence", "previous_price_pence", "price", "previous_price"]].copy()
    return out

details_df = get_vmpp_details(vmpp_df, sel_bnf_code)

if details_df.empty:
    st.warning("No matching detail rows found in vmpp_df for this BNF code.")
else:
    st.write(f"{len(details_df)} matching rows from `vmpp_df`")

    # Prepare a display-only styled DataFrame: format price columns with gbp, keep underlying numeric types
    display_df = details_df.copy()
    display_style = display_df.style.format({
        "price": gbp,
        "previous_price": gbp
    })

    # Show only columns in the desired order and friendly names
    display_style = display_style.hide_index().set_table_attributes("style='width:100%'")
    st.dataframe(display_style, use_container_width=True)

    # CSV download: include both original pence and derived price columns
    csv = details_df.to_csv(index=False)
    st.download_button(
        label="Download details as CSV",
        data=csv,
        file_name=f"vmpp_details_{sel_bnf_code}.csv",
        mime="text/csv"
    )
