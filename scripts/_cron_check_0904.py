import sqlite3, glob, os
base = os.path.expanduser("~/.hermes/stockdb")
c = sqlite3.connect(f"file:{base}/ledger.db?mode=ro", uri=True)
tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
print("tables:", tables)
for t in tables:
    if "trade" in t or "strat" in t or "nav" in t or "account" in t:
        cols = [r[1] for r in c.execute(f"PRAGMA table_info({t})").fetchall()]
        print(t, cols)
# find date-ish column and dump 20260904 rows
for t in tables:
    if not ("trade" in t or "strat" in t):
        continue
    cols = [r[1] for r in c.execute(f"PRAGMA table_info({t})").fetchall()]
    dcol = None
    for cand in ("date","trade_date","ts","day"):
        if cand in cols:
            dcol = cand
            break
    if dcol is None:
        continue
    try:
        rows = c.execute(f"SELECT * FROM {t} WHERE {dcol} IN ('20260904','2026-09-04') ORDER BY rowid DESC LIMIT 30").fetchall()
        print(f"--- {t} 20260904: {len(rows)} rows")
        for r in rows[:20]:
            print(r)
    except Exception as e:
        print(t, "ERR", e)