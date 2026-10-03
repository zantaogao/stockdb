import duckdb
c = duckdb.connect('/Users/zantao/.hermes/stockdb/ledger.db', read_only=True)
print("2026-10-01:", c.execute("select cal_date,is_open from trade_cal where cal_date in ('20261001','2026-10-01')").fetchall())
tabs = [t[0] for t in c.execute('show tables').fetchall()]
print("tables:", tabs)
for t in tabs:
    if t == 'trade_cal':
        continue
    try:
        cols = [d[0] for d in c.execute(f'select * from "{t}" limit 0').description]
        dcol = next((x for x in ('trade_date','date','exec_date','created_at','dt','day') if x in cols), None)
        n = c.execute(f'select count(*) from "{t}"').fetchone()[0]
        mx = c.execute(f'select max("{dcol}") from "{t}"').fetchone()[0] if dcol else None
        print(f"{t}: rows={n} max_{dcol}={mx}")
        if dcol:
            todays = c.execute(f'select count(*) from "{t}" where "{dcol}" in (\'20261001\',\'2026-10-01\')').fetchone()[0]
            if todays:
                print(f"  !! {t} has {todays} rows dated 2026-10-01")
    except Exception as e:
        print(t, 'err', str(e)[:60])
