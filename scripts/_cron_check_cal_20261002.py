import duckdb
c = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
rows = c.execute("select cal_date,is_open from trade_cal where cal_date between '20260928' and '20261012' order by cal_date").fetchall()
for r in rows:
    print(r)
