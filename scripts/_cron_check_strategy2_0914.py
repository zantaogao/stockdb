import sqlite3, os, json
os.chdir(os.path.expanduser('~/.hermes/stockdb'))
c = sqlite3.connect('ledger.db')
print('=== latest NAV per account (strategy_accounts) ===')
for r in c.execute("""SELECT account_id, MAX(date) mx FROM strategy_accounts GROUP BY account_id ORDER BY account_id""").fetchall():
    aid, mx = r
    row = c.execute("SELECT date,nav,cash,pos_value,daily_ret,n_pos,created_at FROM strategy_accounts WHERE account_id=? AND date=?",(aid,mx)).fetchone()
    print(aid, row)
print('=== recent dates global (last 5 distinct) ===')
for r in c.execute("SELECT DISTINCT date FROM strategy_accounts ORDER BY date DESC LIMIT 6").fetchall():
    print(r[0])
    for x in c.execute("SELECT account_id,nav,n_pos FROM strategy_accounts WHERE date=? ORDER BY account_id",(r[0],)).fetchall():
        print('   ', x)
print('=== meta ===')
for r in c.execute("SELECT account_id,name,initial_capital,cash,config_json,updated_at FROM strategy_accounts_meta").fetchall():
    print(r[0], r[1], r[2], r[3], str(r[4])[:300], r[5])
print('=== ledger strategy_positions per account ===')
for r in c.execute("SELECT account_id, COUNT(*), SUM(shares) FROM strategy_positions GROUP BY account_id").fetchall():
    print(r)
print('=== account_balance ===')
for r in c.execute("SELECT * FROM account_balance").fetchall():
    print(r)
