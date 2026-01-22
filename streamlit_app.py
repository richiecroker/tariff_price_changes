import streamlit as st
import pandas as pd

st.title("Price Change Demo")

# 1. Load CSV from root
df = pd.read_csv("pricechangedemo.csv")

# 2. Show raw data
st.subheader("Raw data")
st.dataframe(df)

# 3. Pick group + value column
group_col = st.selectbox("Group by", df.columns)
value_col = st.selectbox("Aggregate column", df.columns)

# 4. Aggregate
agg = (
    df.groupby(group_col)[value_col]
      .mean()
      .reset_index(name="avg_value")
)

st.subheader("Aggregation (mean)")
st.dataframe(agg)

# 5. Drilldown
selected = st.selectbox("Drill into group", agg[group_col])

drill_df = df[df[group_col] == selected]

st.subheader(f"Rows for {group_col} = {selected}")
st.dataframe(drill_df)