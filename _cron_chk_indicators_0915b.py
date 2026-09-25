import duckdb, os
os.chdir(os.path.expanduser('~/.hermes/stockdb'))
i = duckdb.connect('indicators.db', read_only=True)
print("indicator_bfq today:", i.execute("SELECT COUNT(*), COUNT(DISTINCT ts_code) FROM indicator_bfq WHERE trade_date='20260915'").fetchone())
print("nulls today:", i.execute("""SELECT
 SUM(CASE WHEN ma_bfq_5 IS NULL THEN 1 ELSE 0 END) ma5,
 SUM(CASE WHEN macd_bfq IS NULL THEN 1 ELSE 0 END) macd,
 SUM(CASE WHEN rsi_bfq_12 IS NULL THEN 1 ELSE 0 END) rsi12,
 SUM(CASE WHEN boll_mid_bfq IS NULL THEN 1 ELSE 0 END) boll,
 SUM(CASE WHEN ma_bfq_60 IS NULL THEN 1 ELSE 0 END) ma60
 FROM indicator_bfq WHERE trade_date='20260915'""").fetchone())
t = duckdb.connect('tushare.db', read_only=True)
print("tushare daily max:", t.execute("SELECT MAX(trade_date), COUNT(*) FROM daily WHERE trade_date=(SELECT MAX(trade_date) FROM daily)").fetchone())
print("daily 20260915 rows:", t.execute("SELECT COUNT(*) FROM daily WHERE trade_date='20260915'").fetchone())
try:
    print("stk_factor 20260915:", t.execute("SELECT COUNT(*) FROM stk_factor WHERE trade_date='20260915'").fetchone())
except Exception as e:
    print("stk_factor err", e)
