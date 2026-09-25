import duckdb, os, glob
base = os.path.expanduser("~/.hermes/stockdb")
d = duckdb.connect(os.path.join(base, "tushare.db"), read_only=True)
print("000852 last3:", d.execute("SELECT date, close, change_pct FROM index_daily WHERE index_code='000852' ORDER BY date DESC LIMIT 3").fetchall())
print("000001 last3:", d.execute("SELECT date, close, change_pct FROM index_daily WHERE index_code='000001' ORDER BY date DESC LIMIT 3").fetchall())
try:
    print("raw recent:", d.execute("SELECT trade_date, ts_code, close, change FROM index_daily_raw ORDER BY trade_date DESC LIMIT 5").fetchall())
except Exception as e:
    print("raw err", e)
# 找实时行情缓存
for pat in ("data/*.json", "*.json", "cache/*.json", "runtime/*.json", "tmp/*.json"):
    for f in glob.glob(os.path.join(base, pat))[:20]:
        print("json:", f)
