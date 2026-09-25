import sqlite3, os
from collections import Counter
base = os.path.expanduser('~/.hermes/stockdb')
d = sqlite3.connect(f'{base}/ledger.db', timeout=10)
cols = [r[1] for r in d.execute("PRAGMA table_info(holdings)")]
print('holdings cols:', cols)
codes = [r[0] for r in d.execute("SELECT code FROM holdings").fetchall()] if 'code' in cols else []
s = sqlite3.connect(f'file:{base}/state.db.pre_split?mode=ro', uri=True)
cnt = Counter()
for code in codes:
    r = s.execute("SELECT industry FROM stock_basic WHERE stock_code=?", (code,)).fetchone()
    ind = (r[0][:3] if r and r[0] and len(r[0]) >= 2 else 'ZZZ')
    cnt[ind] += 1
print('real industry counts of holdings:', cnt.most_common(15), 'total', len(codes))
# recent orders history
import glob, json, time
for f in sorted(glob.glob(f'{base}/orders/*.json'))[-5:]:
    print('---', f, time.ctime(os.path.getmtime(f)))
    try:
        j = json.load(open(f))
        print(json.dumps(j, ensure_ascii=False)[:800])
    except Exception as e:
        print('read err', e)