# /api/main.py
from fastapi import FastAPI, Query
from pydantic import BaseModel
from typing import List, Dict
import os
import duckdb
import pandas as pd
import json
import re
from .providers import llm_call

app = FastAPI(title="DataWeaver API")

SCHEMA = "Table daily_product_sales(product_title TEXT, category TEXT, day DATE, units INT, revenue DOUBLE). Use DATE functions like date_trunc('quarter', day)."

PROMPT_GEN = """You are a SQL expert. Convert this business question to DuckDB SQL. Output ONLY the SQL query. Schema: {schema}
Question: {q}
SQL:"""

PROMPT_REV = """Review this SQL for the question and schema. Output JSON: {{"reasoning": "your analysis", "ok": true/false, "fixed_sql": "corrected SQL or empty"}}.
Schema: {schema}
Question: {q}
SQL: {sql}
JSON:""

class GenRequest(BaseModel):
    q: str

class ExecResponse(BaseModel):
    sql: str
    rows: List[Dict]
    review: Dict

# Helper functions
def extract_sql(text: str) -> str:
    """Extract SQL query from LLM response, assuming it's the last line or standalone."""
    lines = text.strip().split('\n')
    for line in reversed(lines):
        if line.strip().upper().startswith('SELECT') or line.strip().upper().startswith('WITH'):
            return line.strip()
    raise ValueError("No valid SQL found in response")

def extract_json(text: str) -> Dict:
    """Extract and parse JSON from LLM review response."""
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        return {"reasoning": text, "ok": False, "fixed_sql": ""}

@app.get("/health")
def health():
    return {"ok": True}

@app.post("/nl2sql")
def nl2sql(req: GenRequest):
    raw_sql = llm_call("gen", PROMPT_GEN.format(schema=SCHEMA, q=req.q))
    return {"sql": sanitize(raw_sql)}

@app.post("/review")
def review(req: GenRequest):
    review_output = llm_call("rev", PROMPT_REV.format(schema=SCHEMA, q=req.q, sql=req.q))
    return extract_json(review_output)

def get_db_connection():
    con = duckdb.connect()
    df = pd.read_csv("data/daily_product_sales.csv", parse_dates=["day"])
    df["day"] = df["day"].dt.date
    con.register("daily_product_sales", df)
    return con

@app.get("/execute", response_model=ExecResponse)
def execute(q: str = Query(...)):
    # 1) Generate SQL
    raw_response = llm_call("gen", PROMPT_GEN.format(schema=SCHEMA, q=q))
    sql = sanitize(extract_sql(raw_response))
    # 2) Execute
    con = get_db_connection()
    rows = con.execute(sql).df().to_dict(orient="records")
    # 3) Review
    review_json_str = llm_call("rev", PROMPT_REV.format(schema=SCHEMA, q=q, sql=sql))
    review = extract_json(review_json_str)
    return {"sql": sql, "rows": rows, "review": review}

def sanitize(sql: str) -> str:
    sql = sql.strip().strip(";")
    lower_sql = sql.lower()
    if not (lower_sql.startswith("select") or lower_sql.startswith("with")):
        raise ValueError("Only SELECT or CTE queries allowed.")
    if re.search(r"(?is)\b(drop|delete|update|insert|merge|alter|create|truncate|grant|revoke|vacuum|attach|copy)\b", lower_sql):
        raise ValueError("Dangerous SQL operation blocked.")
    if "daily_product_sales" not in lower_sql:
        where_index = lower_sql.find(" where ")
        cut = where_index if where_index != -1 else len(sql)
        sql = sql[:cut] + " FROM daily_product_sales " + sql[cut:]
    if "limit" not in lower_sql:
        sql += " LIMIT 200"
    return sql