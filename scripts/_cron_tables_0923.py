import duckdb
c = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
for r in c.execute("SHOW TABLES").fetchall():
    print(r[0])
