import sqlite3, json
sig = sqlite3.connect('/Users/zantao/.hermes/stockdb/signals.db')
sig.row_factory = sqlite3.Row
tabs = [r[0] for r in sig.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
print('tables with ic:', [t for t in tabs if 'ic' in t.lower()])
# center IC 序列
for t in tabs:
    if 'center' in t.lower() and 'ic' in t.lower():
        print('\n==', t, '==')
        cols=[x[1] for x in sig.execute(f'PRAGMA table_info({t})')]
        print('cols:',cols)
        order='date' if 'date' in cols else cols[0]
        for r in sig.execute(f'SELECT * FROM {t} ORDER BY {order} DESC LIMIT 12').fetchall():
            print(dict(r))
