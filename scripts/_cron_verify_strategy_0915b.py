import sqlite3, os, json, glob, subprocess, time
from datetime import datetime

SD = os.path.expanduser("~/.hermes/stockdb")
c = sqlite3.connect(os.path.join(SD, "ledger.db"), timeout=15)
c.row_factory = sqlite3.Row
cols = [r[1] for r in c.execute("PRAGMA table_info(strategy_accounts_legacy)")]
print("legacy cols:", cols)
rows = c.execute("SELECT * FROM strategy_accounts_legacy WHERE date >= '20260915' ORDER BY date, created_at").fetchall()
print(f"\n== strategy_accounts_legacy 20260915 rows: {len(rows)}")
for r in rows:
    d = dict(r)
    print("  ", d)

print("\n== sim_accounts json nav tail ==")
for f in sorted(glob.glob(os.path.join(SD, "sim_accounts", "*.json"))):
    try:
        j = json.load(open(f))
    except Exception as e:
        print(f, "ERR", e); continue
    keys = list(j.keys())
    nav = j.get("nav") or j.get("nav_history") or []
    tail = nav[-4:] if isinstance(nav, list) else nav
    print(f"\n-- {os.path.basename(f)} keys={keys[:12]}")
    print(f"   mtime={datetime.fromtimestamp(os.path.getmtime(f)):%Y-%m-%d %H:%M:%S} cash={j.get('cash')} npos={len(j.get('positions') or [])}")
    print(f"   last_rebalance_date={j.get('last_rebalance_date')}")
    print(f"   nav_tail={tail}")
