import sqlite3
c = sqlite3.connect('/Users/zantao/.hermes/stockdb/ledger.db', timeout=15)
print('strategy_accounts tables:', c.execute("SELECT name FROM sqlite_master WHERE name LIKE 'strategy%'").fetchall())
print(c.execute("SELECT date, nav, cash, pos_value, n_pos, daily_ret, market_ret FROM strategy_accounts WHERE account_id='agent_auto' ORDER BY date DESC LIMIT 6").fetchall())
