import duckdb, sqlite3, os, json
from collections import defaultdict
BASE = os.path.expanduser('~/.hermes/stockdb')
conn = duckdb.connect(os.path.join(BASE,'tushare.db'), read_only=True)

# 板块表
print("== board_daily 样本 ==")
try:
    for r in conn.execute("SELECT DISTINCT board_code FROM board_daily LIMIT 20").fetchall(): print(r)
    print("maxdate", conn.execute("SELECT MAX(date) FROM board_daily").fetchone())
except Exception as e: print("ERR", e)

# stock_industry 映射可能在 signals.db 或 ledger
for db in ['signals.db','ledger.db']:
    s = sqlite3.connect(os.path.join(BASE,db))
    tabs=[r[0] for r in s.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    print(db, [t for t in tabs if 'indus' in t.lower() or 'sw' in t.lower()])
    s.close()
