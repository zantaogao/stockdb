#!/usr/bin/env python3
"""cron 巡检 2026-09-15 13:15: 策略账户日更本轮是否有调仓/异常"""
import sqlite3, json, os, glob
from datetime import datetime

DB = '/Users/zantao/.hermes/stockdb/ledger.db'
db = sqlite3.connect(DB)
db.row_factory = sqlite3.Row

print("== objects ==")
for r in db.execute("SELECT type,name FROM sqlite_master WHERE name LIKE '%strateg%' OR name LIKE '%ca_%' ORDER BY type,name"):
    print("  ", r['type'], r['name'])

for tbl in ['strategy_accounts_meta', 'strategy_positions', 'ca_run_log', 'ca_adjustments']:
    try:
        cols = [c[1] for c in db.execute(f"PRAGMA table_info({tbl})")]
    except Exception as e:
        print(f"\n{tbl}: EXC {e}")
        continue
    print(f"\n== {tbl} cols: {cols}")
    try:
        rows = db.execute(f"SELECT * FROM {tbl} ORDER BY rowid DESC LIMIT 15").fetchall()
        for r in rows:
            print("  ", dict(r))
    except Exception as e:
        print("  EXC:", e)

print("\n== trade_log 今天(20260915) & 昨天 ==")
cols = [c[1] for c in db.execute("PRAGMA table_info(trade_log)")]
print(" cols:", cols)
for r in db.execute("SELECT * FROM trade_log WHERE date >= '2026-09-11' ORDER BY rowid DESC LIMIT 25"):
    d = dict(r)
    print("  ", {k: d[k] for k in list(d)[:12]})

print("\n== sim_accounts 文件时间 ==")
for p in sorted(glob.glob('/Users/zantao/.hermes/stockdb/sim_accounts/*.json')):
    st = os.stat(p)
    print(f"  {os.path.basename(p):24s} {datetime.fromtimestamp(st.st_mtime):%Y-%m-%d %H:%M:%S}  {st.st_size}")
db.close()
