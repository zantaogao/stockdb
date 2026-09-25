import duckdb
con = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
for code in ('000592.SZ', '688217.SH'):
    r = con.execute("SELECT trade_date, open, high, low, close, pre_close FROM daily WHERE ts_code=? ORDER BY trade_date DESC LIMIT 3", [code]).fetchall()
    print(code, r)
r = con.execute("SELECT trade_date, close FROM index_daily WHERE ts_code='000852.SH' ORDER BY trade_date DESC LIMIT 3").fetchall() if True else None
print('zz1000', r)
