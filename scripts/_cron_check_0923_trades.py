import sqlite3
con = sqlite3.connect('/Users/zantao/.hermes/stockdb/ledger.db')
cur = con.cursor()
cols = [r[1] for r in cur.execute("PRAGMA table_info(trade_log)")]
print('trade_log cols:', cols)
# today's trades (date formats may be YYYY-MM-DD or YYYYMMDD)
for fmt in ('2026-09-23', '20260923'):
    rows = cur.execute(
        "SELECT * FROM trade_log WHERE trade_date LIKE ? || '%'", (fmt,)
    ).fetchall() if 'trade_date' in cols else []
    if rows:
        print(f'--- trades with date prefix {fmt}: {len(rows)}')
        for r in rows:
            print(r)
# fallback: any date column
if not rows:
    for c in cols:
        if 'date' in c or 'time' in c:
            rows = cur.execute(f"SELECT * FROM trade_log WHERE CAST({c} AS TEXT) LIKE '2026-09-23%' OR CAST({c} AS TEXT) LIKE '20260923%'").fetchall()
            if rows:
                print(f'--- via col {c}: {len(rows)}')
                for r in rows:
                    print(r)
            break
# also confirm last nav row per strategy account for 20260923
try:
    tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    navt = [t for t in tables if 'nav' in t.lower()]
    print('nav tables:', navt)
except Exception as e:
    print('nav probe err', e)
con.close()
