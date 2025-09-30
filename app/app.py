# app/app.py
import os
import json
import requests
import pandas as pd
import streamlit as st

st.set_page_config(page_title="DataWeaver & Dash", layout="wide")
API = os.getenv("API_URL", "http://localhost:8000")

def get(path, params=None):
    r = requests.get(API + path, params=params, timeout=60)
    r.raise_for_status()
    return r.json()

def post(path, payload):
    r = requests.post(API + path, json=payload, timeout=60)
    r.raise_for_status()
    return r.json()

tab1, tab2, tab3 = st.tabs(["💬 Ask (NL→SQL→Run)", "🧑‍⚖️ Review", "📊 Dashboard"])

with tab1:
    q = st.text_input("Ask a business question", "Top 5 electronics by revenue in Q3")
    if st.button("Run", key="ask"):
        resp = get("/execute", {"q": q})
        st.subheader("SQL")
        st.code(resp["sql"], language="sql")
        df = pd.DataFrame(resp["rows"])
        st.subheader("Results")
        # Removed width="stretch" to fix the TypeError
        st.dataframe(df)
        if {"product_title", "revenue"}.issubset(df.columns):
            st.subheader("Revenue Chart")
            st.bar_chart(df.set_index("product_title")["revenue"])
        st.caption("Citations: daily_product_sales")
        st.subheader("Reviewer JSON")
        st.json(resp["review"])

with tab2:
    colA, colB = st.columns(2)
    q2 = colA.text_area("Question (context)", "Top 10 beauty products in Q2")
    sql2 = colB.text_area("SQL to review", "SELECT * FROM daily_product_sales LIMIT 100;")
    if st.button("Review", key="rev"):
        rev = post("/review", {"q": q2, "sql": sql2})
        st.subheader("Review")
        st.json(rev)
        if isinstance(rev, dict) and rev.get("fixed_sql"):
            st.subheader("Suggested fix")
            st.code(rev["fixed_sql"], language="sql")

with tab3:
    st.write("Dashboards mix **real** charts and **placeholders** when joins are missing.")
    try:
        df = pd.read_csv("data/daily_product_sales.csv", parse_dates=["day"])
        s = df.groupby("category", as_index=False)["revenue"].sum().sort_values("revenue", ascending=False)
        st.subheader("Revenue by Category (real)")
        st.bar_chart(s.set_index("category")["revenue"])
        t = df.copy()
        t["month"] = t["day"].dt.to_period("M").astype(str)
        m = t.groupby(["month", "category"], as_index=False)["revenue"].sum()
        st.subheader("Monthly Revenue (real)")
        st.line_chart(m.pivot(index="month", columns="category", values="revenue").fillna(0))
    except Exception as e:
        st.info(f"Placeholder: needs data/daily_product_sales.csv. Error: {e}")

    st.subheader("Customer Cohort Retention (placeholder)")
    st.info("Would show D30 retention. Needs: customers(id, join_date), sessions(customer_id, day).")

    st.subheader("Geo Heatmap (placeholder)")
    st.info("Would show revenue by country. Needs: dim_geo(country_code), mapping to orders.")