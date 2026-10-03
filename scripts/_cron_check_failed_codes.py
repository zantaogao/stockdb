import duckdb
codes = ["001232","301697","688835","688836","301583","601091","301686","601123","603293","603435","688811","688820","001399","301599","688797","688837","001246","001365","301689","603407","688801","301669","688635","001248","001393","301688","301513","301717","688806","688825","001312","301677","688828","001237","301531","301655","301666","301699","603448","688826","301707","301716","688808","301696","603468"]
db = "/Users/zantao/.hermes/stockdb/tushare.db"
con = duckdb.connect(db, read_only=True)
codes6 = ",".join("'"+c+"'" for c in codes)
rows = con.execute(f"""
  SELECT ts_code, name, list_date, delist_date
  FROM stock_basic
  WHERE substr(ts_code,1,6) IN ({codes6})
  ORDER BY list_date DESC NULLS LAST
""").fetchall()
print("found in stock_basic:", len(rows))
for r in rows[:50]:
    print(r)
have = con.execute(f"""
  SELECT substr(ts_code,1,6), COUNT(*), MAX(trade_date)
  FROM daily
  WHERE substr(ts_code,1,6) IN ({codes6}) AND trade_date >= '20260701'
  GROUP BY 1
""").fetchall()
print("codes with daily rows since 20260701:", len(have))
nodata = set(codes) - {h[0] for h in have}
print("codes with NO daily data since 0701:", len(nodata), sorted(nodata))
