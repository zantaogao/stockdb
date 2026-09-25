import duckdb
d = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
print('== crash-day census (000852 by year)')
for r in d.execute("""
 SELECT substr(date::VARCHAR,1,4) yr,
        SUM(CASE WHEN change_pct<=-3 THEN 1 ELSE 0 END) crash,
        SUM(CASE WHEN change_pct<=-1 AND change_pct>-3 THEN 1 ELSE 0 END) mild,
        COUNT(*) AS n_days
 FROM index_daily WHERE index_code='000852' GROUP BY 1 ORDER BY 1
""").fetchall(): print(r)
print('== stk_factor coverage by year')
try:
    for r in d.execute("SELECT substr(trade_date,1,4), COUNT(DISTINCT trade_date), COUNT(*) FROM stk_factor WHERE trade_date>='20220101' GROUP BY 1 ORDER BY 1").fetchall(): print(r)
except Exception as e: print('stk_factor err:', e)
print('== stock_daily coverage')
print(d.execute("SELECT MIN(date), MAX(date), COUNT(DISTINCT date) FROM stock_daily").fetchone())
