# 航发动力600893 / 云天化600096 近数月走势分析
import duckdb, math
db = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
CODES = ['600893.SH','600096.SH']
cl = ",".join(f"'{c}'" for c in CODES)

# 月度聚合
q1 = f"""
SELECT ts_code, substr(trade_date,1,6) AS ym,
  MIN(low) AS lo, MAX(high) AS hi,
  MIN_BY(close, trade_date) AS first_close, MAX_BY(close, trade_date) AS last_close,
  MAX_BY(close, trade_date) AS m_close, SUM(amount)/1e8 AS amt_yi
FROM daily WHERE ts_code IN ({cl}) AND trade_date>='20260101'
GROUP BY 1,2 ORDER BY 1,2
"""
m = db.execute(q1).df()

# 关键区间统计
q2 = f"""
WITH r AS (SELECT ts_code, trade_date, close, pct_chg,
  MAX(close) OVER(PARTITION BY ts_code ORDER BY trade_date) AS runmax,
  MIN(close) OVER(PARTITION BY ts_code ORDER BY trade_date) AS runmin
  FROM daily WHERE ts_code IN ({cl}) AND trade_date>='20250901')
SELECT ts_code, MAX_BY(close, trade_date) AS last_px,
  MAX(runmax) AS hi_1y, MIN(runmin) AS lo_1y
FROM r GROUP BY 1
"""
k = db.execute(q2).df()

# 最新估值
q3 = f"""SELECT ts_code, pe_ttm, pb, total_mv/10000 AS mv_yi FROM daily_basic
WHERE ts_code IN ({cl}) AND trade_date=(SELECT MAX(trade_date) FROM daily_basic)"""
v = db.execute(q3).df()

# 近60日: 回撤、20日动量、量能变化
q4 = f"""
WITH r AS (SELECT ts_code, trade_date, close, vol,
  LAG(close,20) OVER(PARTITION BY ts_code ORDER BY trade_date) c20,
  MAX(close) OVER(PARTITION BY ts_code ORDER BY trade_date) rmax,
  AVG(vol) OVER(PARTITION BY ts_code ORDER BY trade_date ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING) v20
  FROM daily WHERE ts_code IN ({cl}) AND trade_date>='20260401')
SELECT ts_code, trade_date, close, ROUND((close/rmax-1)*100,1) off_high, ROUND((close/c20-1)*100,1) chg20, ROUND(vol/v20,2) vol_ratio
FROM r WHERE trade_date>='20260920' ORDER BY ts_code, trade_date
"""
recent = db.execute(q4).df()

# 周线明细(近26周简易: 每周收盘)
q5 = f"""
SELECT ts_code, trade_date, close, pct_chg FROM daily
WHERE ts_code IN ({cl}) AND trade_date>='20260701' ORDER BY ts_code, trade_date
"""
tail = db.execute(q5).df()

for c in CODES:
    name = db.execute(f"SELECT name FROM stock_basic WHERE ts_code='{c}'").fetchone()[0]
    print(f"\n===== {c} {name} =====")
    print(k[k['ts_code']==c].to_string(index=False))
    print(v[v['ts_code']==c].to_string(index=False))
    mm = m[m['ts_code']==c].copy()
    mm['chg%'] = ((mm['m_close']/mm['first_close']-1)*100).round(1)
    print(mm[['ym','first_close','lo','hi','m_close','chg%','amt_yi']].round(1).to_string(index=False))
    print("--- 近7日 ---")
    print(recent[recent['ts_code']==c].to_string(index=False))
    # 7月以来高低点日期
    t = tail[tail['ts_code']==c]
    print("7/1以来最高:", t.loc[t['close'].idxmax()][['trade_date','close']].tolist(), " 最低:", t.loc[t['close'].idxmin()][['trade_date','close']].tolist())
