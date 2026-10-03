import duckdb
con = duckdb.connect("/Users/zantao/.hermes/stockdb/ledger.db", read_only=True)
rows = con.sql("select cal_date, is_open from trade_cal where cal_date between '20260928' and '20261010' order by cal_date").fetchall()
for r in rows:
    print(r)
