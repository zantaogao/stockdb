import duckdb, sqlite3, os, json, subprocess
H = os.path.expanduser('~/.hermes/stockdb')

print('===== 1. 指数近8日 =====')
t = duckdb.connect(f'{H}/tushare.db', read_only=True)
for ts in ['000852.SH','000001.SH','000016.SH','399006.SZ']:
    rows = t.execute(f"SELECT trade_date, close, pct_chg, vol FROM index_daily_raw WHERE ts_code='{ts}' ORDER BY trade_date DESC LIMIT 8").fetchall()
    print(ts)
    for r in reversed(rows): print('  ', r)

print('===== 2. 行业板块近10日涨幅(前30强5日累计) =====')
rows = t.execute("""
WITH d AS (
  SELECT trade_date, industry_name, AVG(pct_chg) avg_pct, COUNT(*) n
  FROM sw_daily_raw s JOIN stock_industry_raw i ON s.ts_code=i.ts_code
  GROUP BY 1,2
), p AS (
  SELECT industry_name, trade_date, avg_pct,
         LAG(avg_pct,1) OVER (PARTITION BY industry_name ORDER BY trade_date) prev1,
         LAG(avg_pct,2) OVER (PARTITION BY industry_name ORDER BY trade_date) prev2,
         LAG(avg_pct,3) OVER (PARTITION BY industry_name ORDER BY trade_date) prev3,
         LAG(avg_pct,4) OVER (PARTITION BY industry_name ORDER BY trade_date) prev4
  FROM d
)
SELECT industry_name,
  ROUND(avg_pct,2) d0, ROUND(prev1,2) d1, ROUND(prev2,2) d2, ROUND(prev3,2) d3, ROUND(prev4,2) d4,
  ROUND(avg_pct+COALESCE(prev1,0)+COALESCE(prev2,0)+COALESCE(prev3,0)+COALESCE(prev4,0),2) cum5
FROM p WHERE trade_date=(SELECT MAX(trade_date) FROM p)
ORDER BY cum5 DESC LIMIT 30
""").fetchall()
print('板块 | 今 | -1 | -2 | -3 | -4 | 5日累计')
for r in rows: print('  ', r)

print('===== 3. 主账户持仓+watchlist 止损距离 =====')
c = sqlite3.connect(f'{H}/ledger.db')
cols = [x[1] for x in c.execute("PRAGMA table_info(holdings)")]
print('holdings cols:', cols)
for r in c.execute("SELECT * FROM holdings").fetchall(): print('  ', r)
try:
    wc = [x[1] for x in c.execute("PRAGMA table_info(watchlist)")]
    print('watchlist cols:', wc)
    for r in c.execute("SELECT * FROM watchlist ORDER BY 1 DESC LIMIT 30").fetchall(): print('  W', r)
except Exception as e: print('watchlist err', e)

print('===== 4. 策略账户 meta =====')
for r in c.execute("SELECT account_id, last_rebalance_date FROM strategy_accounts_meta").fetchall():
    print('  ', r)
# 重评日之后的实交易日数
mets = c.execute("SELECT account_id, last_rebalance_date FROM strategy_accounts_meta").fetchall()
import re
for acc, lrd in mets:
    if not lrd: print(acc, 'no lrd'); continue
    d = re.sub('-','',str(lrd))
    n = t.execute(f"SELECT COUNT(*) FROM daily WHERE trade_date > '{d}' AND trade_date <= '20260918'").fetchone()[0]
    print(f'  {acc}: last_rebal={lrd} 已过{n}个交易日')

print('===== 5. 分模型IC近12信号日 =====')
s = sqlite3.connect(f'{H}/signals.db')
tabs = [r[0] for r in s.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
for tb in ['ic_daily','fusion_ic_daily','center_dual_ic_daily','ic_window']:
    if tb not in tabs: print(tb,'missing'); continue
    cols = [x[1] for x in s.execute(f"PRAGMA table_info({tb})")]
    print(f'--- {tb} cols: {cols}')
    for r in s.execute(f"SELECT * FROM {tb} ORDER BY 1 DESC LIMIT 12").fetchall(): print('  ', r)
