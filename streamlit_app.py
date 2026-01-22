import streamlit as st
import pandas as pd

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

# Aggregation controls
group_col = st.selectbox("Group by", df.columns)
value_col = st.selectbox("Aggregate column", df.columns)

# Aggregate
agg = (
    df.groupby(group_col)[value_col]
      .mean()
      .reset_index(name="avg_value")
)

st.subheader("Aggregation (mean)")
st.dataframe(agg)

# Drilldown
selected = st.selectbox("Drill into group", agg[group_col])
drill_df = df[df[group_col] == selected]

st.subheader(f"Rows for {group_col} = {selected}")
st.dataframe(drill_df)