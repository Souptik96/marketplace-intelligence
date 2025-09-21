import pandas as pd, duckdb, streamlit as st

st.set_page_config(page_title="🛒 Marketplace Intelligence", layout="wide")

@st.cache_data
def load_df():
    import os
    import pandas as pd
    if not os.path.exists("data/daily_product_sales.csv"):
        st.warning("No CSV found. Generate via synthetic_generator.py or use the API directly.")
        return pd.DataFrame(columns=["product_title","category","day","units","revenue"])
    df = pd.read_csv("data/daily_product_sales.csv", parse_dates=["day"])
    df["day"] = df["day"].dt.date
    return df

con = duckdb.connect()
con.register("daily_product_sales", load_df())

q = st.text_input("Ask", "Top 3 selling electronics products in Q3")
if st.button("Run"):
    ql = q.lower(); topn=3
    for tok in q.split():
        if tok.isdigit(): topn=int(tok); break
    cat = next((c for c in ["electronics","home","beauty","sports","toys"] if c in ql), None)
    where=[]
    if cat: where.append(f"category = '{cat}'")
    if "q3" in ql:
        where.append("CAST(day AS DATE) BETWEEN DATE '2024-07-01' AND DATE '2024-09-30'")
    where_sql = ("WHERE "+" AND ".join(where)) if where else ""
    sql=f"""
SELECT product_title, category, SUM(units) AS units, SUM(revenue) AS revenue
FROM daily_product_sales
{where_sql}
GROUP BY 1,2
ORDER BY revenue DESC
LIMIT {topn};
"""
    st.code(sql, language="sql")
    df = con.execute(sql).df()
    st.dataframe(df, width="stretch")
