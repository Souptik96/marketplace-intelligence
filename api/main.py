# api/main.py
import os
import time
import json
import logging
import re
from typing import List, Dict
from fastapi import FastAPI, Query
from pydantic import BaseModel
import duckdb
import pandas as pd

from .providers import llm_call, extract_sql, extract_json
from .sql_safety import sanitize  # Assuming you have a separate sql_safety module

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("bizsql")

DATA_CSV = os.getenv("DATA_CSV", "data/daily_product_sales.csv")

SCHEMA = (
    "Table daily_product_sales("
    "product_title TEXT, category TEXT, day DATE, units INT, revenue DOUBLE). "
    "Use DATE functions like date_trunc('quarter', day). "
    "For date literals, use CAST('YYYY-MM-DD' AS DATE). "
    "Assume current year (2024) for quarters like Q3 (July-Sep), e.g., CAST('2024-07-01' AS DATE) for Q3 start."
)

# Improved PROMPT_GEN with explicit date handling instructions
PROMPT_GEN = '''You are a SQL expert. Convert this business question to DuckDB SQL. Output ONLY the SQL query.
- Use column names exactly: product_title, category, day, units, revenue
- Use DATE functions like date_trunc('quarter', day). 
- For date literals, use CAST('YYYY-MM-DD' AS DATE).
- Assume current year (2024) for quarters like Q3 (July-Sep), e.g., CAST('2024-07-01' AS DATE) for Q3 start.
- If aggregation is implied, aggregate and sort appropriately.
Schema: {schema}
Question: {q}
SQL:'''

PROMPT_REV = '''You are a senior BI reviewer. Given schema, question and SQL:
1) Check intent & correctness (filters, groupings, windows).
2) List issues (if any).
3) Provide corrected SQL if needed.
Return JSON with keys: reasoning, ok (true/false), fixed_sql.
Schema: {schema}
Question: {q}
SQL:
{sql}
JSON:'''

app = FastAPI(title="BizSQL API", version="0.2")

class ExecResponse(BaseModel):
    sql: str
    rows: List[Dict]
    review: Dict

def _con():
    df = pd.read_csv(DATA_CSV, parse_dates=["day"])
    df["day"] = df["day"].dt.date
    con = duckdb.connect()
    con.register("daily_product_sales", df)
    return con

@app.get("/health")
def health():
    return {"ok": True, "provider": os.getenv("LLM_PROVIDER", "hf")}

@app.get("/schema")
def schema():
    return {"schema": SCHEMA}

@app.post("/nl2sql")
def nl2sql(q: str):
    t0 = time.time()
    raw = llm_call("gen", PROMPT_GEN.format(q=q, schema=SCHEMA)) # Pass schema to prompt
    sql = sanitize(extract_sql(raw))
    log.info(json.dumps({"metric": "gen_latency_ms", "v": int((time.time() - t0) * 1000)}))
    return {"sql": sql, "raw": raw}

@app.post("/review")
def review(q: str, sql: str):
    t0 = time.time()
    out = llm_call("rev", PROMPT_REV.format(schema=SCHEMA, q=q, sql=sql))
    js = extract_json(out)
    log.info(json.dumps({"metric": "review_latency_ms", "v": int((time.time() - t0) * 1000)}))
    return js

@app.get("/execute", response_model=ExecResponse)
def execute(q: str = Query(...)):
    # 1) generate SQL
    t0 = time.time()
    raw_response = llm_call("gen", PROMPT_GEN.format(q=q, schema=SCHEMA)) # Pass schema to prompt
    sql = sanitize(extract_sql(raw_response)) # Apply sanitization after extraction
    gen_ms = int((time.time() - t0) * 1000)
    print(f"Generated SQL: {sql}") # Debug log

    # 2) execute
    t1 = time.time()
    try:
        rows = _con().execute(sql).df().to_dict(orient="records")
    except Exception as e:
        log.error(f"SQL Execution Error: {e}")
        log.error(f"Problematic SQL: {sql}")
        raise # Re-raise the exception to return a 500 error
    exec_ms = int((time.time() - t1) * 1000)

    # 3) review
    t2 = time.time()
    rev = extract_json(llm_call("rev", PROMPT_REV.format(schema=SCHEMA, q=q, sql=sql)))
    rev_ms = int((time.time() - t2) * 1000)

    log.info(json.dumps({"metric": "gen_latency_ms", "v": gen_ms}))
    log.info(json.dumps({"metric": "exec_latency_ms", "v": exec_ms}))
    log.info(json.dumps({"metric": "review_latency_ms", "v": rev_ms}))
    return {"sql": sql, "rows": rows, "review": rev}

# --- Updated sanitize function with date literal fix ---
# If you prefer to keep this in sql_safety.py, move this function there
# and update the import accordingly.
def sanitize(sql: str) -> str:
    """
    Sanitize the SQL string to prevent dangerous operations and fix common LLM errors.
    This function should be applied after extract_sql.
    """
    sql = sql.strip().rstrip(';')
    lower_sql = sql.lower()

    # --- Safety Checks ---
    if not (lower_sql.startswith("select") or lower_sql.startswith("with")):
        raise ValueError("Only SELECT or CTE queries allowed.")

    if re.search(r"(?is)\b(drop|delete|update|insert|merge|alter|create|truncate|grant|revoke|vacuum|attach|copy)\b", lower_sql):
        raise ValueError("Dangerous SQL operation blocked.")

    # --- Risk Mitigation: Auto-fix date literals in date_trunc ---
    # Example: date_trunc('quarter', '2022-07-01') -> date_trunc('quarter', CAST('2022-07-01' AS DATE))
    # This regex finds date_trunc calls with string literals and wraps the string in CAST(... AS DATE)
    sql = re.sub(
        r"date_trunc\(\s*'(\w+)'\s*,\s*'(\d{4}-\d{2}-\d{2})'\s*\)", # Match date_trunc('type', 'YYYY-MM-DD')
        r"date_trunc('\1', CAST('\2' AS DATE))", # Replace with date_trunc('type', CAST('YYYY-MM-DD' AS DATE))
        sql,
        flags=re.IGNORECASE
    )

    # --- Default Table and Limits ---
    if "daily_product_sales" not in lower_sql:
        where_index = lower_sql.find(" where ")
        cut = where_index if where_index != -1 else len(sql)
        sql = sql[:cut] + " FROM daily_product_sales " + sql[cut:]

    if "limit" not in lower_sql:
        sql += " LIMIT 200"

    return sql