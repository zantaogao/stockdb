import sqlite3, glob, os
dbs = glob.glob(os.path.expanduser('~/.hermes/stockdb/**/*.db'), recursive=True)
for db in dbs:
    try:
        con = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
        cur = con.cursor()
        tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        cands = [x for x in tables if any(k in x.lower() for k in ('trade','order','transaction','flow','held','position'))]
        for tbl in cands:
            cols = [c[1] for c in cur.execute(f'PRAGMA table_info("{tbl}")')]
            datecol = next((c for c in cols if 'date' in c.lower() or 'time' in c.lower()), None)
            if not datecol:
                continue
            try:
                rows = cur.execute(f'SELECT * FROM "{tbl}" WHERE "{datecol}" LIKE ? OR "{datecol}" LIKE ?', ('%2026-09-03%','%20260903%')).fetchall()
                if rows:
                    print('===', os.path.basename(db), tbl, cols)
                    for r in rows[:30]:
                        print(r)
            except Exception:
                pass
        con.close()
    except Exception:
        pass