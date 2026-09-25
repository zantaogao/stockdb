import duckdb
con = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
codes = ['001237.SZ','301531.SZ','301655.SZ','301666.SZ','301699.SZ','603448.SH','688826.SH',
         '001365.SZ','301689.SZ','603407.SH','688801.SH','301599.SZ','688797.SH','601123.SH',
         '603293.SH','603435.SH','688811.SH','688820.SH','301696.SZ','603468.SH']
try:
    df = con.execute("""
        SELECT ts_code, list_date FROM stock_basic
        WHERE ts_code IN (%s) ORDER BY list_date DESC
    """ % ",".join(["'"+c+"'" for c in codes])).df()
    print(df.to_string())
except Exception as e:
    print("ERR1:", e)
    tabs = con.execute("SHOW TABLES").df()
    print(tabs.to_string())
