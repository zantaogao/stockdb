import sqlite3
db = sqlite3.connect('/Users/zantao/.hermes/stockdb/ledger.db')
tabs = [t[0] for t in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
print("tables:", tabs)
for t in tabs:
    cols = [c[1] for c in db.execute(f'PRAGMA table_info("{t}")')]
    ucols = [c.upper() for c in cols]
    if 'NAV' in ucols:
        dcol = 'date' if 'DATE' in ucols else None
        acol = [c for c in cols if 'account' in c.lower() or c.lower() in ('acct','strategy')]
        acol = acol[0] if acol else None
        print("---", t, cols)
        if dcol and acol:
            rows = db.execute(f'SELECT "{acol}","{dcol}",nav FROM "{t}" WHERE "{dcol}">=\'20260921\' ORDER BY "{acol}","{dcol}"').fetchall()
            for r in rows: print(r)
