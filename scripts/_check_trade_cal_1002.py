import os
import duckdb
BASE = os.path.expanduser('~/.hermes/stockdb')
con = duckdb.connect(os.path.join(BASE, 'tushare.db'), read_only=True)
rows = con.execute("SELECT cal_date, is_open FROM trade_cal WHERE cal_date BETWEEN '20260928' AND '20261010' ORDER BY cal_date").fetchall()
for r in rows:
    print(r)
con.close()
