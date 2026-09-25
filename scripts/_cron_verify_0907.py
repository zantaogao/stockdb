import sqlite3, os
db = os.path.expanduser('/Users/zantao/.hermes/stockdb/ledger.db')
c = sqlite3.connect(db)
tabs = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")]
print('TABLES:', tabs)
for t in tabs:
    if 'strateg' not in t and t != 'trade_log': continue
    cols = [r[1] for r in c.execute(f'PRAGMA table_info("{t}")')]
    print(t, 'COLS:', cols)
    dcol = next((x for x in ('trade_date','date','nav_date','trade_time','dt','time') if x in cols), None)
    if dcol:
        rows = c.execute(f'SELECT * FROM "{t}" WHERE REPLACE(REPLACE(CAST("{dcol}" AS TEXT),"-",""),"/","") LIKE \'20260907%\'').fetchall()
        print(f'  -> 20260907 rows: {len(rows)}')
        for r in rows[:15]: print('    ', r)
c.close()