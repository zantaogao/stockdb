import sqlite3
db = '/Users/zantao/.hermes/stockdb/ledger.db'
c = sqlite3.connect(db)
cols = [d[1] for d in c.execute('PRAGMA table_info(execution_logs)')]
print('exec cols:', cols)
rows = list(c.execute("select * from execution_logs order by rowid desc limit 5"))
for r in rows:
    print(r)
print('---trade_signals---')
cols2 = [d[1] for d in c.execute('PRAGMA table_info(trade_signals)')]
print('cols:', cols2)
rows2 = list(c.execute("select * from trade_signals order by rowid desc limit 8"))
for r in rows2:
    print(r)
print('---watchlist pending detail (recent)---')
cols3 = [d[1] for d in c.execute('PRAGMA table_info(watchlist)')]
print('cols:', cols3)
rows3 = list(c.execute("select * from watchlist where status='pending' order by rowid desc limit 12"))
for r in rows3:
    print(r)
