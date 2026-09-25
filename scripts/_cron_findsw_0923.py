import duckdb, sqlite3, os
from collections import defaultdict
BASE = os.path.expanduser('~/.hermes/stockdb')
conn = duckdb.connect(os.path.join(BASE,'tushare.db'), read_only=True)

# 找 sw / 行业映射表（含 growth.db 等）
import glob
for p in glob.glob(os.path.expanduser('~/.hermes/**/*.db'), recursive=True):
    try:
        c2 = duckdb.connect(p, read_only=True)
        tabs=[r[0] for r in c2.execute("SHOW TABLES").fetchall()]
        hit=[t for t in tabs if 'sw' in t.lower() or 'industry' in t.lower()]
        if hit: print(p, hit)
        c2.close()
    except Exception:
        try:
            c3 = sqlite3.connect(p)
            tabs=[r[0] for r in c3.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
            hit=[t for t in tabs if 'sw' in t.lower() or 'industry' in t.lower()]
            if hit: print(p, hit)
            c3.close()
        except Exception: pass
