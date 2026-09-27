# 逐年+逐季显著性：最优(0.25,0,0.75) vs 生产(0,0.375,0.625)，20日口径NW-t
import pandas as pd, numpy as np, json
from pathlib import Path
import lightgbm as lgb, duckdb
from scipy import stats
BASE = Path('/Users/zantao/.hermes/stockdb/analysis/retrain_20260927_v8')
m = {k: lgb.Booster(model_str=(BASE/f'lgb_reg_{k}_v8.txt').read_text()) for k in ['10d','20d','40d']}
ps='20250304'
preds={}
for k in ['10d','20d','40d']:
    d=pd.read_parquet(BASE/f'samples_{k}.parquet'); nf=m[k].num_feature()
    sub=d[d.date>=ps]; preds[k]=pd.DataFrame({'date':sub.date.values,'code':sub.code.values,'p':m[k].predict(sub.iloc[:,2:2+nf].values)})
preds['10d']=preds['10d'].rename(columns={'p':'p10'}); preds['20d']=preds['20d'].rename(columns={'p':'p20'}); preds['40d']=preds['40d'].rename(columns={'p':'p40'})
df=preds['10d'].merge(preds['20d'],on=['date','code']).merge(preds['40d'],on=['date','code'])
con=duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db',read_only=True)
cal=[str(r[0]) for r in con.execute("SELECT DISTINCT trade_date FROM daily ORDER BY trade_date").fetchall()]
ci={x:i for i,x in enumerate(cal)}; end_i=ci['20260924']
evd=[x for x in sorted(df.date.unique()) if ci.get(x) is not None and ci[x]+40<=end_i]
df=df[df.date.isin(evd)]
ts_of=lambda c: c+'.SH' if c.startswith(('6','68')) else (c+'.BJ' if c.startswith('9') else c+'.SZ')
df['ts']=df.code.map(ts_of)
need=set(evd)
for n in (10,20,40): need|={cal[ci[x]+n] for x in evd}
inl=",".join(f"'{t}'" for t in df.ts.unique()); dil=",".join(f"'{x}'" for x in sorted(need))
px={(t,str(dd)):float(c) for t,dd,c in con.execute(f"SELECT ts_code,trade_date,close FROM daily WHERE ts_code IN ({inl}) AND trade_date IN ({dil})").fetchall()}
rows=[]
for dd in evd:
    sub=df[df.date==dd]
    f1,f2,f4=cal[ci[dd]+10],cal[ci[dd]+20],cal[ci[dd]+40]
    b=np.array([px.get((t,dd),np.nan) for t in sub.ts]); a1=np.array([px.get((t,f1),np.nan) for t in sub.ts])
    a2=np.array([px.get((t,f2),np.nan) for t in sub.ts]); a4=np.array([px.get((t,f4),np.nan) for t in sub.ts])
    ok=~(np.isnan(b)|np.isnan(a1)|np.isnan(a2)|np.isnan(a4))&(b>0)
    if ok.sum()<1000: continue
    p1=sub.p10.values[ok]; p2=sub.p20.values[ok]; p4=sub.p40.values[ok]
    r2=a2[ok]/b[ok]-1
    fb=stats.spearmanr(0.25*p1+0.75*p4,r2)[0]
    fp=stats.spearmanr(0.375*p2+0.625*p4,r2)[0]
    rows.append((dd,fb,fp,fb-fp))
ic=pd.DataFrame(rows,columns=['date','ic_best','ic_prod','diff'])
def nw_t(x,lags=5):
    x=np.asarray(x,float);n=len(x);mu=x.mean();e=x-mu
    s=(e*e).sum()/n
    for l in range(1,lags+1):
        w=1-l/(lags+1); s+=2*w*(e[l:]*e[:-l]).sum()/n
    return mu/np.sqrt(s/n)
out=[]
ic['year']=ic.date.str[:4]
ic['q']=ic.date.str[:4]+'Q'+(((ic.date.str[4:6].astype(int)-1)//3+1).astype(str))
for col,name in [('year','年'),('q','季')]:
    g=ic.groupby(col).agg(n=('date','count'),ic_b=('ic_best','mean'),ic_p=('ic_prod','mean'))
    ts=[];ps_=[]
    for k,sub in ic.groupby(col):
        t=nw_t(sub['diff'].values); ts.append(round(t,2))
        from scipy.stats import t as td
        ps_.append(round(2*(1-td.cdf(abs(t),len(sub)-1)),4))
    g['nw_t']=ts; g['p_approx']=ps_
    print(f'== 按{name} ==\n'+g.round(4).to_string(), flush=True)
