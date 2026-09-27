# 三臂对比 v3: prod | v8旧卖法(重评) | v8+生产卖法(融合融合分)
# 目的: 拆"选股引擎差异" vs "卖出规则差异"
import numpy as np, pandas as pd, lightgbm as lgb, duckdb
from pathlib import Path
B = Path('/Users/zantao/.hermes/stockdb/analysis/retrain_20260927_v8')
COST=0.0015
con=duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db',read_only=True)
cal=[str(r[0]).replace('-','') for r in con.execute("SELECT DISTINCT trade_date FROM daily ORDER BY trade_date").fetchall()]
ci={x:i for i,x in enumerate(cal)}
imap={str(t).replace('-',''):float(c) for t,c in con.execute("SELECT date,close FROM index_daily WHERE index_code='000852'").fetchall()}
def ts_of(c): return c+'.SH' if c.startswith(('6','68')) else (c+'.BJ' if c.startswith('9') else c+'.SZ')
P={}
for k in ['10d','20d','40d']:
    m=lgb.Booster(model_str=(B/f'lgb_reg_{k}_v8.txt').read_text())
    d=pd.read_parquet(B/f'samples_{k}.parquet'); nf=m.num_feature()
    sub=d[d.date>='20250304']
    P[k]=pd.DataFrame({'date':sub.date.values,'code':sub.code.values,'p_'+k:m.predict(sub.iloc[:,2:2+nf].values)})
v8=P['10d'].merge(P['20d'],on=['date','code']).merge(P['40d'],on=['date','code'])
v8['f8']=0.25*v8.p_10d+0.75*v8.p_40d; v8['fo']=0.375*v8.p_20d+0.625*v8.p_40d
dates=sorted(d for d in v8.date.unique() if ci.get(d) is not None and d<='20260730')
codes=sorted(v8.code.unique()); idx={c:i for i,c in enumerate(codes)}; di={d:i for i,d in enumerate(dates)}
PX=np.full((len(dates),len(codes)),np.nan)
dil=",".join(f"'{d}'" for d in dates); allts=",".join(f"'{ts_of(c)}'" for c in codes)
for t_,d_,c_ in con.execute(f"SELECT ts_code,trade_date,close FROM daily WHERE ts_code IN ({allts}) AND trade_date IN ({dil})").fetchall():
    j=idx.get(str(t_)[:6]); i=di.get(str(d_))
    if j is not None and i is not None: PX[i,j]=float(c_)
PXC=np.full_like(PX,np.nan)
for i in range(1,len(dates)):
    ok=~np.isnan(PX[i-1])&~np.isnan(PX[i])&(PX[i-1]>0); PXC[i,ok]=PX[i,ok]/PX[i-1,ok]-1
LIM=np.where(np.array([c.startswith(('30','68')) for c in codes]),0.197,0.097)
M8=np.full((len(dates),len(codes)),np.nan); Mo=np.full_like(M8,np.nan)
for r in v8.itertuples():
    i=di.get(r.date)
    if i is not None: M8[i,idx[r.code]]=r.f8; Mo[i,idx[r.code]]=r.fo
def pctmat(M):
    O=np.full_like(M,np.nan)
    for i in range(len(M)):
        row=M[i]; ok=~np.isnan(row)
        if ok.sum()>100: O[i,ok]=(pd.Series(row[ok]).rank(pct=True)*100).values
    return O
P8=pctmat(M8); Po=pctmat(Mo)
halved=np.full(len(dates),False)
for i,d_ in enumerate(dates):
    if d_ in imap and ci[d_]>0 and cal[ci[d_]-1] in imap:
        halved[i]=imap[d_]/imap[cal[ci[d_]-1]]-1<=-0.02
def simulate(Pct,M,br,sr):
    hd=np.zeros(len(codes),int); cost=np.full(len(codes),np.nan); act=np.zeros(len(codes),bool); alloc=np.zeros(len(codes))
    cash=1.0; navs=[]; trades=[]
    for i,d_ in enumerate(dates):
        for j in np.where(act)[0]:
            if hd[j]==0: continue
            p=PX[i,j]
            if np.isnan(p): p=PX[i-1,j] if i>0 and not np.isnan(PX[i-1,j]) else cost[j]
            pnl=p/cost[j]-1
            a,why=sr(j,i,pnl,Pct,M,hd)
            if a:
                cash+=alloc[j]*(p/cost[j])*(1-COST); trades.append((d_,codes[j],why,pnl,hd[j])); act[j]=False; alloc[j]=0
        slots=20-act.sum()
        if slots>0 and i>0:
            cand=np.where((~act)&(~np.isnan(PX[i])))[0]; order=cand[np.argsort(-Pct[i,cand])]
            for j in order:
                if act[j] or slots<=0: continue
                if np.isnan(PXC[i,j]) or PXC[i,j]>=LIM[j]: continue
                if not br(j,i,Pct,M): continue
                per=cash/slots*(0.5 if halved[i] else 1.0)
                act[j]=True; cost[j]=PX[i,j]; hd[j]=0; alloc[j]=per; cash-=per; slots-=1
        hd[act]+=1
        mv=sum(alloc[j]*(PX[i,j]/cost[j] if not np.isnan(PX[i,j]) and cost[j]>0 else 1.0) for j in np.where(act)[0])
        navs.append((d_,cash+mv,int(act.sum())))
    nav=pd.DataFrame(navs,columns=['date','nav','npos']); nav['ret']=nav.nav.pct_change()
    return nav,pd.DataFrame(trades,columns=['date','code','reason','pnl','held'])
def sell_prod(j,i,pnl,Pct,M,hd):
    if pnl<=-0.12: return True,'stop'
    if Pct[i,j]<30 and pnl<0: return True,'score_neg'
    if hd[j]>=20 and Pct[i,j]<30 and pnl<0.08: return True,'5B'
    if hd[j]>=30 and M[i,j]<np.nanmean(M[i]): return True,'5C'
    return False,None
def sell_v8(j,i,pnl,Pct,M,hd):
    if pnl<=-0.12: return True,'stop'
    if hd[j]>=40: return True,'expire40'
    if hd[j]>=20:
        n=max((~np.isnan(M[i])).sum(),1)
        if Pct[i,j]<100-50*100/n: return True,'reeval_out'
    return False,None
def buy_prod(j,i,Pct,M): return Pct[i,j]>=90
def buy_v8(j,i,Pct,M):
    n=max((~np.isnan(M[i])).sum(),1)
    return Pct[i,j]>=100-20*100/n
for label,M,Pct,br,sr in [
  ('A_prod',Mo,Po,buy_prod,sell_prod),
  ('B_v8_old_sell',M8,P8,buy_v8,sell_prod),   # 新引擎+生产卖法
  ('C_v8_new_sell',M8,P8,buy_v8,sell_v8)]:
    nav,tr=simulate(Pct,M,br,sr); nav['year']=nav.date.str[:4]
    print(f'\\n===== {label} =====',flush=True)
    for y,g in nav.groupby('year'):
        g=g.dropna(subset=['ret'])
        ann=(g.nav.iloc[-1]/g.nav.iloc[0])**(244/len(g))-1
        shp=g.ret.mean()/g.ret.std()*np.sqrt(244) if g.ret.std()>0 else 0
        dd=(g.nav/g.nav.cummax()-1).min()*100
        print(f'  {y}: 年化{ann*100:+6.1f}%  夏普{shp:5.2f}  回撤{dd:5.1f}%')
    full=(nav.nav.iloc[-1]/nav.nav.iloc[0])**(244/len(nav))-1
    print(f'  全段年化{full*100:+.1f}%  笔数{len(tr)}  胜率{(tr.pnl>0).mean()*100:.0f}%  均持{tr.held.mean():.0f}d  {tr.reason.value_counts().to_dict()}')
