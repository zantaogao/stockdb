import sqlite3, os, json, datetime
os.chdir(os.path.expanduser('~/.hermes/stockdb'))
c = sqlite3.connect('ledger.db')
c.row_factory = sqlite3.Row
tabs = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
print('TABLES(strategy*):', [t for t in tabs if 'strategy' in t])

print('\n=== latest NAV per account ===')
for r in c.execute("SELECT account_id, MAX(date) mx FROM strategy_accounts GROUP BY account_id ORDER BY account_id").fetchall():
    aid, mx = r[0], r[1]
    row = c.execute("SELECT date,nav,cash,pos_value,daily_ret,n_pos,created_at FROM strategy_accounts WHERE account_id=? AND date=?", (aid, mx)).fetchone()
    print(f"{aid:14s} last={mx} nav={row['nav']} cash={row['cash']} pos={row['pos_value']} ret={row['daily_ret']} n_pos={row['n_pos']} at={row['created_at']}")

print('\n=== distinct dates last 5, per account rows ===')
for r in c.execute("SELECT DISTINCT date FROM strategy_accounts ORDER BY date DESC LIMIT 5").fetchall():
    d = r[0]
    ids = [x[0] for x in c.execute("SELECT account_id FROM strategy_accounts WHERE date=? ORDER BY account_id", (d,)).fetchall()]
    print(d, '->', len(ids), 'accounts:', ids)

print('\n=== meta ===')
for r in c.execute("SELECT * FROM strategy_accounts_meta").fetchall():
    print(dict(r))

print('\n=== positions by account ===')
for r in c.execute("SELECT account_id, COUNT(*), ROUND(SUM(shares),0), SUM(total_cost) FROM strategy_positions GROUP BY account_id").fetchall():
    print(r[0], 'n=', r[1], 'shares=', r[2], 'cost=', r[3])

print('\n=== agent_auto positions detail ===')
for r in c.execute("SELECT * FROM strategy_positions WHERE account_id='agent_auto'").fetchall():
    print(dict(r))

print('\n=== trades today (strategy_log) ===')
trt = [t for t in tabs if 'trade' in t]
print('trade tables:', trt)
for t in trt:
    cols = [r[1] for r in c.execute("PRAGMA table_info(%s)" % t).fetchall()]
    dcol = 'trade_date' if 'trade_date' in cols else None
    if not dcol: continue
    rows = c.execute("SELECT * FROM %s WHERE REPLACE(%s,'-','')='20260914'" % (t, dcol)).fetchall()
    print('--', t, cols, 'today rows:', len(rows))
    for row in rows: print('   ', dict(row))

print('\n=== crash state ===')
try:
    for r in c.execute("SELECT * FROM strategy_crash_state ORDER BY crash_date DESC LIMIT 3").fetchall():
        print(dict(r))
except Exception as e:
    print('ERR', e)
