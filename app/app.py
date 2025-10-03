import os
from datetime import date
from typing import Dict, Optional

import pandas as pd
import requests
import streamlit as st

st.set_page_config(page_title="DataWeaver Dashboard", layout="wide")

API_URL = os.getenv("API_URL", "http://localhost:8000")
CATEGORY_OPTIONS = ["electronics", "home", "beauty", "sports", "toys"]


def api_call(
    path: str,
    *,
    params: Optional[Dict] = None,
    payload: Optional[Dict] = None,
    method: str = "GET",
):
    """Wrapper around the FastAPI service with friendly error feedback."""
    url = f"{API_URL}{path}"
    try:
        if method.upper() == "POST":
            response = requests.post(url, json=payload, timeout=60)
        else:
            response = requests.get(url, params=params, timeout=60)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.HTTPError as http_err:
        detail = http_err.response.text if http_err.response is not None else str(http_err)
        st.error(f"API error: {detail}")
    except requests.exceptions.ConnectionError:
        st.error("Unable to reach the API. Start it locally or update API_URL.")
    except requests.exceptions.Timeout:
        st.error("Request timed out. Please retry.")
    except requests.RequestException as exc:
        st.error(f"Unexpected API error: {exc}")
    return None


tab_ask, tab_review, tab_dashboard = st.tabs(
    ["Ask (Business to SQL)", "Review SQL", "Generate Dashboard"]
)


def render_ask_tab() -> None:
    with tab_ask:
        st.caption("Turn business questions into SQL, run them, and inspect AI reviews.")
        default_question = "Top 5 electronics products by revenue in Q3"
        question = st.text_input("Enter business question", default_question)
        if st.button("Generate & Run", key="ask_run"):
            if not question.strip():
                st.warning("Please enter a question first.")
                return
            with st.spinner("Generating SQL and running query..."):
                resp = api_call("/execute", params={"q": question})
            if not resp:
                return
            st.subheader("Generated SQL")
            st.code(resp.get("sql", ""), language="sql")
            rows = resp.get("rows", [])
            df = pd.DataFrame(rows)
            if df.empty:
                st.warning("No rows returned for this question.")
            else:
                st.dataframe(df, use_container_width=True)
                if {"product_title", "revenue"}.issubset(df.columns):
                    chart_df = df.set_index("product_title")["revenue"]
                    st.bar_chart(chart_df, use_container_width=True)
            review_payload = resp.get("review")
            if review_payload:
                st.subheader("AI Review")
                st.json(review_payload)


def render_review_tab() -> None:
    with tab_review:
        st.caption("Validate SQL snippets or NL prompts before you run them.")
        default_question = "Top 10 beauty products in Q2"
        default_sql = (
            "SELECT category, SUM(revenue) AS revenue\n"
            "FROM daily_product_sales\n"
            "GROUP BY category\n"
            "ORDER BY revenue DESC\n"
            "LIMIT 5;"
        )
        col_question, col_sql = st.columns(2)
        question = col_question.text_area(
            "Business question (optional context)", default_question, height=160
        )
        sql_text = col_sql.text_area("SQL to review", default_sql, height=160)
        if st.button("Review", key="review_sql"):
            if not sql_text.strip():
                st.warning("Provide SQL to review.")
                return
            payload = {"q": question, "sql": sql_text}
            with st.spinner("Reviewing SQL..."):
                resp = api_call("/review", payload=payload, method="POST")
            if resp:
                st.json(resp)
                fixed_sql = resp.get("fixed_sql") if isinstance(resp, dict) else None
                if fixed_sql:
                    st.subheader("Suggested Fix")
                    st.code(fixed_sql, language="sql")


def render_dashboard_tab() -> None:
    with tab_dashboard:
        st.subheader("Auto-Generated Dashboard")
        st.caption("Filter and visualize sales data with live queries against the API.")

        with st.form("dashboard_filters"):
            selected_categories = st.multiselect(
                "Filter by category",
                options=CATEGORY_OPTIONS,
                default=CATEGORY_OPTIONS,
            )
            col_start, col_end = st.columns(2)
            with col_start:
                start_date = st.date_input("Start date", date(2024, 1, 1))
            with col_end:
                end_date = st.date_input("End date", date(2024, 12, 31))
            refresh = st.form_submit_button("Refresh Dashboard")

        if not refresh:
            return

        if start_date > end_date:
            st.error("Start date must be before end date.")
            return

        active_categories = selected_categories or CATEGORY_OPTIONS
        quoted = ", ".join(f"'{cat}'" for cat in active_categories)
        sql = (
            "SELECT product_title, category, day, units, revenue\n"
            "FROM daily_product_sales\n"
            f"WHERE category IN ({quoted}) AND day BETWEEN CAST('{start_date}' AS DATE) "
            f"AND CAST('{end_date}' AS DATE)\n"
            "ORDER BY day ASC, revenue DESC\n"
            "LIMIT 1000;"
        )

        with st.spinner("Running dashboard query..."):
            resp = api_call("/execute", params={"q": sql})

        if not resp:
            return

        df = pd.DataFrame(resp.get("rows", []))
        if df.empty:
            st.warning("No data available for the selected filters.")
            return

        if "day" in df.columns:
            df["day"] = pd.to_datetime(df["day"])

        st.write("### Result Sample")
        st.dataframe(df.head(25), use_container_width=True)

        if {"category", "revenue"}.issubset(df.columns):
            revenue_by_category = (
                df.groupby("category")["revenue"].sum().sort_values(ascending=False).reset_index()
            )
            st.bar_chart(
                revenue_by_category.set_index("category")["revenue"],
                use_container_width=True,
            )
            st.caption("Revenue by category")

        if {"day", "units"}.issubset(df.columns):
            units_over_time = df.groupby("day")["units"].sum().sort_index()
            st.line_chart(units_over_time, use_container_width=True)
            st.caption("Units sold over time")

        if {"product_title", "revenue"}.issubset(df.columns):
            top_products = (
                df.groupby("product_title")["revenue"].sum().sort_values(ascending=False).head(10)
            )
            st.write("### Top Products by Revenue")
            st.bar_chart(top_products, use_container_width=True)

        review_payload = resp.get("review")
        if review_payload:
            with st.expander("SQL review details", expanded=False):
                st.json(review_payload)

        st.subheader("Planned Enhancements")
        st.info(
            "Cohort analysis and geo heatmaps will appear here once customer and location tables are joined."
        )


def main() -> None:
    render_ask_tab()
    render_review_tab()
    render_dashboard_tab()


if __name__ == "__main__":
    main()
