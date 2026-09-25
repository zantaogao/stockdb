import sqlite3
con = sqlite3.connect('file:/Users/zantao/.hermes/stockdb/signals.db?mode=ro', uri=True)
tabs = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]
want = ['ic_daily', 'cmmr_ic_daily', 'fusion_ic_daily', 'factor_ic_roll', 'factor_group_ic_daily']
for t in want:
    if t not in tabs:
        print(t, 'MISSING'); continue
    cols = [r[1] for r in con.execute(f"PRAGMA table_info({t})")]
    print('==', t, cols)
    n = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    print('   rows=', n)
    for r in con.execute(f"SELECT * FROM {t} ORDER BY 1 DESC LIMIT 4"):
        print('  ', r)
con.close()
