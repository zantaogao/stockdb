import duckdb, sqlite3, glob, os
for db in glob.glob('/Users/zantao/.hermes/stockdb/*.db') + glob.glob('/Users/zantao/.hermes/stockdb/*.duckdb'):
    try:
        con = duckdb.connect(db, read_only=True)
        tabs = [r[0] for r in con.execute("show tables").fetchall()]
        hit = [t for t in tabs if 'cal' in t.lower()]
        if hit:
            print(db, hit)
            for t in hit:
                try:
                    print(con.execute(f"select cal_date,is_open from {t} where cal_date in ('2026-10-01','20261001')").fetchall())
                except Exception as e:
                    print(' err', e)
        con.close()
    except Exception:
        pass
    try:
        con = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
        tabs = [r[0] for r in con.execute("select name from sqlite_master where type='table'")]
        hit = [t for t in tabs if 'cal' in t.lower()]
        if hit:
            print(db, hit, '(sqlite)')
            for t in hit:
                try:
                    print(con.execute(f"select cal_date,is_open from {t} where cal_date in ('2026-10-01','20261001')").fetchall())
                except Exception as e:
                    print(' err', e)
        con.close()
    except Exception:
        pass
