import sqlite3
c = sqlite3.connect('/Users/zantao/.hermes/stockdb/ledger.db', timeout=15)
rows = c.execute("SELECT trade_date, trade_time, direction, code, name, quantity, price, amount, strategy, notes FROM trade_log ORDER BY rowid DESC LIMIT 15").fetchall()
for r in rows:
    print(r)
