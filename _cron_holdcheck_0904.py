import sqlite3
c = sqlite3.connect('/Users/zantao/.hermes/stockdb/ledger.db')
tl = [r[1] for r in c.execute("PRAGMA table_info(trade_log)")]
print("trade_log cols:", tl)
rows = c.execute("SELECT * FROM trade_log ORDER BY rowid DESC LIMIT 10").fetchall()
for r in rows: print(r)