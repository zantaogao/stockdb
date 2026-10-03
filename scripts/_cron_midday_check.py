import sqlite3, os, json, collections
os.chdir('/Users/zantao/.hermes/stockdb')
c = sqlite3.connect('ledger.db')
tabs = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
print('tables:', tabs)
for t in tabs:
    if 'trade' in t.lower() or 'log' in t.lower():
        cols = [x[1] for x in c.execute(f"PRAGMA table_info({t})").fetchall()]
        print('---', t, cols)
# find a date-ish column and dump 2026-09-30 rows
for t in tabs:
    if 'trade' not in t.lower():
        continue
    cols = [x[1] for x in c.execute(f"PRAGMA table_info({t})").fetchall()]
    dcol = None
    for cand in ('trade_date','ts','date','time','created_at'):
        if cand in cols:
            dcol = cand; break
    if not dcol: continue
    print('=== rows in', t, 'on 2026-09-30 ===')
    try:
        rows = c.execute(f"SELECT * FROM {t} WHERE CAST({dcol} AS TEXT) LIKE '2026-09-30%' OR CAST({dcol} AS TEXT) LIKE '20260930%'").fetchall()
        for r in rows: print(r)
        print('count', len(rows))
    except Exception as e:
        print('ERR', e)
