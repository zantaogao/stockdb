# 重放: 新fusion(0.375reg20+0.625reg40) vs 旧fusion vs reg10单独, 未来10日收益IC
import sqlite3, duckdb, numpy as np, collections
from scipy import stats
sig=sqlite3.connect('/Users/zantao/.hermes/stockdb/signals.db')
rows=sig.execute("SELECT date,stock_code,fusion_score,reg20,reg40,reg10 FROM signal_history WHERE date>='2026-06-01' AND reg20!=0").fetchall()
con=duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
cal=[r[0] for r in con.execute("SELECT DISTINCT trade_date FROM daily WHERE trade_date>='20260601' ORDER BY trade_date").fetchall()]
pos={d:i for i,d in enumerate(cal)}
by=collections.defaultdict(list)
for d,c,f,r2,r4,r1 in rows: by[d].append((c,f,r2,r4,r1))

def ts_of(c): return c+'.SH' if c.startswith(('6','68')) else (c+'.BJ' if c.startswith('9') else c+'.SZ')

io,inn,i10,nr=[],[],[],0
for d in sorted(by):
    di=pos.get(d.replace('-',''))
    if di is None or di+10>=len(cal): continue
    fd=cal[di+10]; d0=d.replace('-','')
    recs=by[d]
    ts=[ts_of(c) for c,_,_,_,_ in recs]
    px0={}; px1={}
    for i in range(0,len(ts),500):
        q=",".join("'"+t+"'" for t in ts[i:i+500])
        for t,cl in con.execute(f"SELECT ts_code,close FROM daily WHERE ts_code IN ({q}) AND trade_date='{d0}'").fetchall(): px0[t]=float(cl)
        for t,cl in con.execute(f"SELECT ts_code,close FROM daily WHERE ts_code IN ({q}) AND trade_date='{fd}'").fetchall(): px1[t]=float(cl)
    rets={t:px1[t]/px0[t]-1 for t in px1 if t in px0 and px0[t]>0}
    keep=[(f,round(0.375*r2+0.625*r4,1),r1) for c,f,r2,r4,r1 in recs if ts_of(c) in rets]
    if len(keep)<1000: continue
    ya=np.array([rets[ts_of(c)] for c,f,r2,r4,r1 in recs if ts_of(c) in rets])
    a=np.array([k[0] for k in keep]); b=np.array([k[1] for k in keep]); e=np.array([k[2] for k in keep])
    io.append(stats.spearmanr(a,ya)[0]); inn.append(stats.spearmanr(b,ya)[0]); i10.append(stats.spearmanr(e,ya)[0]); nr+=1
io=np.array(io); inn=np.array(inn)
print(f"成熟日n={nr} 旧fusion日均IC={io.mean():+.4f} 新fusion={inn.mean():+.4f} reg10单独={np.mean(i10):+.4f}")
t,p=stats.ttest_1samp(inn-io,0)
print(f"新-旧日均IC差={np.mean(inn-io):+.4f} t={t:.2f} p={p:.3f}")
top=[(d,) for d in sorted(by)]
