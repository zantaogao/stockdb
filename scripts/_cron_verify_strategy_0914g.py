#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""09-14 14:05 tick：重复行/今日动作/持仓变动 只读核查"""
import sqlite3, os, json, glob, datetime, collections

os.chdir(os.path.expanduser("~/.hermes/stockdb"))
c = sqlite3.connect("ledger.db")

print("=== strategy_accounts 20260914 行数（查重复）===")
for r in c.execute("SELECT account_id, COUNT(*) FROM strategy_accounts WHERE date='20260914' GROUP BY account_id").fetchall():
    print("  ", r)
print("  表结构唯一键:", [x for x in c.execute("PRAGMA index_list(strategy_accounts)").fetchall()])

print("\n=== strategy_positions 今日是否有变动痕迹（updated_at 最近5条）===")
cols = [r[1] for r in c.execute("PRAGMA table_info(strategy_positions)").fetchall()]
print("   cols:", cols)
if "updated_at" in cols:
    for r in c.execute("SELECT * FROM strategy_positions ORDER BY updated_at DESC LIMIT 6").fetchall():
        print("   ", r)

print("\n=== sim_accounts JSON 中今日成交（2026-09-14 / 20260914）===")
for p in sorted(glob.glob("sim_accounts/*.json")):
    b = os.path.basename(p)
    if b.startswith("_") or ".old_" in b or ".err." in b:
        continue
    d = json.load(open(p, encoding="utf-8"))
    tr = d.get("trades") or []
    today = [t for t in tr if str(t.get("date") or t.get("trade_date") or "")[:10].replace("-", "") == "20260914"]
    nh = d.get("nav_history") or []
    print(f"  {b:24s} n_trades={len(tr)} today={len(today)} nav={nh[-1] if nh else None}")
    for t in today:
        print("      ", t)

print("\n=== 最近 5 个交易日 NAV 序列（各账户）===")
for aid, in c.execute("SELECT DISTINCT account_id FROM strategy_accounts ORDER BY account_id").fetchall():
    rows = c.execute("SELECT date, nav, daily_ret, n_pos FROM strategy_accounts WHERE account_id=? ORDER BY date DESC LIMIT 5", (aid,)).fetchall()
    print(f"  [{aid}]")
    for r in rows:
        print("      ", r)
c.close()

print("\n=== 本任务 cron 输出文件（051af215dc32 最近3份）===")
d = os.path.expanduser("~/.hermes/cron/output/051af215dc32")
fs = sorted(glob.glob(os.path.join(d, "*.md")), key=os.path.getmtime, reverse=True)[:3]
for f in fs:
    print("  ---", os.path.basename(f), datetime.datetime.fromtimestamp(os.path.getmtime(f)).strftime("%m-%d %H:%M"))
    txt = open(f, encoding="utf-8", errors="replace").read()
    print("   len=", len(txt), "head200:", txt[:200].replace("\n", " | "))
