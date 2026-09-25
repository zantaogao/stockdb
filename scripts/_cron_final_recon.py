import sqlite3
c = sqlite3.connect('/Users/zantao/.hermes/stockdb/ledger.db', timeout=15)
print('agent_auto today rows:')
for r in c.execute("SELECT trade_time, direction, code, name, quantity, price, amount, notes FROM trade_log WHERE strategy='agent_auto' AND trade_date='2026-09-24' ORDER BY rowid").fetchall():
    print(r)
print('meta cash:', c.execute("SELECT cash, updated_at FROM strategy_accounts_meta WHERE account_id='agent_auto'").fetchall())
print('positions:')
for r in c.execute("SELECT code, name, shares, avg_cost, buy_date FROM strategy_positions WHERE account_id='agent_auto' ORDER BY code").fetchall():
    print(r)
