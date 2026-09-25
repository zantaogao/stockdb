#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""只读核查：20260914 策略账户日更 13:45 tick"""
import sqlite3, os, json, glob

os.chdir(os.path.expanduser("~/.hermes/stockdb"))
c = sqlite3.connect("ledger.db")

print("=== strategy_accounts_meta ===")
cols = [r[1] for r in c.execute("PRAGMA table_info(strategy_accounts_meta)").fetchall()]
print("cols:", cols)
for r in c.execute("SELECT * FROM strategy_accounts_meta").fetchall():
    d = dict(zip(cols, r))
    cj = d.get("config_json")
    if isinstance(cj, str) and len(cj) > 300:
        try:
            j = json.loads(cj)
            keep = {k: j[k] for k in j if k in ("manual", "closed", "last_rebalance_date", "enabled", "mode", "note")}
            d["config_json"] = keep if keep else str(cj)[:200]
        except Exception:
            d["config_json"] = str(cj)[:200]
    print("  ", d)

print("\n=== strategy_accounts 20260911-20260914 ===")
cols2 = [r[1] for r in c.execute("PRAGMA table_info(strategy_accounts)").fetchall()]
print("cols:", cols2)
for r in c.execute("SELECT * FROM strategy_accounts WHERE date>='20260910' ORDER BY date DESC, account_id").fetchall():
    print("  ", dict(zip(cols2, r)))

print("\n=== 今日流水 ledger.trade_log ===")
tl = [r[1] for r in c.execute("PRAGMA table_info(trade_log)").fetchall()]
print("cols:", tl)
rows = c.execute("SELECT * FROM trade_log WHERE REPLACE(CAST(trade_date AS VARCHAR),'-','')='20260914' ORDER BY rowid").fetchall()
print("rows_today:", len(rows))
for r in rows:
    print("  ", r)

print("\n=== strategy_positions 汇总 ===")
for r in c.execute("SELECT account_id, COUNT(*), SUM(shares), ROUND(SUM(total_cost),0) FROM strategy_positions GROUP BY account_id ORDER BY account_id"):
    print("  ", r)

print("\n=== sim_accounts JSON 概况 ===")
for p in sorted(glob.glob("sim_accounts/*.json")):
    if os.path.basename(p).startswith("_") or ".old_" in p or ".err." in p:
        continue
    try:
        d = json.load(open(p, encoding="utf-8"))
    except Exception as e:
        print("  ", os.path.basename(p), "LOAD_ERR", e)
        continue
    nh = d.get("nav_history") or []
    print(f"   {os.path.basename(p):34s} closed={d.get('closed')} manual={d.get('manual')} "
          f"last_nav={(nh[-1].get('date') if nh else None)} n_pos={len(d.get('positions') or [])} "
          f"last_rebal={d.get('last_rebalance_date')}")
c.close()
