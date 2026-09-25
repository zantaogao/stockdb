import sqlite3, os
os.chdir(os.path.expanduser('~/.hermes/stockdb'))
c = sqlite3.connect('ledger.db')
rows = c.execute("SELECT trade_date,strategy,code,name,direction,price,quantity,amount FROM trade_log WHERE trade_date LIKE '2026-09-11%' OR trade_date LIKE '20260911%' ORDER BY strategy,code").fetchall()
print("trade_log 09-11 rows:", len(rows))
for r in rows: print(r)
