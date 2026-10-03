import sqlite3
con = sqlite3.connect('file:/Users/zantao/.hermes/stockdb/ledger.db?mode=ro', uri=True)
con.row_factory = sqlite3.Row
cur = con.cursor()
tabs = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")]
print("tables:", tabs)
for t in tabs:
    cols = [c[1] for c in cur.execute(f"PRAGMA table_info('{t}')")]
    datecol = None
    for cand in ('trade_date','date','exec_date','ts','created_at','timestamp','source_timestamp'):
        if cand in cols:
            datecol = cand
            break
    n = cur.execute(f"SELECT COUNT(*) FROM '{t}'").fetchone()[0]
    print("==", t, "rows:", n)
    print("   cols:", cols)
