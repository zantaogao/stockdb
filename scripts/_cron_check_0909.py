import sqlite3, os, glob, time
led = '/Users/zantao/.hermes/stockdb/ledger.db'
con = sqlite3.connect(led)
cur = con.cursor()
print('legacy nav latest per acct:')
for r in cur.execute("SELECT account_id, MAX(date), nav FROM strategy_accounts_legacy GROUP BY account_id"):
    print(' ', r)
print('meta updated:')
for r in cur.execute("SELECT account_id, name, cash, updated_at FROM strategy_accounts_meta"):
    print(' ', r)
print('positions:')
for r in cur.execute("SELECT account_id, code, name, shares, buy_date, updated_at FROM strategy_positions ORDER BY account_id"):
    print(' ', r)
con.close()
logs = sorted(glob.glob('/Users/zantao/.hermes/stockdb/logs/*'), key=os.path.getmtime)[-8:]
for L in logs:
    print('---', L, time.ctime(os.path.getmtime(L)))