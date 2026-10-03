import sqlite3
con=sqlite3.connect('file:/Users/zantao/.hermes/stockdb/signals.db?mode=ro',uri=True)
cur=con.cursor()
tabs=[r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")]
print('signals.db tables:',tabs)
for t in tabs:
    if any(k in t.lower() for k in ('order','pending','exec','queue')):
        cols=[c[1] for c in cur.execute(f'PRAGMA table_info("{t}")')]
        print(t,cols)
        print(cur.execute(f'SELECT * FROM "{t}" ORDER BY rowid DESC LIMIT 5').fetchall())
