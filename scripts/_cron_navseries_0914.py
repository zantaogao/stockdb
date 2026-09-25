#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""①今日 fusion_center 各 tick NAV 序列 ②成本兜底假设检验（cost sum vs 落库 pos_value）"""
import os, re, glob, sqlite3, datetime
os.chdir(os.path.expanduser("~/.hermes/stockdb"))

print("=== 今日 各 tick 落库/报告的 fusion_center NAV 序列 ===")
pat = re.compile(r"中枢版Top10 \(fusion_center\)\s+最新 (\d+)\s+NAV=([\d,]+)\s+当日([-+]?[\d.]+)%")
files = sorted(glob.glob(os.path.expanduser("~/.hermes/cron/output/051af215dc32/*.md")))
files = [f for f in files if "2026-09-14" in f]
for f in files:
    txt = open(f, encoding="utf-8", errors="ignore").read()
    m = pat.search(txt)
    if m:
        print(f"  {os.path.basename(f)[11:19]}  date={m.group(1)} NAV={m.group(2)} ret={m.group(3)}%")

c = sqlite3.connect("ledger.db")
rows = c.execute("SELECT code,name,shares,avg_cost FROM strategy_positions WHERE account_id='fusion_center'").fetchall()
cost_sum = sum(r[2] * r[3] for r in rows)
print(f"\n=== fusion_center 持仓 {len(rows)} 只 ===")
print(f"  成本市值合计 sum(shares*avg_cost) = {cost_sum:,.0f}")
r = c.execute("SELECT nav,cash,pos_value FROM strategy_accounts WHERE account_id='fusion_center' AND date='20260914'").fetchone()
print(f"  落库 14:45: nav={r[0]:,.0f} cash={r[1]:,.0f} pos_value={r[2]:,.0f}")
print(f"  落库 pos_value - 成本合计 = {r[2]-cost_sum:,.0f}")
print(f"  若全按成本兜底 NAV 应为 = {r[1]+cost_sum:,.0f}")
for d in ("20260910","20260911","20260914"):
    rr = c.execute("SELECT nav,cash,pos_value,n_pos FROM strategy_accounts WHERE account_id='fusion_center' AND date=?", (d,)).fetchone()
    print(f"  {d}: {rr}")
c.close()
