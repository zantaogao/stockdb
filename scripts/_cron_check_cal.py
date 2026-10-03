import sqlite3
con = sqlite3.connect('/Users/zantao/.hermes/stockdb/ledger.db')
for r in con.execute("SELECT cal_date, is_open FROM trade_cal WHERE cal_date IN ('20260930','20261001','20261009') ORDER BY cal_date"):
    print(r)
