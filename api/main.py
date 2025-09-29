from fastapi import FastAPI, Query
from pydantic import BaseModel
from typing import List, Dict
import os, time, json, duckdb, pandas as pd, logging
from .providers import llm_call, extract_sql, extract_json
from .sql_safety import sanitize

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("bizsql")

DATA_CSV = os.getenv("DATA_CSV", "data/daily_product_sales.csv")

SCHEMA = "Table daily_product_sales(product_title TEXT, category TEXT, day DATE, units INT, revenue DOUBLE). Use DATE functions like date_trunc('quarter', day)."

PROMPT_GEN = """You are a SQL expert. Convert this business question to DuckDB SQL. Output ONLY the SQL query. Schema: {schema}
Question: {q}
SQL:"""

PROMPT_REV = """Review this SQL for the question and schema. Output JSON: {{"reasoning": "your analysis", "ok": true/false, "fixed_sql": "corrected SQL or empty"}}.
Schema: {schema}
Question: {q}
SQL: {sql}
JSON:"""

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
def health(): return {"ok": True, "provider": os.getenv("LLM_PROVIDER","hf")}

@app.get("/schema")
def schema(): return {"schema": SCHEMA}

@app.post("/nl2sql")
def nl2sql(q: str):
    t0 = time.time()
    raw = llm_call("gen", PROMPT_GEN.format(q=q))
    sql = sanitize(extract_sql(raw))
    log.info(json.dumps({"metric":"gen_latency_ms","v":int((time.time()-t0)*1000)}))
    return {"sql": sql, "raw": raw}

@app.post("/review")
def review(q: str, sql: str):
    t0 = time.time()
    out = llm_call("rev", PROMPT_REV.format(schema=SCHEMA, q=q, sql=sql))
    js = extract_json(out)
    log.info(json.dumps({"metric":"review_latency_ms","v":int((time.time()-t0)*1000)}))
    return js

@app.get("/execute", response_model=ExecResponse)
def execute(q: str = Query(...)):
    # 1) gen SQL
    t0 = time.time()
    sql = sanitize(extract_sql(llm_call("gen", PROMPT_GEN.format(q=q))))
    gen_ms = int((time.time()-t0)*1000)

    # 2) run
    t1 = time.time()
    rows = _con().execute(sql).df().to_dict(orient="records")
    exec_ms = int((time.time()-t1)*1000)

    # 3) review
    t2 = time.time()
    rev = extract_json(llm_call("rev", PROMPT_REV.format(schema=SCHEMA, q=q, sql=sql)))
    rev_ms = int((time.time()-t2)*1000)

    log.info(json.dumps({"metric":"gen_latency_ms","v":gen_ms}))
    log.info(json.dumps({"metric":"exec_latency_ms","v":exec_ms}))
    log.info(json.dumps({"metric":"review_latency_ms","v":rev_ms}))
    return {"sql": sql, "rows": rows, "review": rev}