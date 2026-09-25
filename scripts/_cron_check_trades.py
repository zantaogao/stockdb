import sqlite3, os
os.chdir(os.path.expanduser('~/.hermes/stockdb'))
c = sqlite3.connect('ledger.db')
cols = [x[1] for x in c.execute("PRAGMA table_info(trade_log)")]
print('cols:', cols)
dcol = 'date' if 'date' in cols else ('trade_date' if 'trade_date' in cols else cols[0])
rows = c.execute(f"SELECT * FROM trade_log WHERE {dcol} LIKE '%2026-09-01%' OR {dcol} LIKE '%20260901%'").fetchall()
for r in rows:
    print(r)
print('today trades total:', len(rows))
# strategy accounts latest NAV
try:
    rows2 = c.execute("SELECT strategy, trade_date, nav FROM strategy_nav WHERE trade_date >= '2026-09-01' ORDER BY strategy").fetchall()
    for r in rows2: print(r)
except Exception as e:
    print('nav table:', e)