import sqlite3, json, os, time

DB = os.path.expanduser("~/.hermes/stockdb/ledger.db")
c = sqlite3.connect(DB, timeout=15)
c.row_factory = sqlite3.Row

tabs = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
print("TABLES:", tabs)

for t in tabs:
    if "nav" in t or "trade" in t or "position" in t or "account" in t:
        cols = [r[1] for r in c.execute(f"PRAGMA table_info({t})")]
        print(f"\n== {t} cols={cols}")

print("\n===== NAV 20260910+ =====")
for t in tabs:
    if "nav" in t:
        cols = [r[1] for r in c.execute(f"PRAGMA table_info({t})")]
        dcol = "trade_date" if "trade_date" in cols else ("date" if "date" in cols else cols[1])
        aid = "account_id" if "account_id" in cols else ("aid" if "aid" in cols else cols[0])
        rows = c.execute(f"SELECT * FROM {t} WHERE {dcol} >= '20260910' ORDER BY {dcol}").fetchall()
        print(f"-- {t} ({len(rows)} rows since 20260910)")
        for r in rows:
            print("   ", dict(r))

print("\n===== TRADES today 20260915 =====")
for t in tabs:
    if "trade" in t:
        cols = [r[1] for r in c.execute(f"PRAGMA table_info({t})")]
        print(f"-- {t} cols={cols}")
        dcol = "trade_date" if "trade_date" in cols else ("date" if "date" in cols else None)
        if dcol:
            rows = c.execute(f"SELECT * FROM {t} WHERE REPLACE({dcol},'-','')='20260915'").fetchall()
            print(f"   today rows={len(rows)}")
            for r in rows[:20]:
                print("     ", dict(r))
            rows2 = c.execute(f"SELECT * FROM {t} WHERE REPLACE({dcol},'-','')>='20260911' ORDER BY {dcol} DESC LIMIT 15").fetchall()
            print(f"   last15 since 0911:")
            for r in rows2:
                print("     ", dict(r))

print("\n===== strategy_positions counts =====")
for t in tabs:
    if "position" in t and "strategy" in t:
        cols = [r[1] for r in c.execute(f"PRAGMA table_info({t})")]
        aid = "account_id" if "account_id" in cols else cols[0]
        rows = c.execute(f"SELECT {aid}, COUNT(*) FROM {t} GROUP BY {aid}").fetchall()
        print("  ", t, dict(r) if False else [(r[0], r[1]) for r in rows])
