#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""短轮询：等 14:55 tick 写库（最多100s），看 fusion_center 今日行是否被修正"""
import os, json, time, sqlite3, datetime
os.chdir(os.path.expanduser("~/.hermes/stockdb"))
c = sqlite3.connect("ledger.db", timeout=5)
old = c.execute("SELECT created_at,nav,pos_value FROM strategy_accounts WHERE account_id='fusion_center' AND date='20260914'").fetchone()
print("起始:", old, " now:", datetime.datetime.now().strftime("%H:%M:%S"))
for i in range(20):
    time.sleep(5)
    try:
        cur = c.execute("SELECT created_at,nav,pos_value,daily_ret,n_pos FROM strategy_accounts WHERE account_id='fusion_center' AND date='20260914'").fetchone()
    except Exception as e:
        print("  read err", e); continue
    if cur and cur[0] != old[0]:
        print("已更新 ->", cur, " at", datetime.datetime.now().strftime("%H:%M:%S"))
        rows = c.execute("SELECT shares,avg_cost FROM strategy_positions WHERE account_id='fusion_center'").fetchall()
        cost = sum(x[0] * x[1] for x in rows)
        print(f"  成本口径汇总 = {cost:,.0f} （落库 pos_value={cur[2]:,.0f}）")
        d = json.load(open("sim_accounts/fusion_center.json", encoding="utf-8"))
        print("  JSON 尾条:", (d.get("nav_history") or [])[-1])
        break
    if i % 3 == 2:
        print(f"  ...{datetime.datetime.now().strftime('%H:%M:%S')} 仍为 {cur[0]}", flush=True)
else:
    print("100s 内未更新（14:55 tick 可能仍在跑或未落库）")
c.close()
