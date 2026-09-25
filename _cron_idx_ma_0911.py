import duckdb
t = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
for ts in ('000001.SH','000852.SH'):
    rows = t.execute(f"SELECT trade_date, close FROM index_daily_raw WHERE ts_code='{ts}' ORDER BY trade_date DESC LIMIT 20").fetchall()
    c = [r[1] for r in reversed(rows)]
    ma10 = sum(c[-10:])/10; ma20 = sum(c)/20
    print(ts, 'close=%.2f MA10=%.2f MA20=%.2f 20dhigh=%.2f 20dlow=%.2f' % (c[-1], ma10, ma20, max(c), min(c)))
