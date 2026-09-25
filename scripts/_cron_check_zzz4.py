import sqlite3, os, duckdb
base = os.path.expanduser('~/.hermes/stockdb')
d = sqlite3.connect(f'{base}/ledger.db', timeout=10)
d.execute("ATTACH DATABASE ? AS sig", (f'{base}/signals.db',))
print('ledger tables:', [r[0] for r in d.execute("SELECT name FROM main.sqlite_master WHERE type='table'")])
print('signals tables:', [r[0] for r in d.execute("SELECT name FROM sig.sqlite_master WHERE type='table'")])
# state.db (frozen) — where stock_basic used to live
try:
    s = sqlite3.connect(f'file:{base}/state.db?mode=ro', uri=True)
    print('state.db size tables:', [r[0] for r in s.execute("SELECT name FROM sqlite_master WHERE type='table'")])
except Exception as e:
    print('state.db ERR:', e)
# tushare.db has stock_basic (duckdb)
try:
    t = duckdb.connect(f'file:{base}/tushare.db', read_only=True)
    print('tushare stock_basic sample:', t.execute("SELECT ts_code, industry FROM stock_basic WHERE ts_code LIKE '688186%'").fetchall())
except Exception as e:
    print('tushare ERR:', e)
# how many holdings -> what industry via tushare
codes = [r[0] for r in d.execute("SELECT stock_code FROM holdings").fetchall()]
print('holdings count:', len(codes))