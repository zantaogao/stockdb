import duckdb
con = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
codes = ['300952.SZ','300680.SZ','300658.SZ','603966.SH','001332.SZ','301479.SZ','301093.SZ','688191.SH','301237.SZ','301413.SZ']
ph = ','.join(['?']*len(codes))
rows = con.execute(f"""
WITH d AS (SELECT ts_code, trade_date, close,
   ROW_NUMBER() OVER (PARTITION BY ts_code ORDER BY trade_date DESC) rn
   FROM daily WHERE trade_date>='20260801' AND ts_code IN ({ph}))
SELECT ts_code,
  MAX(CASE WHEN rn=1 THEN close END) c1,
  MAX(CASE WHEN rn=6 THEN close END) c6,
  MAX(CASE WHEN rn=1 THEN close END)/MAX(CASE WHEN rn=21 THEN close END)-1 c21
FROM d WHERE rn<=21 GROUP BY ts_code""", codes).fetchall()
for ts,c1,c6,c21 in rows:
    print(ts, '5d%', round((c1/c6-1)*100,1), '20d%', round(c21*100,1))