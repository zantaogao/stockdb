#!/usr/bin/env python3
# 盘后深复盘只读取数 20260917 v2（tushare.db=DuckDB: daily/stock_basic/index_daily_raw；signals/ledger=SQLite）
import duckdb, sqlite3, json, os, statistics, collections
os.chdir(os.path.expanduser('~/.hermes/stockdb'))
TU = duckdb.connect('tushare.db', read_only=True)
SG = sqlite3.connect('file:signals.db?mode=ro', uri=True)
LG = sqlite3.connect('file:ledger.db?mode=ro', uri=True)

def sec(t): print('\n=====', t, '=====', flush=True)

# 2 行业板块（daily join stock_basic.industry）近10日
sec('SECTOR 5d cum strength')
q = """
WITH d AS (
  SELECT b.industry ind, d.trade_date td, AVG(d.pct_chg) chg
  FROM daily d JOIN stock_basic b ON d.ts_code=b.ts_code
  WHERE d.trade_date >= '20260901' AND b.industry IS NOT NULL AND b.industry!=''
  GROUP BY 1,2),
r AS (SELECT ind, td, chg, ROW_NUMBER() OVER (PARTITION BY ind ORDER BY td DESC) rn FROM d)
SELECT ind, ROUND(SUM(CASE WHEN rn<=5 THEN chg END),2) cum5,
  ROUND(SUM(CASE WHEN rn<=10 THEN chg END),2) cum10,
  ROUND(MAX(CASE WHEN rn=1 THEN chg END),2) d1,
  ROUND(MAX(CASE WHEN rn=2 THEN chg END),2) d2,
  ROUND(MAX(CASE WHEN rn=3 THEN chg END),2) d3,
  ROUND(MAX(CASE WHEN rn=4 THEN chg END),2) d4,
  ROUND(MAX(CASE WHEN rn=5 THEN chg END),2) d5
FROM r GROUP BY ind ORDER BY cum5 DESC LIMIT 15"""
for r in TU.execute(q).fetchall(): print(r)
print('--- weakest 8 ---')
for r in TU.execute(q.replace('DESC LIMIT 15','ASC LIMIT 8')).fetchall(): print(r)

# 4 个股形态
sec('STOCK SHAPES')
codes = ['301237.SZ','688093.SH','301283.SZ','002454.SZ','688191.SH','600076.SH','603966.SH','601615.SH',
 '688186.SH','301093.SZ','300658.SZ','603202.SH','001332.SZ','301590.SZ','301110.SZ','605598.SH',
 '301133.SZ','688175.SH','301011.SZ','300970.SZ','605056.SH','301503.SZ']
for c in codes:
    rows = TU.execute("SELECT trade_date,open,high,low,close,pct_chg,vol FROM daily WHERE ts_code=? ORDER BY trade_date DESC LIMIT 25",[c]).fetchall()
    if not rows: print(c,'NOROW'); continue
    rows = list(reversed(rows))
    closes=[r[4] for r in rows]; highs=[r[2] for r in rows]; lows=[r[3] for r in rows]
    last=rows[-1]
    hi20=max(highs[:-1]); lo20=min(lows[:-1])
    vols=[r[6] for r in rows]; v5avg=sum(vols[-6:-1])/5 if len(vols)>=6 else vols[-1]
    st=0; d=None
    for r in reversed(rows):
        s=1 if r[5]>0.05 else (-1 if r[5]<-0.05 else 0)
        if d is None: d=s; st=s
        elif s==d and s!=0: st+=s
        else: break
    prev_high = rows[-2][2]
    gap = 'GAPUP' if last[1] > prev_high else ('GAPDN' if last[1+1] < rows[-2][3] else '')
    print(c, 'd1=%+.1f%%'%last[5],
          '距25日高 %+.1f%%'%((last[4]/hi20-1)*100),
          '距25日低 %+.1f%%'%((last[4]/lo20-1)*100),
          'streak=%+d'%st, 'vol/v5=%.2f'%(last[6]/v5avg if v5avg else 0),
          '5d=%+.1f%%'%((closes[-1]/closes[-6]-1)*100 if len(closes)>=6 else 0), gap)

# 5 ic_daily
sec('ic_daily last 12')
cols=[c[1] for c in SG.execute("PRAGMA table_info(ic_daily)").fetchall()]
print('cols:',cols)
for r in SG.execute("SELECT * FROM ic_daily ORDER BY signal_date DESC LIMIT 12").fetchall(): print(r)

# 6 top10 次日超额原始复算
sec('TOP10 NEXTDAY recheck')
sdays=[r[0] for r in SG.execute("SELECT DISTINCT REPLACE(date,'-','') d FROM signal_history WHERE REPLACE(date,'-','') BETWEEN '20260908' AND '20260917' ORDER BY d").fetchall()]
print('signal days:',sdays)
idx={r[0]:r[1] for r in TU.execute("SELECT trade_date,pct_chg FROM index_daily_raw WHERE ts_code='000852.SH' AND trade_date>='20260901' ORDER BY trade_date").fetchall()}
alldates=[r[0] for r in TU.execute("SELECT DISTINCT trade_date FROM daily WHERE trade_date>='20260901' ORDER BY 1").fetchall()]
for d in sdays:
    top=SG.execute("SELECT stock_code,fusion_score FROM signal_history WHERE REPLACE(date,'-','')=? ORDER BY fusion_score DESC LIMIT 10",[d]).fetchall()
    if d==sdays[-1]:
        print(d,'(today) top10:',[(t[0],round(t[1],2)) for t in top]); continue
    nd=alldates[alldates.index(d)+1]
    rets=[]
    for code,_ in top:
        c=code.replace('.SZ','').replace('.SH','').replace('.BJ','')
        q=TU.execute("SELECT pct_chg FROM daily WHERE ts_code LIKE ? AND trade_date=?",[c+'.%',nd]).fetchall()
        if q: rets.append(q[0][0])
    if rets:
        print(d,'->',nd,'top10均%+.2f%% vs1000 %+.2f%% ex=%+.2f%% n=%d'%(statistics.mean(rets),idx.get(nd,0),statistics.mean(rets)-idx.get(nd,0),len(rets)))

# 7 meta
sec('REBAL meta')
for r in LG.execute("SELECT account_id,last_rebalance_date FROM strategy_accounts_meta").fetchall(): print(r)

# 8 holdings/watchlist
sec('HOLDINGS cols+rows')
print([c[1] for c in LG.execute("PRAGMA table_info(holdings)").fetchall()])
for r in LG.execute("SELECT * FROM holdings").fetchall(): print(r)
sec('WATCHLIST')
print([c[1] for c in LG.execute("PRAGMA table_info(watchlist)").fetchall()])
for r in LG.execute("SELECT * FROM watchlist").fetchall(): print(r)

# 9 中枢系 IC
sec('fusion_ic_daily')
try:
    cols=[c[1] for c in SG.execute("PRAGMA table_info(fusion_ic_daily)").fetchall()]
    print('cols:',cols)
    for r in SG.execute("SELECT * FROM fusion_ic_daily ORDER BY 1 DESC LIMIT 12").fetchall(): print(r)
except Exception as e: print(e)
sec('center_dual_ic_daily')
try:
    cols=[c[1] for c in SG.execute("PRAGMA table_info(center_dual_ic_daily)").fetchall()]
    print('cols:',cols)
    for r in SG.execute("SELECT * FROM center_dual_ic_daily ORDER BY 1 DESC LIMIT 12").fetchall(): print(r)
except Exception as e: print(e)
sec('ic_window')
try:
    cols=[c[1] for c in SG.execute("PRAGMA table_info(ic_window)").fetchall()]
    print('cols:',cols)
    for r in SG.execute("SELECT * FROM ic_window ORDER BY 1 DESC LIMIT 15").fetchall(): print(r)
except Exception as e: print(e)

# 10 defense
sec('DEFENSE STATE')
try:
    for r in LG.execute("SELECT * FROM defense_state").fetchall(): print(r)
except Exception as e: print(e)

# 11 strategy_accounts 各户净值序列尾
sec('strategy_accounts tail')
for r in LG.execute("SELECT account_id, MAX(date) FROM strategy_accounts GROUP BY 1").fetchall(): print(r)
print('\nDONE')
