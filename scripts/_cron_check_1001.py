import duckdb, os
con = duckdb.connect(os.path.expanduser('~/.hermes/stockdb/ledger.db'), read_only=True)
print(con.execute("select cal_date, is_open from trade_cal where cal_date between '20260928' and '20261010' order by cal_date").fetchall())
