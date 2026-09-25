#!/usr/bin/env python3
"""cron 巡检 2026-09-15 13:15: NAV 行完整性 + 取价兜底痕迹"""
import sqlite3
DB = '/Users/zantao/.hermes/stockdb/ledger.db'
db = sqlite3.connect(f'file:{DB}?mode=ro', uri=True); db.row_factory = sqlite3.Row
tabs = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
cand = [t for t in tabs if 'nav' in t.lower() or 'equity' in t.lower()]
print("nav-like:", cand)
for t in cand:
    cols = [c[1] for c in db.execute(f"PRAGMA table_info({t})")]
    print(f"-- {t} cols={cols}")
    rows = db.execute(f"SELECT * FROM {t} WHERE REPLACE(date,'-','')='20260915' ORDER BY account_id").fetchall()
    for r in rows:
        print("   ", dict(r))
    print("   today rows:", len(rows))
# 是否所有账户都有今天行
print("\n== 今天 NAV 覆盖检查 ==")
rows = db.execute("SELECT account_id, MAX(REPLACE(date,'-','')) mx FROM nav_history GROUP BY account_id ORDER BY account_id").fetchall()
for r in rows:
    print("   ", r[0], r[1])
db.close()
