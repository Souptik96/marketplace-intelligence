import re

TABLE = "daily_product_sales"

def enforce_table(sql: str) -> str:
    s = sql.strip().strip(";")
    low = s.lower()
    if TABLE in low:
        return s
    # insert FROM if missing before WHERE/GROUP/ORDER/LIMIT
    cut = len(s); low = s.lower()
    for kw in [" where ", "\nwhere ", " group ", "\ngroup ", " order ", "\norder ", " limit ", "\nlimit "]:
        p = low.find(kw)
        if p != -1: cut = min(cut, p)
    return (s[:cut] + f" FROM {TABLE} " + s[cut:]).strip()

def sanitize(sql: str) -> str:
    s = sql.strip().strip(";")
    low = s.lower()
    if not (low.startswith("select") or low.startswith("with")):
        raise ValueError("Only SELECT/CTE queries are allowed.")
    if re.search(r"(?is)\b(drop|delete|update|insert|merge|alter|create|truncate|grant|revoke|vacuum|attach|copy)\b", low):
        raise ValueError("Dangerous statement blocked.")
    # force table presence
    s = enforce_table(s)
    if "limit" not in low:
        s += " LIMIT 200"
    return s