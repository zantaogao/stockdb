import sqlite3, os
base = os.path.expanduser('~/.hermes/stockdb')
c = sqlite3.connect(f'file:{base}/signals.db?mode=ro', uri=True)
tabs = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')")]
print('signals.db tables:', tabs)
if 'stock_basic' in tabs:
    print('cols:', [r[1] for r in c.execute("PRAGMA table_info(stock_basic)")])
    print(c.execute("SELECT * FROM stock_basic LIMIT 3").fetchall())
    print('rows:', c.execute("SELECT COUNT(*) FROM stock_basic").fetchone())
# test the exact query the decision script uses
try:
    d = sqlite3.connect(f'file:{base}/ledger.db?mode=ro', uri=True)
    d.execute("ATTACH DATABASE ? AS sig", (f'{base}/signals.db',))
    r = d.execute("SELECT industry FROM sig.stock_basic WHERE stock_code='688186'").fetchone()
    print('query 688186 ->', r)
    # industries of holdings
    h = [x[0] for x in d.execute("SELECT stock_code FROM holdings").fetchall()]
    print('holdings codes sample:', h[:5], 'count', len(h))
    for code in h[:100]:
        rr = d.execute("SELECT industry FROM sig.stock_basic WHERE stock_code=?", (code,)).fetchone()
        print(code, '->', rr)
except Exception as e:
    print('QUERY ERR:', e)