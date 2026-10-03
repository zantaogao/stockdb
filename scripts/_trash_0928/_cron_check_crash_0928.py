import sqlite3
db = sqlite3.connect('/Users/zantao/.hermes/stockdb/ledger.db')
cols=[c[1] for c in db.execute('PRAGMA table_info(account_balance)')]
print(cols)
for r in db.execute("SELECT * FROM account_balance ORDER BY rowid DESC LIMIT 3").fetchall():
    print(r)
print('--- crash_state ---')
print(db.execute('SELECT * FROM strategy_crash_state').fetchall())
