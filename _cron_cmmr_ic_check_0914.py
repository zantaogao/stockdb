import sqlite3, duckdb, os
os.chdir(os.path.expanduser('~/.hermes/stockdb'))
c = sqlite3.connect('signals.db')
print("== tables in signals.db ==")
tabs = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
print([t for t in tabs if 'ic' in t.lower() or 'etf' in t.lower()])
for t in ('ic_daily','ic_window','etf_scores','etf_ic'):
    if t not in tabs:
        print(f"-- {t}: MISSING"); continue
    cols = [r[1] for r in c.execute(f"PRAGMA table_info({t})").fetchall()]
    print(f"-- {t} cols={cols}")
    try:
        rows = c.execute(f"SELECT * FROM {t} ORDER BY 1 DESC LIMIT 12").fetchall()
        for r in rows: print("   ", r)
    except Exception as e:
        print("   err", e)
