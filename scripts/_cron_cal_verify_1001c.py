import duckdb
con = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.duckdb', read_only=True)
try:
    print(con.execute("select cal_date, is_open from trade_cal where cal_date between '20260928' and '20261010' order by cal_date").fetchall())
    print('max:', con.execute('select max(cal_date) from trade_cal').fetchone())
except Exception as e:
    print('ERR', e)
    print([r[0] for r in con.execute("select table_name from information_schema.tables").fetchall() if 'cal' in r[0].lower()])
