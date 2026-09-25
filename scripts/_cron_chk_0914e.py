import sqlite3, os
base = os.path.expanduser('~/.hermes/stockdb')
c = sqlite3.connect(os.path.join(base, 'ledger.db'))
c.row_factory = sqlite3.Row
print('view DDL:', c.execute("SELECT sql FROM sqlite_master WHERE name='strategy_accounts'").fetchone()[0])
print('\n=== latest nav rows per account ===')
for r in c.execute("""SELECT account_id, MAX(date) md FROM strategy_accounts GROUP BY account_id"""):
    aid, md = r[0], r[1]
    row = c.execute("SELECT * FROM strategy_accounts WHERE account_id=? AND date=?", (aid, md)).fetchone()
    d = dict(row)
    diff = d['cash'] + d['pos_value'] - d['nav']
    print(f"{aid:14s} {md} nav={d['nav']:.0f} cash={d['cash']:.0f} pos={d['pos_value']:.0f} n_pos={d['n_pos']} daily_ret={d['daily_ret']} diff={diff:.2f} created={d['created_at']}")
print('\n=== dup same-day rows (normalized) last 3 days ===')
for r in c.execute("""SELECT account_id, REPLACE(date,'-','') nd, COUNT(*) k FROM strategy_accounts
                      WHERE REPLACE(date,'-','')>='20260910' GROUP BY account_id, nd HAVING k>1"""):
    print(tuple(r))
print('\n=== agent_auto trades field last 3 entries ===')
import json
d = json.load(open(os.path.join(base, 'sim_accounts', 'agent_auto.json')))
for t in d.get('trades', [])[-4:]:
    print(t)
print('nav tail:', d.get('nav_history', [])[-3:])
