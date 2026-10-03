import sqlite3
c = sqlite3.connect('file:/Users/zantao/.hermes/stockdb/ledger.db?mode=ro', uri=True)
print('10/1-10/8 is_open (YYYYMMDD):',
      c.execute("SELECT cal_date,is_open FROM trade_cal WHERE cal_date BETWEEN '20261001' AND '20261008' ORDER BY cal_date").fetchall())
print('hit $today format test:',
      c.execute("SELECT is_open FROM trade_cal WHERE cal_date='2026-10-01'").fetchone())
c.close()
