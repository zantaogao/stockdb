import duckdb, glob, os
# find the backtest table (fusion strong-buy equal weight)
for db in ['/Users/zantao/.hermes/stockdb/signals.db','/Users/zantao/.hermes/stockdb/factors.db','/Users/zantao/.hermes/stockdb/ledger.db','/Users/zantao/.hermes/stockdb/aquant.db']:
    try:
        c = duckdb.connect(db, read_only=True)
        tabs = [t[0] for t in c.execute("show tables").fetchall()]
        cand = [t for t in tabs if 'backtest' in t.lower() or 'fusion' in t.lower() or 'shadow' in t.lower()]
        print(db, '->', cand)
        for t in cand:
            try:
                cols = [d[0] for d in c.execute(f'describe {t}').fetchall()]
                dcol = [x for x in cols if 'date' in x.lower()]
                if dcol:
                    mx = c.execute(f'select max({dcol[0]}), count(*) from {t}').fetchall()
                    print('  ', t, 'max_date/cnt:', mx)
            except Exception as e:
                print('  ', t, 'err', e)
        c.close()
    except Exception as e:
        print(db, 'open err:', e)
# signal days present for 0929/0930
try:
    c = duckdb.connect('/Users/zantao/.hermes/stockdb/signals.db', read_only=True)
    tabs = [t[0] for t in c.execute("show tables").fetchall()]
    print('signals.db tables:', tabs)
    c.close()
except Exception as e:
    print('signals err', e)
