# 残差IC：剥离 bench_ret10(10日动量) 后的净IC
import duckdb, numpy as np, pandas as pd
DB='/Users/zantao/.hermes/stockdb/tushare.db'
c=duckdb.connect(DB,read_only=True)
daily=c.execute("select ts_code,trade_date,pct_chg,vol,amount,close,high,low,open,pre_close from daily where trade_date>='20240601'").df()
adj=c.execute("select ts_code,trade_date,adj_factor from adj_factor where trade_date>='20240601'").df()
lim=c.execute("select ts_code,trade_date,up_limit from stk_limit where trade_date>='20240601'").df()
dbsc=c.execute("select ts_code,trade_date,turnover_rate from daily_basic where trade_date>='20240601'").df()
mf=c.execute("select stock_code as symbol,strftime(date,'%Y%m%d') as trade_date,main_net from money_flow where date>=DATE '2024-06-01'").df()
nine=c.execute("select ts_code,trade_date,up_count,nine_up_turn from stk_nineturn where trade_date>='20240601'").df()
c.close()
daily['symbol']=daily.ts_code.str[:6]
daily=daily.sort_values(['ts_code','trade_date']).reset_index(drop=True)
daily=daily.merge(adj,on=['ts_code','trade_date'],how='left')
g=daily.groupby('ts_code')
daily['adjclose']=daily.close*daily.adj_factor
daily['fwd10']=g.adjclose.transform(lambda s:s.shift(-10)/s-1)
daily=daily.merge(lim,on=['ts_code','trade_date'],how='left')
daily=daily.merge(dbsc,on=['ts_code','trade_date'],how='left')
daily=daily.merge(mf,on=['symbol','trade_date'],how='left')
daily=daily.merge(nine,on=['ts_code','trade_date'],how='left')
g=daily.groupby('ts_code',sort=False)
touched=(daily.high>=daily.up_limit*0.998)&daily.up_limit.notna()
sealed=(daily.close>=daily.up_limit*0.998)&daily.up_limit.notna()
daily['_touch']=touched.astype(float)
daily['_zba']=((touched)&(~sealed)).astype(float)
daily['f2_touch20']=g._touch.transform(lambda s:s.rolling(20,min_periods=10).sum())
tb=g._zba.transform(lambda s:s.rolling(20,min_periods=5).sum())
tt=g._touch.transform(lambda s:s.rolling(20,min_periods=5).sum())
daily['f3_zba20']=np.where(tt>0,tb/tt.replace(0,np.nan),np.nan)
rng=(daily.high-daily.low).replace(0,np.nan)
wick=(daily[['open','close']].min(axis=1)-daily.low)/rng
daily['_wick']=wick; daily['_wv']=wick*daily.vol
g=daily.groupby('ts_code',sort=False)
daily['f4_wick20']=g._wv.transform(lambda s:s.rolling(20,min_periods=10).sum())/g.vol.transform(lambda s:(s*wick.notna()).rolling(20,min_periods=10).sum()).replace(0,np.nan)
daily['_sealf']=sealed.astype(float)
daily['f14_gene120']=daily.groupby('ts_code',sort=False)._sealf.transform(lambda s:s.rolling(120,min_periods=60).sum())
upv=daily.vol.where(daily.pct_chg>0,0.0); dnv=daily.vol.where(daily.pct_chg<0,0.0)
daily['_upv']=upv; daily['_dnv']=dnv
g=daily.groupby('ts_code',sort=False)
daily['f10_uvasym20']=np.log((g._upv.transform(lambda s:s.rolling(20,min_periods=10).sum())+1)/(g._dnv.transform(lambda s:s.rolling(20,min_periods=10).sum())+1))
ptr=daily.pct_chg*daily.turnover_rate; daily['_ptr']=ptr
g=daily.groupby('ts_code',sort=False)
pm=g.pct_chg.transform(lambda s:s.rolling(20,min_periods=15).mean()); tm=g.turnover_rate.transform(lambda s:s.rolling(20,min_periods=15).mean())
mxy=g._ptr.transform(lambda s:s.rolling(20,min_periods=15).mean())
vx=g.pct_chg.transform(lambda s:s.rolling(20,min_periods=15).var()); vy=g.turnover_rate.transform(lambda s:s.rolling(20,min_periods=15).var())
daily['f11_pvcorr20']=(mxy-pm*tm)/np.sqrt(vx*vy).replace(0,np.nan)
# gap exposure
def gap_exposure(dfg):
    o=dfg.open.values;l=dfg.low.values;pc=dfg.pre_close.values
    n=len(dfg);out=np.zeros(n);gaps=[]
    for i in range(n):
        if o[i]>pc[i]*1.002: gaps.append([i,pc[i]])
        gaps=[gg for gg in gaps if i-gg[0]<=10]
        if gaps:
            amp=np.mean([(b-o[j])/b for j,b in gaps]); out[i]=len(gaps)*amp*100
        gaps=[gg for gg in gaps if not (l[i]<=gg[1])]
    return pd.Series(out,index=dfg.index)
daily['f15_gap']=daily.groupby('ts_code',group_keys=False).apply(gap_exposure)
daily['bench_ret10']=daily.groupby('ts_code',sort=False).pct_chg.transform(lambda s:s.rolling(10,min_periods=8).sum())
daily['_vol20']=daily.groupby('ts_code',sort=False).pct_chg.transform(lambda s:s.rolling(20,min_periods=15).std())
# 换手率20日均（规模代理）
daily['_turn20']=daily.groupby('ts_code',sort=False).turnover_rate.transform(lambda s:s.rolling(20,min_periods=15).mean())
daily['f7_up_count']=daily.up_count

ev=daily[(daily.trade_date>='20250101')&daily.fwd10.notna()].copy()
cnt=ev.groupby('ts_code').trade_date.transform('count'); ev=ev[cnt>=60]
ev=ev[~ev.ts_code.str.endswith('.BJ')].replace([np.inf,-np.inf],np.nan)

FEATS=['f2_touch20','f3_zba20','f4_wick20','f10_uvasym20','f11_pvcorr20','f14_gene120','f15_gap','f7_up_count']
CTRL=['bench_ret10','_vol20','_turn20']
rows=[]
for f in FEATS:
    sub=ev[['trade_date',f,'fwd10']+CTRL].dropna()
    raw={};res={}
    for d,dg in sub.groupby('trade_date'):
        if len(dg)<100: continue
        x=dg[f].rank(); y=dg['fwd10'].rank()
        raw[d]=x.corr(y)
        # 残差化：截面内对控制变量OLS取残差再算IC
        X=np.column_stack([np.ones(len(dg))]+[dg[k].rank().values for k in CTRL])
        beta,*_=np.linalg.lstsq(X,y.values,rcond=None)
        resid=y.values-X@beta
        res[d]=np.corrcoef(x.values,resid)[0,1]
    for name,dd in [('raw',raw),('resid',res)]:
        s=pd.Series(dd).dropna()
        for yr in ['2025','2026']:
            ss=s[s.index.str[:4]==yr]
            if len(ss)>20:
                rows.append(dict(feat=f,kind=name,year=yr,n=len(ss),
                    ic=round(ss.mean(),4),t=round(ss.mean()/ss.std()*np.sqrt(len(ss)),2),
                    win=round((ss>0).mean(),3)))
r=pd.DataFrame(rows).sort_values(['feat','kind','year'])
pd.set_option('display.width',200); print(r.to_string(index=False))