#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""等到 14:55 tick 落库后，核查 fusion_center 今日行是否被修正（只读）"""
import os, json, time, sqlite3, datetime, glob

target = datetime.datetime.now().replace(hour=14, minute=56, second=40, microsecond=0)
wait = (target - datetime.datetime.now()).total_seconds()
if wait > 0:
    print(f"等待 {wait:.0f}s 到 14:56:40 ...")
    time.sleep(wait)

os.chdir(os.path.expanduser("~/.hermes/stockdb"))
print("now:", datetime.datetime.now().strftime("%H:%M:%S"))
c = sqlite3.connect("ledger.db")
r = c.execute("SELECT date,nav,cash,pos_value,daily_ret,n_pos,created_at FROM strategy_accounts WHERE account_id='fusion_center' ORDER BY date DESC LIMIT 2").fetchall()
print("库内 fusion_center:", r)
rows = c.execute("SELECT code,shares,avg_cost FROM strategy_positions WHERE account_id='fusion_center'").fetchall()
cost = sum(x[1] * x[2] for x in rows)
print(f"成本口径 = cash + cost = {r[0][2] + cost:,.0f}  (pos_value 是否仍≈成本: {r[0][3]:,.0f} vs {cost:,.0f})")
for aid in ("cmmr", "cmmr_fusion", "center_dual", "agent_auto"):
    rr = c.execute("SELECT date,nav,daily_ret,pos_value,created_at FROM strategy_accounts WHERE account_id=? ORDER BY date DESC LIMIT 1", (aid,)).fetchone()
    print(f"  {aid}: {rr}")
c.close()

d = json.load(open("sim_accounts/fusion_center.json", encoding="utf-8"))
print("JSON 尾条:", (d.get("nav_history") or [])[-1])

files = sorted(glob.glob(os.path.expanduser("~/.hermes/cron/output/051af215dc32/2026-09-14_*.md")))
print("最新 output 文件:", os.path.basename(files[-1]))
txt = open(files[-1], encoding="utf-8", errors="ignore").read()
print("含『无实时价』:", txt.count("无实时价"), " 含『停牌』:", txt.count("停牌"))
import re
m = re.search(r"中枢版Top10 \(fusion_center\).*?NAV=([\d,]+)", txt, re.S)
print("最新一份报告里的 fusion_center NAV:", m.group(1) if m else "未解析到")
