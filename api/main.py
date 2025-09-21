from fastapi import FastAPI, Query
from pydantic import BaseModel
from typing import List, Dict
import os, duckdb
from dotenv import load_dotenv

load_dotenv()

APP_ENV = os.getenv("APP_ENV", "local")
DB_PATH = os.getenv("DUCKDB_PATH", "data/out/market.duckdb")

app = FastAPI(title="Marketplace RAG API", version="0.1")

class QAResponse(BaseModel):
    sql: str
    rows: List[Dict]
    citations: List[str]

def parse_nl_to_sql(q: str) -> str:
    ql = q.lower()
    topn = 5
    for tok in q.split():
        if tok.isdigit():
            topn = int(tok); break
    cat = None
    for c in ["electronics","home","beauty","sports","toys"]:
        if c in ql: cat = c
    quarter = None
    for qx in ["q1","q2","q3","q4"]:
        if qx in ql: quarter = qx.upper()
    where = []
    if cat: where.append(f"category = '{cat}'")
    if quarter:
        rng = {"Q1":("2024-01-01","2024-03-31"),"Q2":("2024-04-01","2024-06-30"),
               "Q3":("2024-07-01","2024-09-30"),"Q4":("2024-10-01","2024-12-31")}[quarter]
        where.append(f"CAST(day AS DATE) BETWEEN DATE '{rng[0]}' AND DATE '{rng[1]}'")
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    return f"""
SELECT product_title, category, SUM(units) as units, SUM(revenue) as revenue
FROM daily_product_sales
{where_sql}
GROUP BY 1,2
ORDER BY revenue DESC
LIMIT {topn};
"""

def _query_duckdb(sql: str):
    con = duckdb.connect(DB_PATH, read_only=True)
    return con.execute(sql).df().to_dict(orient="records")

# Optional future path if you switch APP_ENV=aws and wire Athena
def _query_athena(sql: str):
    import boto3, time
    s3_output = os.getenv("ATHENA_OUTPUT", "s3://CHANGE-ME/athena-results/")
    db = os.getenv("ATHENA_DB", "default")
    wg = os.getenv("ATHENA_WORKGROUP", "primary")
    ath = boto3.client("athena", region_name=os.getenv("REGION", "ap-south-1"))
    qid = ath.start_query_execution(
        QueryString=sql,
        QueryExecutionContext={"Database": db},
        WorkGroup=wg,
        ResultConfiguration={"OutputLocation": s3_output},
    )["QueryExecutionId"]
    for _ in range(90):
        st = ath.get_query_execution(QueryExecutionId=qid)["QueryExecution"]["Status"]["State"]
        if st in ("SUCCEEDED","FAILED","CANCELLED"): break
        time.sleep(1)
    if st != "SUCCEEDED":
        return []
    res = ath.get_query_results(QueryExecutionId=qid)
    cols = [c["Label"] for c in res["ResultSet"]["ResultSetMetadata"]["ColumnInfo"]]
    rows = []
    for r in res["ResultSet"]["Rows"][1:]:
        vals = [c.get("VarCharValue") for c in r["Data"]]
        rows.append(dict(zip(cols, vals)))
    return rows

@app.get("/health")
def health():
    return {"ok": True, "env": APP_ENV}

@app.get("/ask", response_model=QAResponse)
def ask(q: str = Query(...)):
    sql = parse_nl_to_sql(q)
    if APP_ENV == "aws":
        rows = _query_athena(sql)
        cites = ["athena:daily_product_sales"]
    else:
        rows = _query_duckdb(sql)
        cites = ["daily_product_sales"]
        if "WHERE" in sql:
            cites.append(sql.split("WHERE",1)[1].strip())
    return {"sql": sql, "rows": rows, "citations": cites}
