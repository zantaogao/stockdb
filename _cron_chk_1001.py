import duckdb, os
d = duckdb.connect(os.path.expanduser('~/.hermes/stockdb/tushare.db'), read_only=True)
print("stock_daily 最近5个交易日:")
print(d.execute("select date, count(*) from stock_daily where date>='2026-09-22' group by date order by date desc limit 5").fetchall())
d.close()
i = duckdb.connect(os.path.expanduser('~/.hermes/stockdb/indicators.db'), read_only=True)
print("indicator_bfq 最近5日:")
print(i.execute("select trade_date, count(*) from indicator_bfq where trade_date>='20260922' group by trade_date order by trade_date desc limit 5").fetchall())
i.close()
