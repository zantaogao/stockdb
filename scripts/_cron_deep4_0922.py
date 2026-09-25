#!/usr/bin/env python3
import duckdb, sqlite3, os, json
from collections import defaultdict
os.chdir(os.path.expanduser('~/.hermes/stockdb'))
tdb = duckdb.connect('tushare.db', read_only=True)
sig = sqlite3.connect('file:signals.db?mode=ro', uri=True)
def sec(t): print('\n===== '+t+' =====')

sec('板块近10日 日均涨幅（stock_basic.industry 口径，与前5日对比）')
days = [r[0] for r in tdb.execute("SELECT DISTINCT trade_date FROM daily WHERE trade_date>='20260908' ORDER BY 1").fetchall()]
print('days:', days)
indaily = defaultdict(dict)
for d, in tdb.execute("SELECT DISTINCT trade_date FROM daily WHERE trade_date IN (%s)" % ",".join("'%s'"%x for x in days)).fetchall():
    for ind, p in tdb.execute("""SELECT b.industry, AVG(d.pct_chg) FROM daily d JOIN stock_basic b ON d.ts_code=b.ts_code
        WHERE d.trade_date=? AND b.industry IS NOT NULL AND b.industry!='' GROUP BY 1 HAVING COUNT(*)>=5""", [d]).fetchall():
        indaily[ind][d] = p
stats=[]
for ind,m in indaily.items():
    seq=[round(m.get(d,0),2) for d in days]
    cum5=sum(m.get(d,0) for d in days[-5:])
    streak=0
    for d in reversed(days):
        if m.get(d,0)>0: streak+=1
        else: break
    stats.append((round(cum5,2), streak, ind, seq))
stats.sort(reverse=True)
print('--- 近5日累计强 前12 ---')
for s in stats[:12]: print(s)
print('--- 弱 后6 ---')
for s in stats[-6:]: print(s)

sec('分模型IC序列 近15信号日')
for t in ['ic_daily','fusion_ic_daily','center_dual_ic_daily']:
    cols=[c[1] for c in sig.execute(f"PRAGMA table_info({t})").fetchall()]
    print('--',t,cols)
    try:
        key = 'signal_date' if 'signal_date' in cols else cols[0]
        for r in sig.execute(f"SELECT * FROM {t} ORDER BY {key} DESC LIMIT 15").fetchall(): print(str(r)[:220])
    except Exception as e: print(t,'err',e)

sec('ic_window 表')
cols=[c[1] for c in sig.execute("PRAGMA table_info(ic_window)").fetchall()]
print(cols)
for r in sig.execute("SELECT * FROM ic_window ORDER BY rowid DESC LIMIT 20").fetchall(): print(str(r)[:220])

sec('factor_ic_roll 最新10')
cols=[c[1] for c in sig.execute("PRAGMA table_info(factor_ic_roll)").fetchall()]
print(cols)
for r in sig.execute("SELECT * FROM factor_ic_roll ORDER BY rowid DESC LIMIT 10").fetchall(): print(str(r)[:220])

sec('cmmr_top10_ic_daily 近8')
try:
    cols=[c[1] for c in sig.execute("PRAGMA table_info(cmmr_top10_ic_daily)").fetchall()]
    print(cols)
    for r in sig.execute("SELECT * FROM cmmr_top10_ic_daily ORDER BY rowid DESC LIMIT 8").fetchall(): print(str(r)[:220])
except Exception as e: print(e)
