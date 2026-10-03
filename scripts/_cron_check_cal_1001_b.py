import duckdb, os
db = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
print(db.sql("select cal_date,is_open from trade_cal where cal_date between '2026-09-28' and '2026-10-09' order by cal_date").all())
led = '/Users/zantao/.hermes/stockdb/ledger.db'
if os.path.exists(led):
    L = duckdb.connect(led, read_only=True)
    tabs = [t[0] for t in L.sql("select table_name from information_schema.tables").all()]
    print('ledger tables:', tabs)
    for t in tabs:
        try:
            cols = [c[0] for c in L.sql(f'describe {t}').all()]
            dc = None
            for cand in ('date','trade_date','created_at','submit_date'):
                if cand in cols:
                    dc = cand; break
            if dc:
                rows = L.sql(f"select * from {t} where cast({dc} as varchar) like '2026-10-01%' order by {dc} desc limit 5").all()
                if rows:
                    print(t, cols)
                    for r in rows: print('  ', r)
        except Exception:
            pass
