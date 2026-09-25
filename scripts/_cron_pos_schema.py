import sqlite3
c = sqlite3.connect('/Users/zantao/.hermes/stockdb/ledger.db', timeout=30)
print(c.execute("PRAGMA table_info(strategy_positions)").fetchall())
print(c.execute("SELECT * FROM strategy_positions WHERE account_id='agent_auto'").fetchall())
