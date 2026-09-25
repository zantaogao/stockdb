import sqlite3
con = sqlite3.connect("/Users/zantao/.hermes/stockdb/state.db")
cur = con.cursor()
tabs = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
print("tables:", tabs)
for t in tabs:
    cols = [c[1] for c in cur.execute(f"PRAGMA table_info({t})").fetchall()]
    if any("nav" in c.lower() or "date" in c.lower() for c in cols):
        try:
            dcol = next(c for c in cols if "date" in c.lower())
            rows = cur.execute(f"SELECT * FROM {t} WHERE {dcol} LIKE '%20260924%' OR {dcol} LIKE '%2026-09-24%'").fetchall()
            if rows:
                print(f"--- {t} ({dcol}) 20260924 rows: {len(rows)}")
                for r in rows[:8]:
                    print(r)
        except Exception as e:
            print(t, "ERR", e)
con.close()
