import sqlite3, json, glob, os, datetime
base = '/Users/zantao/.hermes/stockdb'
c = sqlite3.connect(base + '/ledger.db')
rows = c.execute("SELECT id,strategy,code,direction,price,quantity,trade_date,trade_time,notes,signal_score FROM trade_log WHERE id IS NULL ORDER BY trade_date,strategy,code").fetchall()
print('null-id total:', len(rows))
from collections import Counter
print(Counter((r[1], r[6]) for r in rows))
for r in rows[:45]:
    print(r)
# JSON modification times
for f in sorted(glob.glob(base + '/sim_accounts/*.json')):
    st = os.stat(f)
    print(os.path.basename(f), 'mtime', datetime.datetime.fromtimestamp(st.st_mtime))
# full positions of fusion3f / fusion_dual
for f in ('fusion3f','fusion_dual'):
    d = json.load(open(f'{base}/sim_accounts/{f}.json'))
    print(f, 'all positions:', [(x.get('code'), x.get('shares')) for x in d.get('positions', [])], 'cash', d.get('cash'))
    last = [t for t in d.get('trades', [])][-3:]
    print(f, 'last trades:', last)
