import duckdb
t = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
codes = ['600785.SH','300228.SZ','600594.SH','603737.SH','002208.SZ','688500.SH','001366.SZ','600510.SH','000617.SZ','300732.SZ','603887.SH','603113.SH','300214.SZ']
for c in codes:
    r = t.execute("SELECT trade_date, close, pct_chg FROM daily WHERE ts_code=? ORDER BY trade_date DESC LIMIT 2", (c,)).fetchall()
    print(c, r)
