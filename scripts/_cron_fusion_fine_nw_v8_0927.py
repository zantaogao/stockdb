# 复查: 权重敏感性——细网格(0.01) + NW-t(HAC) + 分年IC
import numpy as np, pandas as pd, json, time
from pathlib import Path
import lightgbm as lgb
from scipy import stats
from scipy.stats import t as tdist

BASE = Path('/Users/zantao/.hermes/stockdb/analysis/retrain_20260927_v8')
OUT = BASE/'fusion_grid'

# 重建 day_data（与 grid 脚本同口径）
m = {k: lgb.Booster(model_str=(BASE/f'lgb_reg_{k}_v8.txt').read_text()) for k in ['10d','20d','40d']}
d = {k: pd.read_parquet(BASE/f'samples_{k}.parquet') for k in ['10d','20d','40d']}
ps = '20250304'
pred = {}
for k in ['10d','20d','40d']:
    nf = m[k].num_feature()
    sub = d[k][d[k].date>=ps]
    pred[k] = pd.DataFrame({'date':sub.date.values,'code':sub.code.values,'p':m[k].predict(sub.iloc[:,2:2+nf].values)})
p10 = pred['10d'].rename(columns={'p':'p10'}); p20 = pred['20d'].rename(columns={'p':'p20'}); p40 = pred['40d'].rename(columns={'p':'p40'})
df = p10.merge(p20, on=['date','code']).merge(p40, on=['date','code'])
import duckdb
con = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
cal = [str(r[0]) for r in con.execute("SELECT DISTINCT trade_date FROM daily ORDER BY trade_date").fetchall()]
ci = {x:i for i,x in enumerate(cal)}
end_i = ci['20260924']
evd = [x for x in sorted(df.date.unique()) if ci.get(x) is not None and ci[x]+40<=end_i]
df = df[df.date.isin(evd)]
ts_of = lambda c: c+'.SH' if c.startswith(('6','68')) else (c+'.BJ' if c.startswith('9') else c+'.SZ')
df['ts']=df.code.map(ts_of)
need = set(evd)
for n in (10,20,40):
    need |= {cal[ci[x]+n] for x in evd}
inl = ",".join(f"'{t}'" for t in df.ts.unique()); dil = ",".join(f"'{x}'" for x in sorted(need))
px = {(t,str(dd)):float(c) for t,dd,c in con.execute(f"SELECT ts_code,trade_date,close FROM daily WHERE ts_code IN ({inl}) AND trade_date IN ({dil})").fetchall()}
day = {}
for dd in evd:
    sub = df[df.date==dd]
    f1,f2,f4 = cal[ci[dd]+10],cal[ci[dd]+20],cal[ci[dd]+40]
    b = np.array([px.get((t,dd),np.nan) for t in sub.ts])
    a1 = np.array([px.get((t,f1),np.nan) for t in sub.ts])
    a2 = np.array([px.get((t,f2),np.nan) for t in sub.ts])
    a4 = np.array([px.get((t,f4),np.nan) for t in sub.ts])
    ok = ~(np.isnan(b)|np.isnan(a1)|np.isnan(a2)|np.isnan(a4)) & (b>0)
    if ok.sum()>=1000:
        day[dd] = np.column_stack([sub.p10.values[ok],sub.p20.values[ok],sub.p40.values[ok],a1[ok]/b[ok]-1,a2[ok]/b[ok]-1,a4[ok]/b[ok]-1])
ds = sorted(day)
print('评估日', len(ds), flush=True)

def nw_t(x, lags=5):
    x=np.asarray(x,float); n=len(x); mu=x.mean(); e=x-mu
    g0=(e*e).sum()/n
    s=g0
    for l in range(1,lags+1):
        w=1-l/(lags+1)
        s+=2*w*(e[l:]*e[:-l]).sum()/n
    return mu/np.sqrt(s/n)

# 细网格 0.01
res=[]
for a in np.arange(0,1.001,0.01):
    for b in np.arange(0,1.001-a,0.01):
        c=1-a-b
        ic20=[]
        for dd in ds:
            arr=day[dd]
            f=a*arr[:,0]+b*arr[:,1]+c*arr[:,2]
            ic20.append(stats.spearmanr(f,arr[:,4])[0])
        res.append((round(a,2),round(b,2),round(c,2),np.mean(ic20),nw_t(ic20)))
rdf=pd.DataFrame(res,columns=['w10','w20','w40','ic20','nw_t20']).sort_values('ic20',ascending=False)
rdf.to_csv(OUT/'grid_fine_nw.csv',index=False)
print(rdf.head(10).to_string(index=False))
# 最优点分年IC + top vs 生产权重配对差
best=rdf.iloc[0]
def day_ic(a,b,c):
    out={}
    for dd in ds:
        arr=day[dd]
        f=a*arr[:,0]+b*arr[:,1]+c*arr[:,2]
        out[dd]=stats.spearmanr(f,arr[:,4])[0]
    return out
ib=day_ic(best.w10,best.w20,best.w40)
ip=day_ic(0.0,0.375,0.625)
dif=np.array([ib[k]-ip[k] for k in ds])
print(f"\n最优({best.w10},{best.w20},{best.w40}) vs 生产(0,0.375,0.625): 日均IC差 {dif.mean():+.4f} NW-t {nw_t(dif):.2f}")
byr=pd.DataFrame({'d':list(ib),'ic_b':[ib[k] for k in ib],'ic_p':[ip[k] for k in ip]})
byr['yr']=byr.d.str[:4]
print(byr.groupby('yr')[['ic_b','ic_p']].mean().round(4).to_string())
json.dump({'best':[float(best.w10),float(best.w20),float(best.w40)],'ic20':float(best.ic20),'nw_t':float(best.nw_t20)}, open(OUT/'fine_best.json','w'))
