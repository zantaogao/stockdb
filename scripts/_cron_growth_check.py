import duckdb, os
con = duckdb.connect(os.path.expanduser('~/.hermes/growth/growth.db'), read_only=True)
tabs = [r[0] for r in con.execute("SHOW TABLES").fetchall()]
print('tables:', tabs)
for t in tabs:
    cols = [c[0] for c in con.execute(f"DESCRIBE {t}").fetchall()]
    dcol = next((c for c in cols if 'day' in c.lower() or 'date' in c.lower() or 'time' in c.lower()), None)
    if dcol:
        rows = con.execute(f"SELECT {dcol}, COUNT(*) FROM {t} WHERE CAST({dcol} AS VARCHAR) >= '2026-09-26' GROUP BY 1 ORDER BY 1").fetchall()
        print(t, dcol, rows)
con.close()
