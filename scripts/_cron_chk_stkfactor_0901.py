import duckdb
c = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
for t in ['stk_factor', 'daily', 'index_daily_raw']:
    try:
        print(t, c.execute(f'SELECT MAX(trade_date) FROM {t}').fetchone()[0])
    except Exception as e:
        print(t, 'ERR', str(e)[:80])
rows = c.execute("""
  SELECT d.trade_date, s.n FROM
    (SELECT DISTINCT trade_date FROM daily WHERE trade_date>='20260825') d
  LEFT JOIN (SELECT trade_date, COUNT(*) n FROM stk_factor WHERE trade_date>='20260825' GROUP BY 1) s
  USING (trade_date) ORDER BY 1
""").fetchall()
print('daily vs stk_factor rows:', rows)