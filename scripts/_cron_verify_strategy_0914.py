#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""策略账户日更监督核查：closed 标记 + 最新NAV日期 + 今日成交"""
import json, os, glob, sqlite3

SA = os.path.expanduser("~/.hermes/stockdb/sim_accounts")
print("=== sim_accounts JSON ===")
for p in sorted(glob.glob(os.path.join(SA, "*.json"))):
    if ".old_" in p or ".err." in p:
        continue
    try:
        d = json.load(open(p, encoding="utf-8"))
    except Exception as e:
        print(f"{os.path.basename(p)}: LOAD_ERR {e}")
        continue
    nh = d.get("nav_history") or []
    last = str(nh[-1].get("date")) if nh else "NONE"
    print(f"{os.path.basename(p):28s} closed={d.get('closed')} manual={d.get('manual')} "
          f"nav={d.get('nav')} last_nav_date={last} n_hist={len(nh)} n_pos={len(d.get('positions') or [])}")

LED = os.path.expanduser("~/.hermes/stockdb/ledger.db")
print("\n=== ledger.db tables ===")
con = sqlite3.connect(LED)
tab = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
print(tab)
for t in tab:
    cols = [r[1] for r in con.execute(f"PRAGMA table_info({t})").fetchall()]
    if any(c in cols for c in ("date", "trade_date", "ts")):
        dc = "date" if "date" in cols else ("trade_date" if "trade_date" in cols else "ts")
        try:
            n = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            print(f"\n-- {t} ({n} rows) cols={cols}")
            rows = con.execute(
                f"SELECT * FROM {t} WHERE REPLACE(CAST({dc} AS VARCHAR),'-','') LIKE '2026091%' "
                f"ORDER BY {dc} DESC LIMIT 15").fetchall()
            for r in rows:
                print("   ", r)
        except Exception as e:
            print(f"   {t} ERR {e}")
con.close()
