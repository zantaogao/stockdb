import sqlite3, glob, os, time

db = '/Users/zantao/.hermes/stockdb/ledger.db'
c = sqlite3.connect('file:' + db + '?mode=ro', uri=True)
tabs = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")]
print('tables:', tabs)
for t in tabs:
    cols = [d[1] for d in c.execute(f'PRAGMA table_info("{t}")')]
    dcols = [x for x in cols if 'date' in x.lower() or 'time' in x.lower() or x.lower() == 'ts']
    if not dcols:
        continue
    dc = dcols[0]
    for pat in ('%2026-09-30%', '%20260930%'):
        try:
            rows = c.execute(f'SELECT * FROM "{t}" WHERE "{dc}" LIKE ? ORDER BY rowid DESC LIMIT 5', (pat,)).fetchall()
        except Exception:
            continue
        if rows:
            print('---', t, cols)
            for r in rows:
                print('  ', r)

print('=== recent logs (by mtime) ===')
for f in sorted(glob.glob('/Users/zantao/.hermes/stockdb/logs/*'), key=os.path.getmtime, reverse=True)[:8]:
    print(time.strftime('%m-%d %H:%M', time.localtime(os.path.getmtime(f))), f)
