# One-off cron verification: today's market vs skipped-trap stocks performance
import duckdb, sqlite3

con = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)

# Index moves today
idx = con.execute("""
  SELECT ts_code, trade_date, pct_chg FROM daily
  WHERE ts_code IN ('000001.SH','399006.SZ','932000.CSI') AND trade_date >= '20260916'
  ORDER BY ts_code, trade_date
""").fetchall()
print("index:", idx)

# Skipped stocks actual move today (0918)
skipped = ['300970','603721','600250','688057','300093','600706','300950','300097','601700',
           '601118','300163','600121','688051','600493','605122','002661','301010','002535',
           '603909','603029','603900','603321','002248','001222','600807','000692','603023',
           '600303','600386','301011','603238','300994','300703','600847','002660','002679',
           '600758','002397','301314','600192','605089','600719','600793','300904','002470',
           '600108','000798','688548','003013','603669','300575','002578','301056','601279',
           '002040','000735','603183','600403','300032','002321','300050','300129','601975']
inlist = ",".join(f"'{s}'" for s in skipped)
rows = con.execute(f"""
  SELECT ts_code, pct_chg FROM daily
  WHERE ts_code IN ({inlist}) AND trade_date = '20260918'
""").fetchall()
import statistics
if rows:
    chgs = [r[1] for r in rows if r[1] is not None]
    print(f"skipped stocks today: n={len(chgs)} median={statistics.median(chgs):.2f}% mean={statistics.mean(chgs):.2f}%")
else:
    print("no 0918 daily rows yet for skipped stocks")

# Does 0918 daily data exist at all in tushare?
mx = con.execute("SELECT MAX(trade_date) FROM daily").fetchone()[0]
print("tushare daily max date:", mx)
con.close()
