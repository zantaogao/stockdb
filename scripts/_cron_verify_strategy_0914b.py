#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""核查2：今日成交逐日计数 + nav_history 同日去重 + 现金/持仓勾稽"""
import json, os, sqlite3, collections

SD = os.path.expanduser("~/.hermes/stockdb")
con = sqlite3.connect(os.path.join(SD, "ledger.db"))
print("=== trade_log 近8日计数 ===")
for r in con.execute("SELECT trade_date, COUNT(*), SUM(direction='BUY'), SUM(direction='SELL') "
                     "FROM trade_log GROUP BY trade_date ORDER BY trade_date DESC LIMIT 8"):
    print("  ", r)

print("\n=== 今日(20260914)全部成交 ===")
for r in con.execute("SELECT id,strategy,direction,code,name,price,quantity,amount,trade_time "
                     "FROM trade_log WHERE trade_date='2026-09-14' ORDER BY id"):
    print("  ", r)

print("\n=== strategy_accounts_meta 当前状态 ===")
cols = [c[1] for c in con.execute("PRAGMA table_info(strategy_accounts_meta)")]
print("  cols:", cols)
for r in con.execute("SELECT * FROM strategy_accounts_meta"):
    print("  ", r)

print("\n=== nav_history 同日(横杠归一)重复检查 ===")
for p in sorted(os.listdir(os.path.join(SD, "sim_accounts"))):
    if not p.endswith(".json") or ".old_" in p or ".err." in p:
        continue
    d = json.load(open(os.path.join(SD, "sim_accounts", p), encoding="utf-8"))
    keys = [str(h.get("date", "")).replace("-", "") for h in (d.get("nav_history") or [])]
    dup = [k for k, v in collections.Counter(keys).items() if v > 1]
    print(f"  {p:22s} n={len(keys)} dup={dup} last3={keys[-3:]}")
con.close()
