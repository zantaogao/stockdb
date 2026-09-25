#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""查今日策略账户成交与执行日志（只读）。"""
import sqlite3, os
base = os.path.expanduser("~/.hermes/stockdb")
c = sqlite3.connect("file:%s/ledger.db?mode=ro" % base, uri=True)

for t in ("trade_log", "execution_logs", "trade_signals"):
    cols = [r[1] for r in c.execute("PRAGMA table_info(%s)" % t)]
    print("=== %s cols=%s" % (t, cols))
    try:
        rows = c.execute("SELECT * FROM %s ORDER BY rowid DESC LIMIT 12" % t).fetchall()
        for r in rows:
            print("   ", r)
    except Exception as e:
        print("ERR", e)
    print()

print("=== 今日(含09-14)策略账户持仓 updated_at 明细 ===")
for r in c.execute("""SELECT account_id, COUNT(*) FROM strategy_positions GROUP BY account_id"""):
    print(r)

print("\n=== agent_auto 持仓 ===")
for r in c.execute("SELECT account_id, code, name, shares, avg_cost, buy_date, updated_at FROM strategy_positions WHERE account_id='agent_auto'"):
    print(r)
c.close()

# 找日志
import glob, subprocess
print("\n=== 最近的 strategy 相关日志文件 ===")
cands = glob.glob(os.path.expanduser("~/.hermes/stockdb/logs/*")) + glob.glob(os.path.expanduser("~/.hermes/logs/*"))
cands = [p for p in cands if os.path.isfile(p)]
cands.sort(key=lambda p: os.path.getmtime(p), reverse=True)
for p in cands[:15]:
    import time
    print(time.strftime("%m-%d %H:%M", time.localtime(os.path.getmtime(p))), os.path.getsize(p), p)
