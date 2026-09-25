#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""持仓计数与流水自洽核查（只读）：strategy_positions 明细 vs n_pos 历史 vs JSON trades 尾段"""
import sqlite3, os, json, glob

os.chdir(os.path.expanduser("~/.hermes/stockdb"))
c = sqlite3.connect("ledger.db")

for aid in ("cmmr_fusion", "center_dual", "fusion_center", "agent_auto", "cmmr"):
    rows = c.execute("SELECT code,name,shares,buy_date FROM strategy_positions WHERE account_id=? ORDER BY buy_date", (aid,)).fetchall()
    print(f"[{aid}] strategy_positions={len(rows)} (shares==0: {sum(1 for r in rows if not r[2])})")
    for r in rows:
        print("   ", r)
    print()

print("=== n_pos 近 8 日 ===")
for aid in ("cmmr_fusion", "center_dual"):
    print(" [", aid, "]", c.execute("SELECT date,n_pos FROM strategy_accounts WHERE account_id=? ORDER BY date DESC LIMIT 8", (aid,)).fetchall())

print("\n=== JSON trades 尾 6 笔（各账户）===")
for b in ("cmmr_fusion", "center_dual", "fusion_center", "agent_auto"):
    d = json.load(open(f"sim_accounts/{b}.json", encoding="utf-8"))
    tr = d.get("trades") or []
    print(f"  [{b}] n_positions={len(d.get('positions') or [])} n_trades={len(tr)}")
    for t in tr[-6:]:
        print("     ", {k: t.get(k) for k in ("date", "trade_time", "action", "code", "name", "price", "shares")})
    pos = d.get("positions") or []
    if isinstance(pos, list):
        print("      positions:", [(p.get("code"), p.get("shares"), p.get("buy_date")) for p in pos])
    else:
        print("      positions:", pos)
c.close()
