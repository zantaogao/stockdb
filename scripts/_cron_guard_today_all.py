import json, sqlite3
c = sqlite3.connect('/Users/zantao/.hermes/stockdb/ledger.db', timeout=30)
c.execute("PRAGMA journal_mode=WAL")
print(c.execute("SELECT trade_date, COUNT(*), SUM(CASE WHEN direction='BUY' THEN amount ELSE 0 END) FROM trade_log WHERE trade_date='2026-09-24' GROUP BY trade_date").fetchall())
