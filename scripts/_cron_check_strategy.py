import sqlite3, os
BASE = os.path.expanduser('~/.hermes/stockdb/')
c = sqlite3.connect('file:' + BASE + 'ledger.db?mode=ro', uri=True)
print('== trades today (trade_log, strategy accounts) ==')
for r in c.execute("SELECT trade_date,trade_time,strategy,direction,code,name,price,quantity,amount FROM trade_log WHERE trade_date IN ('20260901','2026-09-01') AND strategy IS NOT NULL AND strategy != '' ORDER BY trade_time"):
    print(r)
print('== crash_state recent ==')
for r in c.execute("SELECT * FROM strategy_crash_state ORDER BY created_at DESC LIMIT 5"):
    print(r)
print('== positions count per account ==')
for r in c.execute("SELECT account_id, COUNT(*), SUM(shares) FROM strategy_positions GROUP BY account_id"):
    print(r)
print('== meta updated ==')
for r in c.execute("SELECT account_id, name, cash, updated_at FROM strategy_accounts_meta"):
    print(r)