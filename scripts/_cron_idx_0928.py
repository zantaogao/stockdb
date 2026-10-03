import duckdb
con = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
rows = con.execute("SELECT table_name FROM information_schema.tables WHERE table_name LIKE '%index%'").fetchall()
print('tables:', rows)
for t in rows:
    try:
        n = con.execute(f"SELECT COUNT(*), MAX(trade_date) FROM {t[0]}").fetchone()
        print(t[0], n)
    except Exception as e:
        try:
            print(t[0], con.execute(f"SELECT COUNT(*) FROM {t[0]}").fetchone())
        except Exception as e2:
            print(t[0], 'ERR', str(e2)[:80])
# any 000852 data in daily-like tables?
try:
    print('000852 any:', con.execute("SELECT trade_date,pct_chg FROM index_daily WHERE ts_code='000852.SH' ORDER BY trade_date DESC LIMIT 3").fetchall())
except Exception as e:
    print('index_daily ERR', str(e)[:100])
