import duckdb
c = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
for t in ['board_daily','stock_daily','daily']:
    try:
        cols=[r[1] for r in c.execute(f"PRAGMA table_info({t})").fetchall()]
        print(t, cols[:25])
        print('  maxdt', c.execute(f"SELECT MAX(trade_date) FROM {t}").fetchone())
    except Exception as e:
        print(t,'ERR',e)
# 行业映射来源
try:
    print(c.execute("SELECT table_name,column_name FROM information_schema.columns WHERE column_name='industry_name'").fetchall())
except Exception as e: print(e)
