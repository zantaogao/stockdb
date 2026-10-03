import duckdb
t = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
tabs = [r[0] for r in t.execute('SHOW TABLES').fetchall()]
print(tabs)
for tb in tabs:
    if 'sw' in tb.lower() or 'industry' in tb.lower() or 'index' in tb.lower():
        print(tb, [r[1] for r in t.execute(f"PRAGMA table_info({tb})").fetchall()][:12])
