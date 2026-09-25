import sqlite3, os, json, glob
os.chdir(os.path.expanduser('~/.hermes/stockdb'))
c = sqlite3.connect('ledger.db')
tabs = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
print('TABLES:', [t for t in tabs if 'strategy' in t or 'account' in t])
for t in tabs:
    if t.startswith('strategy') or t == 'account_balance':
        cols = [r[1] for r in c.execute("PRAGMA table_info(%s)" % t).fetchall()]
        print('--', t, cols)
print('=== strategy_accounts ===')
try:
    print([r[1] for r in c.execute("PRAGMA table_info(strategy_accounts)").fetchall()])
    for r in c.execute("SELECT * FROM strategy_accounts").fetchall():
        print(r)
except Exception as e:
    print('ERR', e)
print('=== strategy_account_daily tail ===')
for t in tabs:
    if 'daily' in t and 'strategy' in t:
        cols = [r[1] for r in c.execute("PRAGMA table_info(%s)" % t).fetchall()]
        print('--', t, cols)
        for r in c.execute("SELECT * FROM %s ORDER BY 1 DESC,2 DESC LIMIT 30" % t).fetchall():
            print(r)
