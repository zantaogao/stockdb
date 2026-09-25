# -*- coding: utf-8 -*-
"""v4f 终审（2026-09-19）：base31 vs base31+kyle+amihud
样本 = C:/Users/zantan/v4d_retrain/samples_v4c.parquet (34维含y, 2019-04起, 不复制)
新维 = C:/Users/zantan/v4f_retrain/micro_feats_0919.parquet (kyle/amihud, 2025-04-08起, 之前行 NaN 直喂 LGBM)
方法学照抄 _train_v4d_pc.py：按日期切 80/20、训练段 stats、NW-t lag10、gain、十分组 + 分月拆解。
背景：09-06 v4e 轮 pair_mean_diff=0.0/MD5相同=训练没吃进新维，结论作废，本轮重做。
"""
import json, time, sys
import numpy as np, pandas as pd, lightgbm as lgb
from scipy import stats
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
BASE = 'C:/Users/zantan/v4f_retrain'
t0 = time.time()
sm = pd.read_parquet('C:/Users/zantan/v4d_retrain/samples_v4c.parquet')
mf = pd.read_parquet(BASE + '/micro_feats_0919.parquet')
# code 对齐: micro ts_code 'sh.600000' -> 纯6位; trade_date '20250408' -> '2025-04-08' 对齐 samples 的 date 字符串
mf['code'] = mf['ts_code'].str.split('.').str[-1].str.zfill(6)
mf['date'] = pd.to_datetime(mf['trade_date'], format='%Y%m%d').dt.strftime('%Y-%m-%d')
mf = mf[['code', 'date', 'kyle', 'amihud']].drop_duplicates(['code', 'date'])
n0 = len(sm)
sm = sm.merge(mf, on=['code', 'date'], how='left')
assert len(sm) == n0, f'merge改变行数 {n0}->{len(sm)}'
feats31=[f'f{j}' for j in range(31)]
NEW5=['f39_vol_diverge','f32_zha20','f34_overnight_share','f43_turn_cv20','f44_skew20']
NEW4=['f50_intraday_dd','f51_vol_burst','f52_downside_var','f53_kyle_illiq']
feats=feats31+NEW5+NEW4
print(f'样本 {len(sm):,}',flush=True)

dates=np.sort(sm['date'].unique()); split=dates[int(len(dates)*0.8)]
tr=sm[sm['date']<split]; va=sm[sm['date']>=split]
print(f'切分日 {split} 训练 {len(tr):,} / 验证 {len(va):,}',flush=True)

Xtr=tr[feats].to_numpy(dtype=float).copy(); Xva=va[feats].to_numpy(dtype=float).copy()
ytr=tr['y'].to_numpy(dtype=float); yva=va['y'].to_numpy(dtype=float)
stats_dict={}
for j in range(31):
    v=Xtr[:,j]; v=v[np.isfinite(v)]
    lo,hi=np.percentile(v,1),np.percentile(v,99)
    mu,sd=float(v.mean()),float(v.std())
    stats_dict[feats[j]]={'mean':mu,'std':sd,'low':float(lo),'high':float(hi)}
    Xtr[:,j]=(np.clip(Xtr[:,j],lo,hi)-mu)/sd
    Xva[:,j]=(np.clip(Xva[:,j],lo,hi)-mu)/sd
Xtr[:,31:]=np.where(np.isfinite(Xtr[:,31:]),Xtr[:,31:],np.nan)
Xva[:,31:]=np.where(np.isfinite(Xva[:,31:]),Xva[:,31:],np.nan)

params={'objective':'regression','metric':'l2','num_leaves':15,'learning_rate':0.008,
 'feature_fraction':0.6,'bagging_fraction':0.6,'bagging_freq':5,'min_data_in_leaf':300,
 'lambda_l1':0.5,'lambda_l2':2.0,'max_depth':5,'min_gain_to_split':0.2,'verbose':1,'num_threads':8}
model=lgb.train(params,lgb.Dataset(Xtr,ytr),num_boost_round=2500,
  valid_sets=[lgb.Dataset(Xtr,ytr),lgb.Dataset(Xva,yva)],valid_names=['train','val'],
  callbacks=[lgb.early_stopping(50),lgb.log_evaluation(200)])
pred=model.predict(Xva)
vd=va['date'].to_numpy()
def daily_ic(p):
    out={}
    for dte in np.unique(vd):
        m=vd==dte
        if m.sum()>=200: out[str(dte)]=float(stats.spearmanr(p[m],yva[m])[0])
    return pd.Series(out)
ic_v4e=daily_ic(pred); ic_v4e.to_csv(BASE+'/daily_ic_v4e.csv')
print(f'v4e IC {ic_v4e.mean():+.4f} (n={len(ic_v4e)}) 正占比 {(ic_v4e>0).mean()*100:.0f}% best_iter={model.best_iteration}',flush=True)

m36=lgb.train(params,lgb.Dataset(Xtr[:,:36],ytr),num_boost_round=model.best_iteration)
ic_v4d=daily_ic(m36.predict(Xva[:,:36])); ic_v4d.to_csv(BASE+'/daily_ic_v4e_base36.csv')
print(f'v4d(36维) IC {ic_v4d.mean():+.4f}',flush=True)

j=pd.concat([ic_v4e,ic_v4d],axis=1,keys=['a','b']).dropna()
dd=(j['a']-j['b']).to_numpy(); n=len(dd); mu=dd.mean(); x=dd-mu; l=10
gw=((x*x).sum()+sum(2*(1-i/(l+1))*(x[i:]*x[:-i]).sum() for i in range(1,l+1)))/n
se=np.sqrt(gw/n)
print(f'配对差 {mu:+.5f} NW-t {mu/se:+.2f} (n={n})',flush=True)

imp=model.feature_importance(importance_type='gain')
top=sorted(zip(feats,imp),key=lambda t:-t[1])[:15]
print('gain top15:',' '.join(f'{k}:{v/1e3:.0f}k' for k,v in top),flush=True)

pairs=sorted(zip(pred,yva),key=lambda t:t[0]); d10=max(1,len(pairs)//10)
dec=[float(np.mean([r for _,r in pairs[k*d10:(k+1)*d10]])*100) for k in range(10)]
print('十分组:',' '.join(f'D{k+1}:{v:+.2f}%' for k,v in enumerate(dec)),flush=True)
model.save_model(BASE+'/lgb_reg_v4e.txt')
json.dump(stats_dict, open(BASE+'/stats_v4e.json','w'))
json.dump({'split_date':str(split),'best_iteration':int(model.best_iteration),
 'ic_v4e':float(ic_v4e.mean()),'ic_v4d36':float(ic_v4d.mean()),'pair_nw_t':float(mu/se),
 'pair_mean_diff':float(mu),'val_days':int(n),'pos_ratio_v4e':float((ic_v4e>0).mean()),
 'gain_top15':{k:float(v) for k,v in top},'deciles':dec},
 open(BASE+'/train_v4e_results.json','w'),indent=1)
print(f'完成 {time.time()-t0:.0f}s',flush=True)