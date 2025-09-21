import duckdb, pandas as pd, numpy as np, pathlib

pathlib.Path('data/out').mkdir(parents=True, exist_ok=True)
np.random.seed(7)

cats = ["electronics","home","beauty","sports","toys"]
products = pd.DataFrame({"product_id": range(1,501)})
products["product_title"] = [f"Product {i}" for i in range(1,501)]
products["category"] = np.random.choice(cats, size=len(products))
products["price"] = np.round(np.random.gamma(4, 20, size=len(products))+5,2)

orders = []
for oid in range(1,20001):
    pid = np.random.randint(1,501)
    qty = np.random.randint(1,4)
    ts  = pd.Timestamp("2024-01-01") + pd.to_timedelta(np.random.randint(0,365), unit="D")
    orders.append({"order_id": oid, "product_id": pid, "qty": qty, "ts": ts})
orders = pd.DataFrame(orders)

con = duckdb.connect("data/out/market.duckdb")
con.execute("CREATE OR REPLACE TABLE products AS SELECT * FROM products")
con.execute("CREATE OR REPLACE TABLE orders AS SELECT * FROM orders")
con.execute('''
CREATE OR REPLACE TABLE daily_product_sales AS
SELECT
  p.product_id,
  p.product_title,
  p.category,
  DATE_TRUNC('day', o.ts) as day,
  SUM(o.qty) as units,
  SUM(o.qty * p.price) as revenue
FROM orders o JOIN products p ON o.product_id = p.product_id
GROUP BY ALL
''')
print("OK: data/out/market.duckdb with products, orders, daily_product_sales")
