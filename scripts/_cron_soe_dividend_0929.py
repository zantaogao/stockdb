# 中国中车601766 + 同类"央企红利低波"票(中国建筑/国投电力/中国神华/长江电力/宝钢) 走势与评分链
import duckdb, sqlite3
db = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
CODES = ['601766.SH','601668.SH','600886.SH','601088.SH','600900.SH','600019.SH']
cl = ",".join(f"'{c}'" for c in CODES)

q1 = f"""
SELECT ts_code, substr(trade_date,1,6) ym, MIN(low) lo, MAX(high) hi,
  MIN_BY(close,trade_date) f, MAX_BY(close,trade_date) m
FROM daily WHERE ts_code IN ({cl}) AND trade_date>='20260101' GROUP BY 1,2 ORDER BY 1,2
"""
m = db.execute(q1).df()
v = db.execute(f"SELECT ts_code,pe_ttm,pb,ROUND(total_mv/10000,0) mv_yi FROM daily_basic WHERE ts_code IN ({cl}) AND trade_date=(SELECT MAX(trade_date) FROM daily_basic)").df()
q2 = f"""
WITH r AS (SELECT ts_code, trade_date, close, vol,
  MAX(close) OVER(PARTITION BY ts_code ORDER BY trade_date) rmax,
  LAG(close,20) OVER(PARTITION BY ts_code ORDER BY trade_date) c20,
  LAG(close,60) OVER(PARTITION BY ts_code ORDER BY trade_date) c60
  FROM daily WHERE ts_code IN ({cl}) AND trade_date>='20251001')
SELECT ts_code, close, ROUND((close/rmax-1)*100,1) off_high, ROUND((close/c20-1)*100,1) chg20, ROUND((close/c60-1)*100,1) chg60
FROM r WHERE trade_date=(SELECT MAX(trade_date) FROM daily)
"""
r = db.execute(q2).df()
print(v.merge(r, on='ts_code').round(2).to_string(index=False))
for c in CODES:
    mm = m[m['ts_code']==c].copy(); mm['chg%']=((mm['m']/mm['f']-1)*100).round(1)
    print(c, ' '.join(f"{x.ym}:{x._2 if False else ''}" for x in []), mm[['ym','lo','hi','chg%']].round(1).values.tolist())

sig = sqlite3.connect('/Users/zantao/.hermes/stockdb/signals.db')
for code in ['601766','601668','600886','601088','600900','600019']:
    row = sig.execute("SELECT date,fusion_score,final_score,cmmr_score,reg10,reg40 FROM signal_history WHERE stock_code=? ORDER BY date DESC LIMIT 1",(code,)).fetchone()
    f3 = sig.execute("SELECT date,fusion_3f_score,signal FROM fusion_3f_signals WHERE stock_code=? ORDER BY date DESC LIMIT 1",(code,)).fetchone()
    print(code, 'signal_history:', row, '| 3f:', f3)
