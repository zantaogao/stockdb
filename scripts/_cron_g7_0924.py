import sqlite3, os, json
BASE = os.path.expanduser('~/.hermes/stockdb')
lc = sqlite3.connect(BASE + '/ledger.db'); lc.row_factory = sqlite3.Row
cols = [r[1] for r in lc.execute("PRAGMA table_info(strategy_positions)")]
print('cols', cols)
rows = [dict(r) for r in lc.execute("SELECT * FROM strategy_positions").fetchall()]
print('n', len(rows))
r7 = []
for r in rows:
    ac = r.get('avg_cost'); px = r.get('latest_price') or r.get('current_price')
    if ac and px and ac > 0:
        r7.append((r.get('account_id'), r.get('code'), r.get('name'), round(ac,2), round(px,2), round((px/(ac*0.94)-1)*100, 2), r.get('shares')))
r7.sort(key=lambda x: x[5])
for x in r7[:14]: print(x)
print('R7 hits (<=0):', [x for x in r7 if x[5] <= 0])
