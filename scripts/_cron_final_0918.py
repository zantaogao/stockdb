import duckdb, sqlite3, os
H = os.path.expanduser('~/.hermes/stockdb')
t = duckdb.connect(f'{H}/tushare.db', read_only=True)
print('== 指数近30日高/低 ==')
for ts in ['000852.SH','000001.SH']:
    r = t.execute(f"SELECT MAX(high), MIN(low), MAX(trade_date) FROM (SELECT * FROM index_daily_raw WHERE ts_code='{ts}' ORDER BY trade_date DESC LIMIT 30)").fetchone()
    print(ts, '30日高', r[0], '30日低', r[1])
print('== 今日板块单日涨幅前12 ==')
rows = t.execute("""SELECT b.industry, ROUND(AVG(d.pct_chg),2) ap FROM daily d JOIN stock_basic b ON d.ts_code=b.ts_code
WHERE d.trade_date='20260918' AND b.industry IS NOT NULL AND b.industry!='' GROUP BY 1 ORDER BY 2 DESC LIMIT 12""").fetchall()
print(rows)
print('== 今日单日倒数前8 ==')
print(t.execute("""SELECT b.industry, ROUND(AVG(d.pct_chg),2) ap FROM daily d JOIN stock_basic b ON d.ts_code=b.ts_code
WHERE d.trade_date='20260918' AND b.industry IS NOT NULL AND b.industry!='' GROUP BY 1 ORDER BY 2 ASC LIMIT 8""").fetchall())
print('== 黄金/铜/能源金属/煤炭 近3日 ==')
for ind in ['黄金','铜','能源金属','煤炭开采','钢铁']:
    r = t.execute(f"""SELECT LIST(trade_date[5:7*0+6:], 3), LIST(ROUND(ap,2),3) FROM (
      SELECT d.trade_date, AVG(d.pct_chg) ap FROM daily d JOIN stock_basic b ON d.ts_code=b.ts_code
      WHERE b.industry='{ind}' AND d.trade_date<='20260918' GROUP BY 1 ORDER BY 1 DESC LIMIT 3)""").fetchone()
    print(ind, r)
s = sqlite3.connect(f'{H}/signals.db')
print('== ic_daily signal_history 复算 0918 top10 名单存在性 ==')
print(s.execute("SELECT COUNT(*), MAX(date) FROM signal_history").fetchall())
print(s.execute("SELECT date, COUNT(*) FROM signal_history WHERE REPLACE(date,'-','')>='20260914' GROUP BY 1 ORDER BY 1").fetchall())
