import sqlite3
con = sqlite3.connect('/Users/zantao/.hermes/stockdb/ledger.db')
try:
    rows = con.execute("SELECT cal_date, is_open, updated_at FROM trade_cal WHERE cal_date BETWEEN '20260928' AND '20261009' ORDER BY cal_date").fetchall()
    for r in rows:
        print(*r)
except Exception as e:
    print('ERR', e)
