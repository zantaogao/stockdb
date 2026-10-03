import os
import sqlite3
db = os.path.expanduser('~/.hermes/stockdb/ledger.db')
con = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
cur = con.cursor()
tabs = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")]
print('tables:', tabs)
for t in tabs:
    cols = [c[1] for c in cur.execute(f'PRAGMA table_info({t})')]
    datecol = next((c for c in cols if c in ('date','trade_date','dt','day','created_at','ts','time')), None)
    if not datecol: continue
    try:
        rows = cur.execute(f"SELECT * FROM {t} WHERE {datecol} LIKE '2026-09-29%' OR {datecol} LIKE '20260929%'").fetchall()
        if rows:
            print(f'== {t} ({len(rows)} rows today) cols={cols}')
            for r in rows[:30]:
                print(r)
    except Exception as e:
        print(t, 'ERR', e)
