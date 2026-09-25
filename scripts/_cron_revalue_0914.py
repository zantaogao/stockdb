#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""14:45 tick 全账户估值复核：库内 pos_value vs 实时价市值 vs 成本市值"""
import sys, os, sqlite3, datetime
sys.path.insert(0, os.path.expanduser("~/.hermes/stockdb"))
os.chdir(os.path.expanduser("~/.hermes/stockdb"))
from core.prices import fetch_prices_batch
print("now:", datetime.datetime.now().strftime("%H:%M:%S"))
c = sqlite3.connect("ledger.db")
for aid in ("agent_auto", "center_dual", "cmmr", "cmmr_fusion", "fusion_center"):
    row = c.execute("SELECT nav,cash,pos_value,daily_ret,n_pos,created_at FROM strategy_accounts WHERE account_id=? AND date='20260914'", (aid,)).fetchone()
    pos = c.execute("SELECT code,shares,avg_cost FROM strategy_positions WHERE account_id=?", (aid,)).fetchall()
    codes = [p[0] for p in pos]
    px = fetch_prices_batch(codes)
    mv = sum(p[1] * (px.get(p[0]) or p[2]) for p in pos)
    cost = sum(p[1] * p[2] for p in pos)
    n_missing = len([p for p in pos if p[0] not in px])
    print(f"[{aid}] 库内 nav={row[0]:,.0f} pos={row[2]:,.0f} ret={row[3]}% n={row[4]} [{row[5]}]")
    print(f"    实时市值={mv:,.0f} 成本市值={cost:,.0f} 实时NAV={row[1]+mv:,.0f} 缺价={n_missing}/{len(pos)}  → 库内pos_value-实时市值={row[2]-mv:+,.0f}")
c.close()
