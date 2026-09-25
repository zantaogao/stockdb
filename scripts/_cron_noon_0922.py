import sqlite3, json, os
os.chdir('/Users/zantao/.hermes/stockdb')
c = sqlite3.connect('ledger.db')
print('=== 今日(2026-09-22) trade_log ===')
cols = [r[1] for r in c.execute("PRAGMA table_info(trade_log)")]
print('cols:', cols)
rows = c.execute("SELECT * FROM trade_log WHERE trade_date LIKE '2026-09-22%' OR trade_date LIKE '20260922%' ORDER BY rowid").fetchall()
for r in rows: print(r)
print('rows:', len(rows))
print()
print('=== 账户现金 ===')
for r in c.execute("SELECT * FROM account_balance").fetchall(): print(r)
print()
print('=== 持仓(现价/成本/股数) ===')
cols2 = [r[1] for r in c.execute("PRAGMA table_info(holdings)")]
print('cols:', cols2)
for r in c.execute("SELECT * FROM holdings").fetchall(): print(r)
