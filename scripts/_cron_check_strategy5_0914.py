import sqlite3, os
os.chdir(os.path.expanduser('~/.hermes/stockdb'))
c = sqlite3.connect('ledger.db')
c.row_factory = sqlite3.Row
tabs = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
print('TABLES:', [t for t in tabs if 'strategy' in t or 'trade' in t])

print('\n=== strategy_accounts 20260914 ===')
for r in c.execute("SELECT account_id,date,nav,cash,pos_value,daily_ret,n_pos,created_at FROM strategy_accounts WHERE date IN ('20260914','20260911') ORDER BY date,account_id").fetchall():
    print(dict(r))

print('\n=== distinct dates last 8 ===')
for r in c.execute("SELECT DISTINCT date FROM strategy_accounts ORDER BY date DESC LIMIT 8").fetchall():
    print(r[0])

for t in [x for x in tabs if 'trade' in x]:
    cols = [r[1] for r in c.execute("PRAGMA table_info(%s)" % t).fetchall()]
    print('\n--', t, cols)
    dcol = 'trade_date' if 'trade_date' in cols else ('date' if 'date' in cols else None)
    if dcol:
        for r in c.execute("SELECT * FROM %s WHERE REPLACE(%s,'-','')='20260914'" % (t, dcol)).fetchall():
            print('  TODAY:', dict(r))
        for r in c.execute("SELECT * FROM %s ORDER BY %s DESC LIMIT 8" % (t, dcol)).fetchall():
            print('  last:', dict(r))

print('\n=== positions by account ===')
for r in c.execute("SELECT account_id, COUNT(*), ROUND(SUM(shares),0) FROM strategy_positions GROUP BY account_id").fetchall():
    print(tuple(r))
print('\n=== meta cash ===')
for r in c.execute("SELECT account_id,name,initial_capital,cash,updated_at,substr(config_json,1,120) FROM strategy_accounts_meta").fetchall():
    print(tuple(r))
print('\n=== crash state ===')
try:
    for r in c.execute("SELECT * FROM strategy_crash_state ORDER BY crash_date DESC LIMIT 4").fetchall():
        print(dict(r))
except Exception as e:
    print('ERR', e)
