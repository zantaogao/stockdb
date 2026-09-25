#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""查 cron executions.db 中 051af215dc32 最近执行 + 再轮询一次库"""
import os, sqlite3, datetime, time
p = os.path.expanduser("~/.hermes/cron/executions.db")
c = sqlite3.connect(p)
tabs = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")]
print("executions.db tables:", tabs)
for t in tabs:
    cols = [r[1] for r in c.execute(f"PRAGMA table_info({t})")]
    if not any(x in cols for x in ("job_id", "id")):
        continue
    print(f"\n-- {t} cols={cols}")
    try:
        rows = c.execute(f"SELECT * FROM {t} WHERE CAST(job_id AS TEXT) LIKE '%051af215dc32%' ORDER BY rowid DESC LIMIT 6").fetchall()
    except Exception as e:
        print("   q err", e); continue
    for r in rows:
        print("   ", r)
c.close()

print("\n=== 再轮询 fusion_center 今日行 60s ===")
os.chdir(os.path.expanduser("~/.hermes/stockdb"))
l = sqlite3.connect("ledger.db", timeout=5)
for i in range(12):
    cur = l.execute("SELECT created_at,nav,pos_value,daily_ret FROM strategy_accounts WHERE account_id='fusion_center' AND date='20260914'").fetchone()
    print(f"  {datetime.datetime.now().strftime('%H:%M:%S')} -> {cur}", flush=True)
    time.sleep(5)
l.close()
