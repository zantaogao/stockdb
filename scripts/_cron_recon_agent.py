import sqlite3, json
c = sqlite3.connect('/Users/zantao/.hermes/stockdb/ledger.db', timeout=15)
print(c.execute("SELECT trade_date, direction, code, quantity, price, amount, trade_time FROM trade_log WHERE strategy='agent_auto' AND trade_date>='2026-09-23' ORDER BY rowid").fetchall())
print(c.execute("SELECT cash FROM strategy_accounts_meta WHERE account_id='agent_auto'").fetchall())
