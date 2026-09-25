import sqlite3, os
con = sqlite3.connect("file:/Users/zantao/.hermes/stockdb/ledger.db?mode=ro", uri=True)
cur = con.cursor()
for t in ("strategy_accounts","trade_log"):
    cols = [c[1] for c in cur.execute(f"PRAGMA table_info({t})")]
    print("==", t, cols)
    dcol = next((c for c in cols if c.lower() in ("date","trade_date","dt","day")), None)
    rows = cur.execute(f"SELECT * FROM {t} WHERE {dcol} IN ('20260924','2026-09-24')").fetchall()
    print(f"  20260924 rows: {len(rows)}")
    for r in rows[:60]: print("   ", r)
# last write sanity: max date in strategy_accounts
print("max date:", cur.execute("SELECT MAX(date) FROM strategy_accounts").fetchone())
con.close()
