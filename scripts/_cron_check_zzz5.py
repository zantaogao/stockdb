import sqlite3, os
from collections import Counter
base = os.path.expanduser('~/.hermes/stockdb')
# state.db.pre_split is the frozen pre-migration source
s = sqlite3.connect(f'file:{base}/state.db.pre_split?mode=ro', uri=True)
tabs = [r[0] for r in s.execute("SELECT name FROM sqlite_master WHERE type='table'")]
print('pre_split has stock_basic:', 'stock_basic' in tabs)
d = sqlite3.connect(f'{base}/ledger.db', timeout=10)
codes = [r[0] for r in d.execute("SELECT stock_code FROM holdings").fetchall()]
cnt = Counter()
for code in codes:
    if 'stock_basic' in tabs:
        r = s.execute("SELECT industry FROM stock_basic WHERE stock_code=?", (code,)).fetchone()
        ind = (r[0][:3] if r and r[0] and len(r[0]) >= 2 else 'ZZZ')
    else:
        ind = '?'
    cnt[ind] += 1
print('real industry counts of holdings:', cnt.most_common(15))
print('total holdings:', len(codes))