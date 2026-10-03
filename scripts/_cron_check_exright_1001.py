import duckdb, glob, os

candidates = glob.glob(os.path.expanduser('~/.hermes/stockdb/data/*.db')) + glob.glob(os.path.expanduser('~/.hermes/stockdb/data/*.duckdb'))
for db in candidates:
    try:
        con = duckdb.connect(db, read_only=True)
    except Exception as e:
        print(db, 'open ERR', e)
        continue
    try:
        tabs = [r[0] for r in con.sql("select table_name from information_schema.tables").fetchall()]
        if 'ca_run_log' in tabs:
            print('=== ca_run_log in', db)
            cols = [r[1] for r in con.sql("pragma table_info('ca_run_log')").fetchall()]
            print('cols:', cols)
            print(con.sql('select * from ca_run_log order by 1 desc limit 10').df().to_string())
        if 'trade_cal' in tabs:
            print('=== trade_cal in', db)
            print(con.sql("select cal_date,is_open from trade_cal where cal_date>='20260928' and cal_date<='20261010' order by cal_date").df().to_string())
    except Exception as e:
        print(db, 'ERR', e)
    con.close()
