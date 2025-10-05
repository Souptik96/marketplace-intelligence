import os
import io
import json
import re
from datetime import date
from typing import Any, Dict, List, Optional

import duckdb
import pandas as pd
import requests
import streamlit as st
import chardet

CACHE_ROOT = "/tmp/cache"
os.environ.setdefault("TRANSFORMERS_CACHE", os.path.join(CACHE_ROOT, "transformers"))
os.environ.setdefault("HF_HOME", os.path.join(CACHE_ROOT, "hf"))
os.environ.setdefault("HF_HUB_CACHE", os.path.join(CACHE_ROOT, "hf", "hub"))
os.environ.setdefault("XDG_CACHE_HOME", CACHE_ROOT)
os.makedirs(CACHE_ROOT, exist_ok=True)

st.set_page_config(page_title="Marketplace Intelligence — Upload & Query", layout="wide")

REMOTE_ERROR_HINT = (
    "Unable to reach the remote API. Falling back to in-process mode. "
    "If you expect to use a remote backend, set the API_URL environment variable."
)
MISSING_MODEL_HINT = (
    "Missing model configuration. Set FIREWORKS_API_KEY or HF_API_KEY along with LLM_MODEL_GEN and LLM_MODEL_REV."
)
PROMPT_DASHBOARD = (
    "You are a data visualization expert. Based on the following data columns, suggest the best single chart to build. "
    "Your response must be a single JSON object with \"chart_type\" (choose from \"bar\", \"line\", \"scatter\"), "
    "\"x_column\", and \"y_column\".\n\nColumns: {column_info}\nJSON:"
)


def _sanitize(name: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_]", "_", name).lower().strip("_")
    return cleaned or "table"


@st.cache_data(show_spinner=False)
def _load_file(file_bytes: bytes, filename: str) -> pd.DataFrame:
    name = filename.lower()
    buffer = io.BytesIO(file_bytes)
    if name.endswith((".xlsx", ".xls")):
        return pd.read_excel(buffer)
    if name.endswith(".jsonl"):
        buffer.seek(0)
        return pd.read_json(buffer, lines=True)
    if name.endswith((".txt", ".tsv")):
        buffer.seek(0)
        return pd.read_csv(buffer, sep=None, engine="python")
    try:
        buffer.seek(0)
        return pd.read_csv(buffer, sep=None, engine="python")
    except Exception:
        buffer.seek(0)
        enc = chardet.detect(file_bytes).get("encoding") or "utf-8"
        return pd.read_csv(buffer, sep=None, engine="python", encoding=enc)


def _register_tables(dfs: Dict[str, pd.DataFrame]) -> Optional[duckdb.DuckDBPyConnection]:
    if not dfs:
        return None
    con = duckdb.connect()
    for table, df in dfs.items():
        con.register(table, df)
    return con


def _schema_for_prompt(con: Optional[duckdb.DuckDBPyConnection]) -> str:
    if con is None:
        return ""
    rows = con.execute(
        """
        SELECT table_name, column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = 'main'
        ORDER BY table_name, ordinal_position
        """
    ).fetchall()
    layout: Dict[str, List[str]] = {}
    for table, column, dtype in rows:
        layout.setdefault(table, []).append(f"{column} {dtype}")
    return "\n".join([f"Table {tbl}({', '.join(cols)})." for tbl, cols in layout.items()])


def _enforce_limits(sql: str) -> str:
    statement = sql.strip().rstrip(";")
    lowered = statement.lower()
    if not (lowered.startswith("select") or lowered.startswith("with")):
        raise ValueError("Only SELECT/CTE statements are allowed.")
    if " limit " not in lowered:
        statement += " LIMIT 200"
    return statement


def _expected_tables(sql: str) -> List[str]:
    tables = re.findall(r"(?i)\bfrom\s+([\w\.]+)", sql)
    tables += re.findall(r"(?i)\bjoin\s+([\w\.]+)", sql)
    sanitized = {_sanitize(name.split(".")[-1]) for name in tables}
    return sorted(filter(None, sanitized))


def _provider_has_creds(provider: str) -> bool:
    if provider == "fireworks":
        return bool(os.getenv("FIREWORKS_API_KEY") or st.secrets.get("FIREWORKS_API_KEY"))
    return bool(os.getenv("HF_API_KEY") or st.secrets.get("HF_API_KEY"))


def _call_llm(provider: str, model: str, prompt: str) -> str:
    if not model:
        raise RuntimeError("Model name is required.")
    if provider == "fireworks":
        key = os.getenv("FIREWORKS_API_KEY", st.secrets.get("FIREWORKS_API_KEY", ""))
        if not key:
            raise RuntimeError("FIREWORKS_API_KEY not set")
        payload = {
            "model": model,
            "prompt": prompt,
            "max_tokens": 400,
            "temperature": 0.0,
        }
        headers = {"Authorization": f"Bearer {key}"}
        resp = requests.post(
            "https://api.fireworks.ai/inference/v1/completions",
            json=payload,
            headers=headers,
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        choices = data.get("choices") or []
        if choices:
            return (choices[0].get("text") or choices[0].get("message", {}).get("content", "")).strip()
        return json.dumps(data)
    key = os.getenv("HF_API_KEY", st.secrets.get("HF_API_KEY", ""))
    if not key:
        raise RuntimeError("HF_API_KEY not set")
    payload = {"inputs": prompt, "parameters": {"max_new_tokens": 400, "temperature": 0.0}}
    headers = {"Authorization": f"Bearer {key}", "x-use-cache": "false"}
    resp = requests.post(
        f"https://api-inference.huggingface.co/models/{model}",
        json=payload,
        headers=headers,
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    if isinstance(data, list) and data and "generated_text" in data[0]:
        return data[0]["generated_text"]
    if isinstance(data, dict) and "generated_text" in data:
        return data["generated_text"]
    return json.dumps(data)


def _extract_sql_from_text(text: str) -> str:
    fenced = re.search(r"`sql\s*(.*?)`", text, flags=re.I | re.S)
    if fenced:
        return fenced.group(1).strip()
    generic = re.search(r"`(.*?)`", text, flags=re.S)
    if generic:
        block = generic.group(1).strip()
        if re.search(r"(?is)\bselect\b", block):
            return block
    fallback = re.search(r"(?is)\b(select|with)\b.*", text)
    if fallback:
        return fallback.group(0).strip()
    return text.strip()


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    match = re.search(r"\{.*\}", text, flags=re.S)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def _gen_sql(question: str, schema: str, provider: str, model: str, api_url: str) -> str:
    if not question.strip():
        raise ValueError("Question cannot be empty.")
    prompt = (
        "You convert business questions into DuckDB SQL ONLY.\n"
        "Use these tables:\n"
        f"{schema if schema else 'No tables were provided.'}\n"
        "Return only SQL without commentary.\n"
        f"Question: {question}\nSQL:"
    )
    if api_url:
        try:
            resp = requests.post(
                api_url.rstrip('/') + '/nl2sql',
                json={"q": question, "schema": schema},
                timeout=60,
            )
            resp.raise_for_status()
            payload = resp.json()
            candidate = payload.get("sql") if isinstance(payload, dict) else str(payload)
            return _enforce_limits(candidate)
        except Exception:
            st.warning(REMOTE_ERROR_HINT)
    llm_output = _call_llm(provider, model, prompt)
    return _enforce_limits(_extract_sql_from_text(llm_output))


def _basic_review(question: str, sql: str, rows: Optional[List[Dict[str, Any]]]) -> Dict[str, Any]:
    lowered = " ".join(sql.lower().split())
    analysis = {
        "has_limit": " limit " in f" {lowered} ",
        "targets_tables": [
            t for t in ("daily_product_sales", "orders", "products") if t in lowered
        ],
        "has_group_by": "group by" in lowered,
        "has_aggregation": any(
            token in lowered for token in ("sum(", "avg(", "count(", "min(", "max(", "group by")
        ),
    }
    issues: List[str] = []
    warnings: List[str] = []
    stripped = lowered.strip()
    if not (stripped.startswith("select") or stripped.startswith("with")):
        issues.append("Only SELECT/CTE statements are supported in this interface.")
    forbidden = [kw for kw in ("insert", "update", "delete", "drop", "alter") if kw in lowered]
    if forbidden:
        issues.append(f"Detected disallowed keywords: {', '.join(forbidden)}")
    if not analysis["has_limit"]:
        warnings.append("Add LIMIT to keep dashboards responsive.")
    if not analysis["targets_tables"]:
        warnings.append("Query does not reference a known table.")
    if rows is not None and len(rows) == 0:
        warnings.append("Query returned zero rows for the selected filters.")
    summary = "SQL validated successfully."
    if issues:
        summary = "SQL failed validation due to critical issues."
    elif warnings:
        summary = "SQL is valid but review the warnings before finalizing."
    return {
        "valid": not issues,
        "summary": summary,
        "issues": issues,
        "warnings": warnings,
        "analysis": analysis,
        "question": question,
    }


def _review_sql(question: str, sql: str, schema: str, provider: str, model: str) -> Dict[str, Any]:
    prompt = (
        "You are a senior BI reviewer. Assess SQL for intent, correctness, and produce fixes when needed.\n"
        "Schema:\n"
        f"{schema if schema else 'No schema provided.'}\n"
        f"Question: {question or 'N/A'}\n"
        "SQL:\n"
        f"{sql}\n"
        "Return JSON with keys reasoning, ok (true/false), fixed_sql."
    )
    try:
        llm_response = _call_llm(provider, model, prompt)
        parsed = _extract_json(llm_response)
        if parsed:
            return parsed
        st.info("Review model returned non-JSON output; using heuristic checks instead.")
    except Exception as exc:
        st.info(f"Review fallback: {exc}")
    return _basic_review(question, sql, None)


def _execute_sql(con: duckdb.DuckDBPyConnection, sql: str) -> pd.DataFrame:
    statement = _enforce_limits(sql)
    return con.execute(statement).df()


def _render_placeholder(summary: str, expected: List[str]) -> None:
    expected_text = ", ".join(expected) if expected else "review your uploaded tables."
    st.info(f"{summary}\nExpected tables: {expected_text}")


def _render_charts(df: pd.DataFrame) -> None:
    if {"product_title", "revenue"}.issubset(df.columns):
        st.write("### Revenue by Product")
        st.bar_chart(df.set_index("product_title")["revenue"], use_container_width=True)
    date_cols = [col for col in df.columns if pd.api.types.is_datetime64_any_dtype(df[col])]
    if date_cols and "revenue" in df.columns:
        st.write("### Revenue Over Time")
        time_df = df.groupby(date_cols[0])["revenue"].sum().sort_index()
        st.line_chart(time_df, use_container_width=True)
    numeric_cols = df.select_dtypes(include="number").columns.tolist()
    if len(numeric_cols) >= 2:
        st.write("### Numeric Overview")
        st.area_chart(df[numeric_cols[:2]], use_container_width=True)


def _suggest_chart(df: pd.DataFrame, provider: str, model: str) -> Optional[Dict[str, Any]]:
    if df.empty or not _provider_has_creds(provider):
        return None
    column_info = ", ".join(f"{col} ({df[col].dtype})" for col in df.columns)
    prompt = PROMPT_DASHBOARD.format(column_info=column_info)
    try:
        raw = _call_llm(provider, model, prompt)
        parsed = _extract_json(raw)
        if isinstance(parsed, dict):
            chart_type = parsed.get("chart_type")
            if chart_type in {"bar", "line", "scatter"}:
                return parsed
    except Exception as exc:
        st.info(f"Chart suggestion fallback: {exc}")
    return None


uploaded_files = st.sidebar.file_uploader(
    "Upload CSV/XLSX/TXT/JSONL (multi)",
    type=["csv", "xlsx", "xls", "tsv", "txt", "jsonl"],
    accept_multiple_files=True,
)

dfs: Dict[str, pd.DataFrame] = {}
if uploaded_files:
    for file in uploaded_files:
        data = file.getvalue()
        if len(data) > 50 * 1024 * 1024:
            st.warning(f"{file.name} skipped (exceeds 50 MB limit).")
            continue
        df = _load_file(data, file.name)
        table_name = _sanitize(file.name.rsplit(".", 1)[0])
        while table_name in dfs:
            table_name += "_u"
        dfs[table_name] = df
else:
    try:
        sample = pd.read_csv("data/daily_product_sales.csv", parse_dates=["day"])
        sample["day"] = sample["day"].dt.date
        dfs["daily_product_sales"] = sample
    except Exception:
        dfs = {}

con = _register_tables(dfs)
schema = _schema_for_prompt(con)

st.sidebar.caption(
    "Tables registered: " + (", ".join(dfs.keys()) if dfs else "none — upload to begin")
)

provider_default = os.getenv("LLM_PROVIDER", "fireworks").lower()
provider_choices = ["fireworks", "hf"]
provider_index = provider_choices.index(provider_default) if provider_default in provider_choices else 0
provider = st.sidebar.selectbox("Provider", provider_choices, index=provider_index)

gen_default = os.getenv(
    "LLM_MODEL_GEN",
    "accounts/fireworks/models/qwen3-coder-30b-a3b-instruct"
    if provider == "fireworks"
    else "Qwen/Qwen2.5-1.5B-Instruct",
)
rev_default = os.getenv(
    "LLM_MODEL_REV",
    "accounts/fireworks/models/qwen3-coder-30b-a3b-instruct"
    if provider == "fireworks"
    else "Qwen/Qwen2.5-Coder-1.5B-Instruct",
)

gen_model = st.sidebar.text_input("Generation model", value=gen_default)
rev_model = st.sidebar.text_input("Review model", value=rev_default)
api_url = st.sidebar.text_input(
    "Optional backend API base URL",
    value=os.getenv("API_URL", ""),
    help="Set only if you have a compatible API that understands the uploaded schema.",
)

st.title("Marketplace Intelligence — Upload → NL→SQL → Dashboard")
if not dfs:
    st.warning("Upload at least one file to begin querying.")

with st.sidebar.expander("Schema", expanded=False):
    if schema:
        st.text(schema)
    else:
        st.info("No tables available yet.")

if con is None:
    st.stop()

st.session_state.setdefault("ask_results", None)


def _handle_query(question: str) -> Dict[str, Any]:
    result: Dict[str, Any] = {"question": question}
    use_remote = bool(api_url) and not uploaded_files
    sql = None
    chart = None
    error: Optional[str] = None
    df: pd.DataFrame = pd.DataFrame()
    review_payload: Optional[Dict[str, Any]] = None

    if use_remote:
        try:
            payload = requests.get(
                api_url.rstrip('/') + '/execute',
                params={"q": question},
                timeout=60,
            )
            payload.raise_for_status()
            data = payload.json()
            sql = data.get("sql", "")
            df = pd.DataFrame(data.get("rows", []))
            review_payload = data.get("review")
            chart = data.get("chart_suggestion")
            error = None if not data.get("error") else data["error"]
        except Exception as exc:
            st.warning(f"Remote execution failed ({exc}). Falling back to local mode.")
            use_remote = False

    if not use_remote:
        sql = _gen_sql(question, schema, provider, gen_model, "")
        try:
            df = _execute_sql(con, sql)
        except Exception as exc:
            df = pd.DataFrame()
            error = str(exc)
        if df.empty and error is None:
            error = "Query executed but returned no rows."
        try:
            review_payload = _review_sql(question, sql, schema, provider, rev_model)
        except Exception as exc:
            review_payload = {"summary": f"Review failed: {exc}"}
        if error is None:
            chart = _suggest_chart(df, provider, gen_model)

    result.update(
        {
            "sql": sql or "",
            "df": df,
            "review": review_payload,
            "error": error,
            "expected": _expected_tables(sql or ""),
            "chart": chart,
        }
    )
    return result


tabs = st.tabs(["Ask (Business to SQL)", "Review SQL", "Generate Dashboard"])

with tabs[0]:
    default_question = "Top 5 electronics products by revenue in Q3"
    question = st.text_input("Enter business question", default_question)
    if st.button("Generate & Run", key="ask_run"):
        if not question.strip():
            st.warning("Please enter a question first.")
        else:
            with st.spinner("Generating SQL and executing..."):
                st.session_state["ask_results"] = _handle_query(question)
    results = st.session_state.get("ask_results")
    if results:
        st.subheader("Generated SQL")
        st.code(results.get("sql", ""), language="sql")
        if results.get("error"):
            st.error(results["error"])
            _render_placeholder(
                "Placeholder: Unable to execute with current tables.",
                results.get("expected", []),
            )
        else:
            df = results.get("df", pd.DataFrame())
            if df.empty:
                st.warning("No rows returned for this question.")
                _render_placeholder(
                    "Placeholder: Result set was empty. Upload additional tables or adjust filters.",
                    results.get("expected", []),
                )
            else:
                st.dataframe(df, use_container_width=True)
                chart = results.get("chart")
                if isinstance(chart, dict):
                    st.subheader("Suggested Chart")
                    chart_type = chart.get("chart_type")
                    x_col = chart.get("x_column")
                    y_col = chart.get("y_column")
                    if chart_type == "bar" and x_col in df.columns and y_col in df.columns:
                        st.bar_chart(df.set_index(x_col)[y_col], use_container_width=True)
                    elif chart_type == "line" and x_col in df.columns and y_col in df.columns:
                        st.line_chart(df.set_index(x_col)[y_col], use_container_width=True)
                    elif chart_type == "scatter" and x_col in df.columns and y_col in df.columns:
                        st.scatter_chart(df[[x_col, y_col]], use_container_width=True)
                    else:
                        st.caption("Chart suggestion incomplete; displaying standard summaries.")
                _render_charts(df)
        review_payload = results.get("review")
        if review_payload:
            st.subheader("AI Review")
            st.json(review_payload)

with tabs[1]:
    st.caption("Validate SQL snippets or natural language prompts before execution.")
    review_question = st.text_area("Optional context", "Top 10 beauty products in Q2", height=100)
    review_sql = st.text_area(
        "SQL to review",
        "SELECT category, SUM(revenue) AS revenue\nFROM daily_product_sales\nGROUP BY category\nORDER BY revenue DESC\nLIMIT 5;",
        height=160,
    )
    if st.button("Review", key="review_sql_button"):
        if not review_sql.strip():
            st.warning("Provide SQL to review.")
        else:
            with st.spinner("Reviewing SQL..."):
                payload = _review_sql(review_question, review_sql, schema, provider, rev_model)
            st.json(payload)

with tabs[2]:
    st.subheader("Auto-Generated Dashboard")
    st.caption("Filter and visualize sales data with live queries against the in-memory DuckDB instance.")
    if "daily_product_sales" not in dfs:
        _render_placeholder(
            "Placeholder: Upload a table with day/category/units/revenue to enable this dashboard.",
            ["daily_product_sales"],
        )
    else:
        base_df = dfs["daily_product_sales"]
        required_cols = {"category", "day", "revenue"}
        if not required_cols.issubset(base_df.columns):
            _render_placeholder(
                "Placeholder: Upload a table containing category, day, and revenue columns to enable this dashboard.",
                ["daily_product_sales"],
            )
        else:
            available_categories = sorted(base_df["category"].dropna().unique())
            default_start = pd.to_datetime(base_df["day"].min()) if "day" in base_df.columns else pd.Timestamp("2024-01-01")
            default_end = pd.to_datetime(base_df["day"].max()) if "day" in base_df.columns else pd.Timestamp("2024-12-31")
            with st.form("dashboard_filters"):
                selected_categories = st.multiselect(
                    "Filter by category",
                    options=available_categories,
                    default=available_categories,
                )
                col_start, col_end = st.columns(2)
                with col_start:
                    start_date = st.date_input("Start date", default_start.date())
                with col_end:
                    end_date = st.date_input("End date", default_end.date())
                refresh = st.form_submit_button("Refresh Dashboard")
            if refresh:
                filters = "\n    AND category IN ({})".format(
                    ", ".join(f"'{c}'" for c in selected_categories)
                ) if selected_categories else ""
                dash_sql = f"""
SELECT product_title, category, day, units, revenue
FROM daily_product_sales
WHERE day BETWEEN DATE '{start_date}' AND DATE '{end_date}'{filters}
ORDER BY day ASC, revenue DESC
LIMIT 200;
"""
                try:
                    dash_df = _execute_sql(con, dash_sql)
                    if dash_df.empty:
                        st.warning("No data available for the selected filters.")
                        _render_placeholder(
                            "Placeholder: Upload more granular sales data to populate this dashboard.",
                            ["daily_product_sales"],
                        )
                    else:
                        st.dataframe(dash_df.head(50), use_container_width=True)
                        _render_charts(dash_df)
                except Exception as exc:
                    st.error(f"Dashboard query failed: {exc}")
                    _render_placeholder(
                        "Placeholder: Dashboard requires tables with day/category/units/revenue columns.",
                        ["daily_product_sales"],
                    )
