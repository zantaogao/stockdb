import sqlite3, os
BASE = os.path.expanduser('~/.hermes/stockdb')
l = sqlite3.connect(os.path.join(BASE,'ledger.db'))
cols=[c[1] for c in l.execute("PRAGMA table_info(holdings)").fetchall()]
print('holdings cols:', cols)
for r in l.execute("SELECT * FROM holdings").fetchall(): print(r)
print('--- watchlist active (非archived) ---')
wcols=[c[1] for c in l.execute("PRAGMA table_info(watchlist)").fetchall()]
print('watchlist cols:', wcols)
for r in l.execute("SELECT * FROM watchlist WHERE status NOT IN ('archived') ORDER BY date DESC LIMIT 20").fetchall(): print(r)
print('--- account_balance ---')
for r in l.execute("SELECT * FROM account_balance").fetchall(): print(r)
l.close()
