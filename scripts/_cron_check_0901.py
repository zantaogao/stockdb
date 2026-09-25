import sqlite3, os
base = os.path.expanduser('~/.hermes/stockdb')
con = sqlite3.connect(f'file:{base}/ledger.db?mode=ro', uri=True)
tabs = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]
print('tabs:', tabs)
for t in tabs:
    cols = [c[1] for c in con.execute(f'PRAGMA table_info("{t}")')]
    dcol = None
    for c in ('date','trade_date','exec_date','dt'):
        if c in cols:
            dcol = c; break
    if dcol and ('trade' in t or 'strategy' in t or 'order' in t):
        rows = con.execute(f'SELECT * FROM "{t}" WHERE REPLACE({dcol},"-","")=? ORDER BY rowid DESC LIMIT 30', ('20260901',)).fetchall()
        print(f'== {t} ({dcol}) 20260901 rows={len(rows)} cols={cols}')
        for r in rows: print('  ', r)
con.close()