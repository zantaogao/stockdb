import duckdb, glob, os
for db in sorted(glob.glob('/Users/zantao/.hermes/stockdb/*.db') + glob.glob('/Users/zantao/.hermes/stockdb/*.duckdb')):
    try:
        c = duckdb.connect(db, read_only=True)
        tabs = [t[0] for t in c.execute('show tables').fetchall()]
        hits = [t for t in tabs if 'cal' in t.lower()]
        if hits:
            print(db, hits)
            for t in hits:
                try:
                    print('  ', c.execute(f"select * from {t} where cal_date in ('20261001','2026-10-01') or trade_date in ('20261001','2026-10-01')").fetchall())
                except Exception as e:
                    cols = [d[0] for d in c.execute(f'select * from {t} limit 0').description]
                    print('   cols:', cols)
        c.close()
    except Exception as e:
        print(db, 'ERR', str(e)[:80])
