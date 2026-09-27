import duckdb
conn = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
print('tables:', [r[0] for r in conn.execute("select table_name from information_schema.tables").fetchall()])
for t in ['stock_daily','stock_factor','stk_factor_pro']:
    try:
        r = conn.execute(f"select count(*), min(trade_date), max(trade_date) from {t}").fetchone()
        print(t, r)
        cols = conn.execute(f"describe {t}").fetchall()
        print('  cols:', [c[0] for c in cols])
    except Exception as e:
        print(t, 'ERR', str(e)[:80])
