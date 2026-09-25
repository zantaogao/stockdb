# -*- coding: utf-8 -*-
"""v4c 样本构建 0905
A) 全市场算 13 个第二批创新特征 → 截面IC → analysis/uncon_feat_ic_batch2_0905.csv
B) samples_v4_big(31维) + f31触板频率 + f32下影线 + f33量价相关 → samples_v4c_raw.parquet
只算特征与IC，不训练。日期统一 YYYY-MM-DD。
"""
import duckdb, numpy as np, pandas as pd, time
BASE='/Users/zantao/.hermes/stockdb'
t0=time.time()
def fmt(s):
    s=s.astype(str); return np.where(s.str.contains('-'),s,s.str[:4]+'-'+s.str[4:6]+'-'+s.str[6:8])

con=duckdb.connect(BASE+'/tushare.db',read_only=True)
pool=set(con.execute(f"select distinct code from read_parquet('{BASE}/analysis/retrain_10d_v4/samples_v4_big.parquet')").df()['code'])
d=con.execute("""select ts_code,trade_date,open,high,low,close,pre_close,
  coalesce(pct_chg,0) as pct, vol, amount from daily where trade_date>='20180601'""").df()
d=d[d.ts_code.str[:6].isin(pool)].copy()
lim=con.execute("select ts_code,trade_date,up_limit,down_limit from stk_limit where trade_date>='20180601'").df()
db=con.execute("select ts_code,trade_date,turnover_rate,circ_mv from daily_basic where trade_date>='20180601'").df()
mf=con.execute("select stock_code as symbol,strftime(date,'%Y-%m-%d') as date,main_net,retail_net from money_flow where date>=DATE '2018-06-01'").df()
sb=con.execute("select ts_code, substr(ts_code,1,3) as brd from stock_basic").df()
af=con.execute("select ts_code,trade_date,adj_factor from adj_factor where trade_date>='20180601'").df()
con.close()

for t in (d,lim,db,af): t['date']=fmt(t['trade_date'])
d['symbol']=d.ts_code.str[:6]
d['ret']=d.pct/100.0
d=d.merge(lim[['ts_code','date','up_limit','down_limit']],on=['ts_code','date'],how='left')
d=d.merge(db[['ts_code','date','turnover_rate','circ_mv']],on=['ts_code','date'],how='left')
d=d.merge(mf,on=['symbol','date'],how='left')
d=d.merge(sb,on='ts_code',how='left')
d=d.merge(af[['ts_code','date','adj_factor']],on=['ts_code','date'],how='left')
d=d.sort_values(['symbol','date']).reset_index(drop=True)
print(f'加载 {time.time()-t0:.0f}s rows={len(d):,}',flush=True)

g=lambda col,fn: d.groupby('symbol',sort=False)[col].transform(fn)

# ===== 第一批3特征（进训练） =====
ul=d.up_limit; touch=((d.high>=ul*0.998)&ul.notna()).fillna(False)
seal=((d.close>=ul*0.998)&ul.notna()).fillna(False)
d['_touch']=touch.astype(float); d['_zba']=(touch&~seal).astype(float)
d['f31_touch20']=g('_touch',lambda s:s.rolling(20,min_periods=10).sum())
tb=g('_zba',lambda s:s.rolling(20,min_periods=5).sum()); tt=g('_touch',lambda s:s.rolling(20,min_periods=5).sum())
d['f32_zha20']=np.where(tt>0,tb/tt.replace(0,np.nan),np.nan)
rng=(d.high-d.low).replace(0,np.nan)
wick=(d[['open','close']].min(axis=1)-d.low)/rng
d['_wv']=wick*d.vol; d['_wok']=wick.notna().astype(float)
d['f32_wick20']=g('_wv',lambda s:s.rolling(20,min_periods=10).sum())/ \
    d.groupby('symbol',sort=False).apply(lambda x:(x.vol*x._wok).rolling(20,min_periods=10).sum()).reset_index(level=0,drop=True).replace(0,np.nan) if False else np.nan
# 上式groupby.apply索引麻烦，直接循环算两列
wv=(wick*d.vol).values; wok=wick.notna().astype(float).values; vol=d.vol.values
out_w=np.full(len(d),np.nan)
for sym,idx in d.groupby('symbol',sort=False).indices.items():
    a=wv[idx]; b=(vol[idx]*wok[idx])
    ca=pd.Series(a).rolling(20,min_periods=10).sum().values
    cb=pd.Series(b).rolling(20,min_periods=10).sum().values
    with np.errstate(divide='ignore',invalid='ignore'):
        out_w[idx]=np.where(cb>0,ca/cb,np.nan)
d['f32_wick20']=out_w
d['_ptr']=d.pct*d.turnover_rate
pm=g('pct',lambda s:s.rolling(20,min_periods=15).mean()); tm=g('turnover_rate',lambda s:s.rolling(20,min_periods=15).mean())
mxy=g('_ptr',lambda s:s.rolling(20,min_periods=15).mean())
vx=g('pct',lambda s:s.rolling(20,min_periods=15).var()); vy=g('turnover_rate',lambda s:s.rolling(20,min_periods=15).var())
d['f33_pvcorr20']=(mxy-pm*tm)/np.sqrt(vx*vy).replace(0,np.nan)

# ===== 第二批创新特征 =====
# f34 隔夜动量占比：20日累计隔夜收益/累计|日内收益|（散户情绪跳空驱动度）
d['_on']=d.open/d.pre_close-1; d['_idio']=d.close/d.open-1
d['f34_overnight_share']=g('_on',lambda s:s.rolling(20,min_periods=15).sum())/ \
    (g('_idio',lambda s:s.abs().rolling(20,min_periods=15).sum())+1e-9)
# f35 距250日最高价%（锚定套牢结构）
d['f35_dist_high250']=(d.groupby('symbol',sort=False).high.transform(lambda s:s.rolling(250,min_periods=120).max())-d.close)/d.close*100
# f36 最近涨停日的板块内流通市值排名（龙头1/跟风大），10日内有效
zt=((d.close>=ul*0.998)&ul.notna()).fillna(False)
zz=d[zt].copy(); zz['rk']=zz.groupby(['brd','date']).circ_mv.rank(ascending=False,method='first')
d=d.merge(zz[['ts_code','date','rk']].rename(columns={'rk':'_rk'}),on=['ts_code','date'],how='left')
d['_rkf']=d.groupby('symbol',sort=False)['_rk'].transform(lambda s:s.ffill())
d['_ztdi']=pd.to_datetime(d.date).where(zt.values)
d['_ztdif']=d.groupby('symbol',sort=False)['_ztdi'].transform(lambda s:s.ffill())
ok=(pd.to_datetime(d.date)-d['_ztdif']).dt.days<=10
d['f36_leader_rank']=d['_rkf'].where(ok.fillna(False))
# f37 昨日封板今日内盘承接，60日均（打板资金接力意愿）
d['_sealf']=seal.astype(float); d['_prev_seal']=d.groupby('symbol',sort=False)['_sealf'].shift(1)
d['_carry']=np.where(d._prev_seal==1, d.close/d.open-1, np.nan)
d['f37_zt_carry60']=d.groupby('symbol',sort=False)['_carry'].transform(lambda s:s.rolling(60,min_periods=3).mean())
# f38 主力净流入波动率20（占流通市值%，资金不稳定度）
cmv=d.circ_mv.replace(0,np.nan)
d['_mfp']=d.main_net/cmv*100
d['f38_mf_vola20']=d.groupby('symbol',sort=False)['_mfp'].transform(lambda s:s.rolling(20,min_periods=15).std())
# f39 量能背离：创60日价格新高但量/前60日峰值量的缺口（缩量新高=惜售 or 无量=没跟风）
hh=d.groupby('symbol',sort=False).high.transform(lambda s:s.rolling(61,min_periods=40).max())
newhigh=(d.high>=hh).fillna(False)
d['_volshift']=d.groupby('symbol',sort=False).vol.transform(lambda s:s.shift(1))
peakvol=d.groupby('symbol',sort=False)['_volshift'].transform(lambda s:s.rolling(60,min_periods=40).max())
dvv=np.where(newhigh, 1-d.vol/peakvol.replace(0,np.nan), np.nan)
d['f39_vol_diverge']=pd.Series(dvv,index=d.index)
# f40 跌停基因120
dl=((d.close<=d.down_limit*1.002)&d.down_limit.notna()).fillna(False)
d['_dl']=dl.astype(float)
d['f40_down_gene120']=d.groupby('symbol',sort=False)['_dl'].transform(lambda s:s.rolling(120,min_periods=60).sum())
# f41 散户拥挤度：散户净买/成交额 20日均（retail_net单位万元, amount千元）
d['_retail_sh']=d.retail_net*10/(d.amount*1000+1)
d['f41_retail_crowd20']=d.groupby('symbol',sort=False)['_retail_sh'].transform(lambda s:s.rolling(20,min_periods=15).mean())
# f42 ln流通市值（规模因子）
d['f42_ln_circmv']=np.log(cmv)
# f43 换手率变异系数20（筹码交换不稳定度）
tmean=d.groupby('symbol',sort=False).turnover_rate.transform(lambda s:s.rolling(20,min_periods=15).mean())
tstd=d.groupby('symbol',sort=False).turnover_rate.transform(lambda s:s.rolling(20,min_periods=15).std())
d['f43_turn_cv20']=tstd/tmean.replace(0,np.nan)
# f44/f45 收益偏度 20/60（左侧尾部=恐慌盘 or 妖股脉冲）
d['f44_skew20']=d.groupby('symbol',sort=False).ret.transform(lambda s:s.rolling(20,min_periods=15).skew())
d['f45_skew60']=d.groupby('symbol',sort=False).ret.transform(lambda s:s.rolling(60,min_periods=40).skew())
# f46 连跌天数（诅咒/超卖）
neg=(d.ret<0).values; ls=np.zeros(len(d)); run=0.
for i,v in enumerate(neg):
    run=run+1 if v else 0; ls[i]=run
d['f46_lose_streak']=ls
print(f'特征 {time.time()-t0:.0f}s',flush=True)

# ===== 前向收益 + IC =====
d['adjclose']=d.close*d.adj_factor
d['fwd10']=d.groupby('symbol',sort=False).adjclose.transform(lambda s:s.shift(-10)/s-1)
ev=d[(d.date>='2025-01-01')&d.fwd10.notna()].replace([np.inf,-np.inf],np.nan)
cnt=ev.groupby('symbol').date.transform('count'); ev=ev[cnt>=60]
print(f'评估行 {len(ev):,}',flush=True)

B2=['f32_zha20','f34_overnight_share','f35_dist_high250','f36_leader_rank','f37_zt_carry60',
    'f38_mf_vola20','f39_vol_diverge','f40_down_gene120','f41_retail_crowd20','f42_ln_circmv',
    'f43_turn_cv20','f44_skew20','f45_skew60','f46_lose_streak']
CTRL=['f31_touch20','f32_wick20','f33_pvcorr20']
rows=[]
for f in B2:
    sub=ev[['date',f,'fwd10']+CTRL].dropna(subset=[f])
    raw={}; res={}
    for dt,dg in sub.groupby('date'):
        if len(dg)<100: continue
        x=dg[f].rank().values; y=dg['fwd10'].rank().values
        raw[dt]=pd.Series(x).corr(pd.Series(y))
        ctrl=dg[CTRL].rank()
        if ctrl.notna().all().all():
            X=np.column_stack([np.ones(len(dg)),ctrl.values])
            beta,*_=np.linalg.lstsq(X,y,rcond=None)
            resid=y-X@beta
            xr=x-x.mean(); rr=resid-resid.mean()
            den=np.sqrt((xr*xr).sum()*(rr*rr).sum())
            res[dt]=(xr*rr).sum()/den if den>0 else np.nan
    for kind,dd in [('raw',raw),('resid',res)]:
        s=pd.Series(dd).dropna()
        for yr in ['2025','2026']:
            ss=s[s.index.astype(str).str[:4]==yr]
            if len(ss)>20 and ss.std()>0:
                rows.append(dict(feat=f,kind=kind,year=yr,n=len(ss),ic=round(ss.mean(),4),
                    t=round(ss.mean()/ss.std()*np.sqrt(len(ss)),2),win=round((ss>0).mean(),3)))
r=pd.DataFrame(rows).sort_values(['feat','kind','year'])
pd.set_option('display.width',200)
print(r.to_string(index=False),flush=True)
r.to_csv(BASE+'/analysis/uncon_feat_ic_batch2_0905.csv',index=False)
d[['symbol','date','f31_touch20','f32_wick20','f33_pvcorr20']+B2].to_parquet(BASE+'/analysis/retrain_10d_v4/_uncon_feats.parquet',index=False)

# ===== 拼 v4c 训练样本 =====
sm=pd.read_parquet(BASE+'/analysis/retrain_10d_v4/samples_v4_big.parquet')
sm=sm.merge(d[['symbol','date','f31_touch20','f32_wick20','f33_pvcorr20']],
            left_on=['code','date'],right_on=['symbol','date'],how='left').drop(columns=['symbol'])
print(f'v4c样本 {len(sm):,} 缺失率 f31={sm.f31_touch20.isna().mean():.3f} f32={sm.f32_wick20.isna().mean():.3f} f33={sm.f33_pvcorr20.isna().mean():.3f}',flush=True)
sm.to_parquet(BASE+'/analysis/retrain_10d_v4/samples_v4c.parquet',index=False)
print(f'完成 {time.time()-t0:.0f}s → samples_v4c.parquet',flush=True)