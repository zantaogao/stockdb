import duckdb
con = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
try:
    df = con.execute("select trade_date,close,pct_chg,vol from index_daily where ts_code='000852.SH' order by trade_date desc limit 8").df()
    print(df.to_string())
except Exception as e:
    print('err', e)
    tabs = [x[0] for x in con.execute("select table_name from information_schema.tables").fetchall()]
    print(tabs[:40])
