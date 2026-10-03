import sqlite3
con = sqlite3.connect('/Users/zantao/.hermes/stockdb/ledger.db')
cur = con.cursor()
cols = [c[1] for c in cur.execute("PRAGMA table_info(trade_log)").fetchall()]
print('trade_log cols:', cols)
for row in cur.execute("SELECT * FROM trade_log ORDER BY rowid DESC LIMIT 3").fetchall():
    print(row)
print('---execution_logs---')
cols2 = [c[1] for c in cur.execute("PRAGMA table_info(execution_logs)").fetchall()]
print(cols2)
for row in cur.execute("SELECT * FROM execution_logs ORDER BY rowid DESC LIMIT 3").fetchall():
    print(row)
