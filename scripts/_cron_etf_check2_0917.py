import duckdb
d = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
print('fund_daily max trade_date:', d.execute("SELECT MAX(trade_date) FROM fund_daily").fetchone()[0])
print('fund_daily last dates:', d.execute("SELECT trade_date, COUNT(*) FROM fund_daily GROUP BY 1 ORDER BY 1 DESC LIMIT 5").fetchall())
print('daily max:', d.execute("SELECT MAX(trade_date) FROM daily").fetchone()[0])
