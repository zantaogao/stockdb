import sqlite3
db = '/Users/zantao/.hermes/stockdb/ledger.db'
con = sqlite3.connect(db)
rows = con.execute(
    "select cal_date, is_open from trade_cal "
    "where cal_date in ('20260930','20261001','20261002','20261008','20261009') "
    "order by cal_date"
).fetchall()
print(rows)
mx = con.execute("select max(cal_date) from trade_cal").fetchone()
print('max cal_date:', mx)
