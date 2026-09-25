import duckdb, sqlite3, os, re, glob
H = os.path.expanduser('~/.hermes/stockdb')
# 找 sw_daily_raw / stock_industry_raw 所在库
cands = glob.glob(os.path.expanduser('~/.hermes/**/*.db'), recursive=True) + glob.glob(os.path.expanduser('~/.hermes/**/*.duckdb'), recursive=True)
for p in set(cands):
    if os.path.getsize(p) == 0: continue
    try:
        names = [x[0] for x in duckdb.connect(p, read_only=True).execute("SHOW TABLES").fetchall()]
    except Exception:
        try:
            names = [x[0] for x in sqlite3.connect(f'file:{p}?mode=ro', uri=True).execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        except Exception:
            continue
    hits = [n for n in names if 'sw_daily' in n or 'stock_industry' in n]
    if hits: print(p, hits)
