#!/usr/bin/env python3
"""Check etf_scores gap + factor_ic_daily schema + watchlist."""
import sqlite3, os, glob, json

BASE = "/Users/zantao/.hermes/stockdb"
c = sqlite3.connect(os.path.join(BASE, "state.db"), timeout=5)

print("== factor_ic_daily schema ==")
cols = [r[1] for r in c.execute("PRAGMA table_info(factor_ic_daily)").fetchall()]
print("cols:", cols)
mx = c.execute("SELECT MAX(date) FROM factor_ic_daily").fetchone()[0]
print("MAX(signal_date):", mx)

print("\n== etf_scores ==")
rows = c.execute("SELECT scan_date, count(*) FROM etf_scores GROUP BY scan_date ORDER BY scan_date DESC LIMIT 6").fetchall()
for r in rows:
    print(r)
tot = c.execute("SELECT count(*) FROM etf_scores").fetchone()[0]
print("total rows:", tot)

print("\n== watchlist ==")
rows = c.execute("SELECT scan_date, count(*) FROM watchlist GROUP BY scan_date ORDER BY scan_date DESC LIMIT 5").fetchall()
for r in rows:
    print(r)
c.close()

print("\n== etf/ic related logs (7/29-7/31) ==")
for p in sorted(glob.glob(os.path.join(BASE, "logs", "*etf*")) + glob.glob(os.path.join(BASE, "logs", "*2026073*")) + glob.glob(os.path.join(BASE, "logs", "*20260731*")) + glob.glob(os.path.join(BASE, "logs", "*20260730*"))):
    print(f"--- {os.path.basename(p)} ({os.path.getsize(p)}B, mtime {os.path.getmtime(p)})")
    with open(p, "r", errors="replace") as f:
        print(f.read()[:600])

print("\n== cron jobs.json ETF entries (last_status) ==")
try:
    jobs = json.load(open(os.path.expanduser("~/.hermes/cron/jobs.json")))
    items = jobs if isinstance(jobs, list) else jobs.get("jobs", jobs)
    def walk(o):
        if isinstance(o, dict):
            s = json.dumps(o, ensure_ascii=False)
            if "etf" in s.lower() or "ic_daily" in s:
                print("---", str(o.get("id", ""))[:16], "|", str(o.get("name", ""))[:40], "| schedule:", o.get("schedule", o.get("cron", "")), "| last_status:", o.get("last_status"), "| last_run:", o.get("last_run_at", o.get("last_run", "")))
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(items)
except Exception as e:
    print("cron jobs read err:", e)
