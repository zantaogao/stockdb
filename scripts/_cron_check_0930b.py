import sqlite3, os
base = os.path.expanduser('~/.hermes/stockdb')
con = sqlite3.connect(os.path.join(base, 'ledger.db'))
cur = con.cursor()
tabs = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")]
print('tables:', tabs)
for t in tabs:
    cols = [c[1] for c in cur.execute(f'PRAGMA table_info({t})')]
    dcol = None
    for c in ('date','trade_date','dt','day','ts','created_at','time'):
        if c in cols:
            dcol = c; break
    if dcol is None:
        print(t, '(no date col)', cols[:8]); continue
    try:
        n = cur.execute(f"SELECT COUNT(*) FROM {t} WHERE {dcol} LIKE '2026093%' OR {dcol} LIKE '2026-09-3%'").fetchone()[0]
        print(t, 'rows_sep30+:', n)
        if n and n <= 20:
            for r in cur.execute(f"SELECT * FROM {t} WHERE {dcol} LIKE '2026093%' OR {dcol} LIKE '2026-09-3%' ORDER BY {dcol}"):
                print('  ', r)
    except Exception as e:
        print(t, 'ERR', e)
