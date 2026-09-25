import sqlite3, os
base = os.path.expanduser('~/.hermes/stockdb')
d = sqlite3.connect(f'{base}/ledger.db', timeout=10)
d.execute("ATTACH DATABASE ? AS sig", (f'{base}/signals.db',))
tabs = [r[0] for r in d.execute("SELECT name FROM sig.sqlite_master WHERE type IN ('table','view')")]
print('has stock_basic in signals.db:', 'stock_basic' in tabs)
if 'stock_basic' in tabs:
    print('cols:', [r[1] for r in d.execute("PRAGMA sig.table_info(stock_basic)")])
    print('rows:', d.execute("SELECT COUNT(*) FROM sig.stock_basic").fetchone()[0])
    print('sample:', d.execute("SELECT stock_code, industry FROM sig.stock_basic LIMIT 3").fetchall())
    print('688186 ->', d.execute("SELECT industry FROM sig.stock_basic WHERE stock_code='688186'").fetchone())
    # industry counts among holdings (the ZZZ=22 symptom)
    codes = [r[0] for r in d.execute("SELECT stock_code FROM holdings").fetchall()]
    from collections import Counter
    cnt = Counter()
    for code in codes:
        r = d.execute("SELECT industry FROM sig.stock_basic WHERE stock_code=?", (code,)).fetchone()
        ind = (r[0][:3] if r and r[0] and len(r[0]) >= 2 else 'ZZZ')
        cnt[ind] += 1
    print('holdings industry counts:', cnt.most_common(10), 'total holdings', len(codes))