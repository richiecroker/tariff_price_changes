import streamlit as st
import pandas as pd
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode, JsCode
from datetime import datetime
import yaml
import os

from db import get_duckdb_connection, get_latest_dates, _bq_client, _latest_bq_month

import logging
logging.basicConfig(level=logging.INFO)

base_dir = os.path.dirname(__file__)

# Set wide layout
st.set_page_config(layout="wide")

st.image("content/OpenPrescribing.svg")
st.image("content/OpenPrescribing.svg")
st.info(
    """##### Hello!  This is a **very** early prototype of estimating the impact of drug tariff changes.  
Please let us know what you think, and what you'd like to see.  Email us at [bennett@phc.ox.ac.uk](mailto:bennett@phc.ox.ac.uk)"""
)

conn = get_duckdb_connection()

vmpp_df = conn.execute("""
    SELECT * FROM vmpp_tariff_changes
    """).df()


dates = get_latest_dates()
max_rx_date = dates["prescribing"]
max_tariff_date  = dates["tariff"]

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

    st.header("Organisation Filter")
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

    st.header("Tariff Filter")
    tariff_cat_opts = ["(All)"] + sorted(conn.execute("SELECT DISTINCT tariff_cat FROM tariff_price_changes ORDER BY tariff_cat").df()["tariff_cat"].dropna().tolist())
    sel_tariff_cat = st.multiselect("DT Category", tariff_cat_opts, key="sel_tariff_cat")

    sort_option = st.radio(
        "Sort by",
        ["Largest Increases", "Largest Reductions"],
        key="sort_option"
    )

st.markdown (f"#### Total changes for {datetime.strptime(max_tariff_date, '%Y-%m-%d').strftime('%B %Y')}")

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


conn.register("selected_practices", df_selected)


filtered_df = conn.execute("""
    SELECT
        rx.bnf_name,
        rx.bnf_code,
        dt.tariff_cat,
        SUM(rx.quantity * dt.price_diff_pu * dt.is_max_price_diff_pu) AS price_difference
    FROM prescribing AS rx
    INNER JOIN tariff_price_changes AS dt
    ON rx.bnf_code = dt.bnf_code
    INNER JOIN selected_practices sp ON rx.practice = sp.practice_code
    GROUP BY rx.bnf_name, rx.bnf_code, dt.tariff_cat
    """).df()

conn.unregister("selected_practices")

if sel_tariff_cat:
    filtered_df = filtered_df[filtered_df["tariff_cat"].isin(sel_tariff_cat)]

# Calculate and display total price change
total_difference = filtered_df["price_difference"].sum()




st.markdown(f"### Total estimated monthly price difference: {gbp(total_difference)}")

st.markdown ("### Breakdown by presentation")


st.info("ℹ️ To see details on changes to individual packs, click on the arrow")
st.markdown("""
<style>
details {
    border: none !important;
    box-shadow: none !important;
}
</style>
""", unsafe_allow_html=True)

if "page" not in st.session_state:
    st.session_state.page = 0

if sort_option == "Largest Increases":
    sorted_df = filtered_df.sort_values("price_difference", ascending=False)
else:
    sorted_df = filtered_df.sort_values("price_difference", ascending=True)

total_pages = max(1, (len(sorted_df) - 1) // 20 + 1)
if st.session_state.page >= total_pages:
    st.session_state.page = 0
page = st.session_state.page
page20 = sorted_df.iloc[page * 20:(page + 1) * 20]

for _, row in page20.iterrows():
    colour = "red" if row["price_difference"] > 0 else "green"
    label = f":{colour}[{row['bnf_name']}: {gbp2f(row['price_difference'])}]"
    vmpp_details = vmpp_df[vmpp_df["bnf_code"] == row["bnf_code"]].copy()
    with st.expander(label):
        display_df = vmpp_details[["nm", "price_pence", "previous_price_pence", "tariff_category"]].copy()
        display_df["price_pence"] = (pd.to_numeric(display_df["price_pence"], errors="coerce") / 100).apply(gbp2f)
        display_df["previous_price_pence"] = (pd.to_numeric(display_df["previous_price_pence"], errors="coerce") / 100).apply(gbp2f)
        display_df.columns = ["Name", "Price", "Previous Price", "DT Category"]
        st.dataframe(display_df, hide_index=True, use_container_width=True)

col_prev, col_info, col_next = st.columns([1, 2, 1])
with col_prev:
    if st.button("← Previous", disabled=page == 0):
        st.session_state.page -= 1
        st.rerun()
with col_info:
    st.markdown(f"<div style='text-align:center'>Page {page + 1} of {total_pages}</div>", unsafe_allow_html=True)
with col_next:
    if st.button("Next →", disabled=page >= total_pages - 1):
        st.session_state.page += 1
        st.rerun()

# ── Changelog ─────────────────────────────────────────────────────────────────

st.divider()

with st.expander("Click here to read our methodology", icon=":material/quick_reference:"):
    with open("content/methodology.md") as f:
        st.markdown(f.read())

with open("content/changelog.yaml") as f:
    changelog = yaml.safe_load(f)

with st.expander("Click to see changelog", icon=":material/history:"):
    for entry in reversed(changelog):
        st.markdown(f"**{entry['date']}** — {entry['change']} *({entry['person']})*")
