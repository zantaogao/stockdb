import duckdb
con = duckdb.connect('/Users/zantao/.hermes/stockdb/signals.db', read_only=True)
rows = con.execute("select date, ic, win_rate, forward_days from cmmr_ic_daily order by date desc limit 15").fetchall()
for r in rows: print(r)
print('---top10---')
rows = con.execute("select * from cmmr_top10_ic_daily order by date desc limit 10").fetchall()
for r in rows: print(r)
con.close()
