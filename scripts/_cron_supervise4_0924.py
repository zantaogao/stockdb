import sqlite3, json, glob, os
# 1. ledger.db strategy_accounts NAV for today
con = sqlite3.connect("/Users/zantao/.hermes/stockdb/ledger.db")
cur = con.cursor()
try:
    rows = cur.execute("SELECT account_id, date, nav, cash, positions_count FROM strategy_accounts WHERE date>='2026-09-23' OR date>='20260923' ORDER BY account_id, date").fetchall()
    for r in rows: print(r)
except Exception as e:
    print("nav query err:", e)
    cols=[c[1] for c in cur.execute("PRAGMA table_info(strategy_accounts)").fetchall()]
    print("cols:", cols)
    rows = cur.execute("SELECT * FROM strategy_accounts ORDER BY rowid DESC LIMIT 15").fetchall()
    for r in rows: print(r)
con.close()
print("=== sim_accounts json ===")
for f in sorted(glob.glob(os.path.expanduser("~/.hermes/stockdb/sim_accounts/*.json"))):
    d = json.load(open(f))
    navs = d.get("nav_history") or d.get("navs") or []
    last = navs[-2:] if isinstance(navs, list) and navs else navs
    print(os.path.basename(f), "last_nav:", json.dumps(last, ensure_ascii=False)[:200])
