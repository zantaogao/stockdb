import sqlite3, json
from pathlib import Path
con = sqlite3.connect('file:/Users/zantao/.hermes/stockdb/ledger.db?mode=ro', uri=True)
cur = con.cursor()
print('watchlist by status:', cur.execute('select status,count(*) from watchlist group by status').fetchall())
print('pending detail:', cur.execute("select stock_code,final_score,status from watchlist where status='pending' limit 10").fetchall())
p = Path('/Users/zantao/.hermes/stockdb/orders/pending.json')
print('pending.json exists:', p.exists())
# last execution_logs entries
print('last exec logs:', cur.execute('select exec_id,status from execution_logs order by exec_id desc limit 5').fetchall())
