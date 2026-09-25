import sqlite3, os
p = os.path.expanduser('~/.hermes/stockdb/ledger.db')
con = sqlite3.connect(p)
for r in con.execute("SELECT account_id, date, nav, daily_ret FROM strategy_accounts_legacy WHERE date IN ('20260922','20260923') ORDER BY account_id, date"):
    print(r)
