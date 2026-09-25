import sqlite3
c = sqlite3.connect('/Users/zantao/.hermes/stockdb/ledger.db', timeout=30)
print(c.execute("SELECT trade_date, trade_time, direction, code, name, quantity, price, amount, notes FROM trade_log WHERE strategy='agent_auto' AND trade_date>='2026-09-24' ORDER BY id").fetchall())
