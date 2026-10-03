import sqlite3, os
con = sqlite3.connect(os.path.expanduser('~/.hermes/stockdb/ledger.db'))
print(con.execute("select cal_date,is_open from trade_cal where cal_date>='20261001' and cal_date<='20261010' order by cal_date").fetchall())
con.close()
