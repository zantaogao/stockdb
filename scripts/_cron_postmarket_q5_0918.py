import duckdb, sqlite3, os, re
H = os.path.expanduser('~/.hermes/stockdb')
t = duckdb.connect(f'{H}/tushare.db', read_only=True)

print('===== A. 板块近5日每日涨跌幅(stock_basic行业口径, 按5日累计排序前25) =====')
rows = t.execute("""
WITH d AS (
  SELECT d.trade_date, b.industry ind, AVG(d.pct_chg) ap
  FROM daily d JOIN stock_basic b ON d.ts_code=b.ts_code
  WHERE d.trade_date <= '20260918' AND b.industry IS NOT NULL AND b.industry != ''
    AND d.trade_date >= '20260904'
  GROUP BY 1,2
), p AS (
  SELECT ind, trade_date, ap,
    LAG(ap,1) OVER (PARTITION BY ind ORDER BY trade_date) p1,
    LAG(ap,2) OVER (PARTITION BY ind ORDER BY trade_date) p2,
    LAG(ap,3) OVER (PARTITION BY ind ORDER BY trade_date) p3,
    LAG(ap,4) OVER (PARTITION BY ind ORDER BY trade_date) p4
  FROM d
)
SELECT ind, ROUND(ap,2), ROUND(p1,2), ROUND(p2,2), ROUND(p3,2), ROUND(p4,2),
  ROUND(ap+COALESCE(p1,0)+COALESCE(p2,0)+COALESCE(p3,0)+COALESCE(p4,0),2) cum5
FROM p WHERE trade_date='20260918' ORDER BY cum5 DESC LIMIT 25
""").fetchall()
print('行业 | 今 | -1 | -2 | -3 | -4 | cum5')
for r in rows: print('  ', r)

print('===== B. 重评日距今日数 =====')
c = sqlite3.connect(f'{H}/ledger.db')
mets = c.execute("SELECT account_id, last_rebalance_date FROM strategy_accounts_meta").fetchall()
print(mets)
for acc, lrd in mets:
    if not lrd: print(acc,'no lrd'); continue
    d = re.sub('-','',str(lrd))
    n = t.execute(f"SELECT COUNT(*) FROM daily WHERE trade_date > '{d}' AND trade_date <= '20260918'").fetchone()[0]
    print(f'  {acc}: last_rebal={lrd} 已过{n}个交易日')

print('===== C. signals.db IC表 =====')
s = sqlite3.connect(f'{H}/signals.db')
tabs = [r[0] for r in s.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
print([x for x in tabs if 'ic' in x.lower()])
for tb in ['ic_daily','fusion_ic_daily','center_dual_ic_daily','ic_window']:
    if tb not in tabs: print(tb,'missing'); continue
    cols = [x[1] for x in s.execute(f"PRAGMA table_info({tb})")]
    print(f'--- {tb}: {cols}')
    try:
        for r in s.execute(f"SELECT * FROM {tb} ORDER BY 1 DESC LIMIT 12").fetchall(): print('  ', r)
    except Exception as e: print('  err', e)
