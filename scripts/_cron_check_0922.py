import sqlite3
con = sqlite3.connect('/Users/zantao/.hermes/stockdb/ledger.db')
print("== trades today (strategy accounts) ==")
for r in con.execute("SELECT trade_date,trade_time,strategy,code,name,direction,price,quantity,notes FROM trade_log WHERE trade_date='2026-09-22' ORDER BY trade_time"):
    print(r)
print("== strategy_positions count per account ==")
for r in con.execute("SELECT account_id, COUNT(*), MIN(buy_date), MAX(buy_date) FROM strategy_positions GROUP BY account_id"):
    print(r)
print("== nav legacy last 3 days ==")
for r in con.execute("SELECT account_id,date,nav,daily_ret FROM strategy_accounts_legacy WHERE date>='20260921' ORDER BY date,account_id"):
    print(r)
