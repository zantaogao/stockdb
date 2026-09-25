import duckdb
tdu = duckdb.connect('tushare.db', read_only=True)
codes = ['688275.SH','688063.SH','688191.SH','001332.SZ','605598.SH','002595.SZ']
for c in codes:
    rows = tdu.execute("""
        SELECT trade_date, close, pct_chg FROM (
          SELECT *, ROW_NUMBER() OVER (PARTITION BY ts_code ORDER BY trade_date DESC) rn
          FROM daily WHERE ts_code=?) WHERE rn<=4 ORDER BY trade_date
    """, (c,)).fetchall()
    print(c, rows)