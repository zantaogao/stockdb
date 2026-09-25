import sqlite3, os
base = os.path.expanduser("~/.hermes/stockdb")
for name in ["ledger.db","signals.db"]:
    p = os.path.join(base, name)
    if not os.path.exists(p):
        import glob
        hits = glob.glob(base+"/**/"+name, recursive=True)
        p = hits[0] if hits else None
    print("==", name, p)
    if not p: continue
    con = sqlite3.connect(p); cur = con.cursor()
    tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    for t in tables:
        cols = [c[1] for c in cur.execute(f"PRAGMA table_info('{t}')")]
        datecol = None
        for c in ("date","trade_date","dt","day","trade_dt"):
            if c in cols: datecol=c; break
        if datecol and any(k in t.lower() for k in ("trade","tx","ledger","order","nav","snapshot","position")):
            try:
                rows = cur.execute(f"SELECT * FROM '{t}' WHERE {datecol} IN ('20260922','2026-09-22')").fetchall()
                print(f"-- {t}: {len(rows)} rows on 0922 cols={cols}")
                for r in rows[:20]: print("  ", r)
            except Exception as e:
                print("  err", t, e)
    con.close()
