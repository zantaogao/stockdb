import duckdb
c = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
try:
    rows = c.execute("select cal_date from trade_cal where is_open=1 and cal_date>='20260925' and cal_date<='20261008' order by cal_date").fetchall()
    print("open_days:", [r[0] for r in rows])
except Exception as e:
    print("trade_cal err:", e)
try:
    rows2 = c.execute("select distinct trade_date from daily where trade_date>='20260925' and trade_date<='20261008' order by trade_date").fetchall()
    print("daily_dates:", [r[0] for r in rows2])
except Exception as e:
    print("daily err:", e)
