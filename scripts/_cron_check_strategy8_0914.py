#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""只读：nav_history 同日重复检查 + cron 执行状态"""
import sqlite3, os, json, glob, collections

os.chdir(os.path.expanduser("~/.hermes/stockdb"))
print("=== nav_history 同日重复（09-05 双记录 bug 复查）===")
for p in sorted(glob.glob("sim_accounts/*.json")):
    b = os.path.basename(p)
    if b.startswith("_") or ".old_" in b or ".err." in b:
        continue
    try:
        d = json.load(open(p, encoding="utf-8"))
    except Exception as e:
        print(f"  {b}: LOAD_ERR {e}")
        continue
    nh = d.get("nav_history") or []
    dates = [x.get("date") for x in nh]
    dup = [k for k, v in collections.Counter(dates).items() if v > 1 and k and k >= "2026-09-14"]
    last3 = nh[-3:]
    print(f"  {b:24s} n={len(nh)} last={dates[-1] if dates else None} dup_today={dup} last3={last3}")

print("\n=== cron executions: 051af215dc32 最近 8 次 ===")
for dbname in ("executions.db",):
    path = os.path.expanduser("~/.hermes/cron/" + dbname)
    if not os.path.exists(path):
        print("  no", path)
        continue
    con = sqlite3.connect(path)
    tabs = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    print("  tables:", tabs)
    for t in tabs:
        cols = [r[1] for r in con.execute("PRAGMA table_info(%s)" % t)]
        print(f"  -- {t} cols={cols}")
        try:
            for r in con.execute("SELECT * FROM %s ORDER BY rowid DESC LIMIT 8" % t):
                print("    ", r)
        except Exception as e:
            print("    ERR", e)
    con.close()
