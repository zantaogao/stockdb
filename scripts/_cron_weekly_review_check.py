import duckdb
con = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
tabs = [r[0] for r in con.execute("SHOW TABLES").fetchall()]
print("tables:", tabs)
