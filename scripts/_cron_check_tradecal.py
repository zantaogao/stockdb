# Check tushare trade_cal authority for 2026-10-02 (should be closed: National Day holiday)
import glob, duckdb

candidates = sorted(glob.glob('/Users/zantao/.hermes/stockdb/tushare*')) + [
    '/Users/zantao/.hermes/stockdb/db_backups/tushare/20261001/tushare.db',
]
for path in candidates:
    try:
        con = duckdb.connect(path, read_only=True)
    except Exception as e:
        print(path, 'SKIP', type(e).__name__)
        continue
    try:
        t = [r[0] for r in con.execute(
            "select table_name from information_schema.tables where table_name like '%trade_cal%'"
        ).fetchall()]
        if t:
            rows = con.execute(
                "select cal_date, is_open from trade_cal "
                "where cal_date between '2026-09-29' and '2026-10-09' order by cal_date"
            ).fetchall()
            print(path, t, rows)
        else:
            print(path, 'no trade_cal table')
    except Exception as e:
        print(path, 'ERR', e)
    con.close()
