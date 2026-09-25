# -*- coding: utf-8 -*-
"""v4d 训练对照：31维 + f39_vol_diverge + f32_zha20 + f34_overnight_share + f43_turn_cv20 + f44_skew20
参数照抄 v4_big。对照 base31 同切分同口径。NaN 交给 LGBM 原生处理（f39 只在触发票有值）。
注意：标准化 clip/zscore 跳过（f39/部分为稀疏特征，LGBM 对秩式树模型不需要标准化；
但为与 v4_big 完全同口径，31维仍按训练段stats标准化，新5维不标准化直接用原值——
树模型对单调变换不敏感，无碍）。"""
import json, time
import numpy as np, pandas as pd, lightgbm as lgb
from scipy import stats
BASE='/Users/zantao/.hermes/stockdb/analysis/retrain_10d_v4'
t0=time.time()
sm=pd.read_parquet(BASE+'/samples_v4c.parquet')          # date,code,f0..f30,f31,f32,f33,y
uf=pd.read_parquet(BASE+'/_uncon_feats.parquet')          # symbol,date,+第二批特征
sm=sm.merge(uf.rename(columns={'symbol':'code'}),on=['code','date'],how='left')
feats31=[f'f{j}' for j in range(31)]
NEW=['f39_vol_diverge','f32_zha20','f34_overnight_share','f43_turn_cv20','f44_skew20']
feats=feats31+NEW
print(f'样本 {len(sm):,} 新特征缺失率 { {c: round(sm[c].isna().mean(),3) for c in NEW} }',flush=True)

dates=np.sort(sm['date'].unique()); split=dates[int(len(dates)*0.8)]
tr=sm[sm['date']<split]; va=sm[sm['date']>=split]
print(f'切分日 {split} 训练 {len(tr):,} / 验证 {len(va):,}',flush=True)

Xtr=tr[feats].to_numpy(float).copy(); Xva=va[feats].to_numpy(float).copy()
ytr=tr['y'].to_numpy(float); yva=va['y'].to_numpy(float)
stats_dict={}
for j in range(31):
    v=Xtr[:,j]; v=v[np.isfinite(v)]
    lo,hi=np.percentile(v,1),np.percentile(v,99)
    mu,sd=float(v.mean()),float(v.std())
    stats_dict[feats[j]]={'mean':mu,'std':sd,'low':float(lo),'high':float(hi)}
    Xtr[:,j]=(np.clip(Xtr[:,j],lo,hi)-mu)/sd
    Xva[:,j]=(np.clip(Xva[:,j],lo,hi)-mu)/sd
# 新5维: 保留NaN(LGBM原生), inf->nan
Xtr[:,31:]=np.where(np.isfinite(Xtr[:,31:]),Xtr[:,31:],np.nan)
Xva[:,31:]=np.where(np.isfinite(Xva[:,31:]),Xva[:,31:],np.nan)

params={'objective':'regression','metric':'l2','num_leaves':15,'learning_rate':0.008,
 'feature_fraction':0.6,'bagging_fraction':0.6,'bagging_freq':5,'min_data_in_leaf':300,
 'lambda_l1':0.5,'lambda_l2':2.0,'max_depth':5,'min_gain_to_split':0.2,'verbose':1,'num_threads':8}
model=lgb.train(params,lgb.Dataset(Xtr,ytr),num_boost_round=2000,
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
ic_v4d=daily_ic(pred); ic_v4d.to_csv(BASE+'/daily_ic_v4d.csv')
print(f'v4d IC {ic_v4d.mean():+.4f} (n={len(ic_v4d)}) 正占比 {(ic_v4d>0).mean()*100:.0f}% 树{model.best_iteration}',flush=True)

m31=lgb.train(params,lgb.Dataset(Xtr[:,:31],ytr),num_boost_round=model.best_iteration)
ic_b31=daily_ic(m31.predict(Xva[:,:31])); ic_b31.to_csv(BASE+'/daily_ic_v4d_base31.csv')
print(f'base31 IC {ic_b31.mean():+.4f}',flush=True)

j=pd.concat([ic_v4d,ic_b31],axis=1,keys=['a','b']).dropna()
dd=(j['a']-j['b']).to_numpy(); n=len(dd); mu=dd.mean(); x=dd-mu; l=10
gw=((x*x).sum()+sum(2*(1-i/(l+1))*(x[i:]*x[:-i]).sum() for i in range(1,l+1)))/n
se=np.sqrt(gw/n)
print(f'配对差 {mu:+.5f} NW-t {mu/se:+.2f} (n={n})',flush=True)

# 新特征重要性
imp=model.feature_importance(importance_type='gain')
top=sorted(zip(feats,imp),key=lambda t:-t[1])[:12]
print('gain top12:',' '.join(f'{k}:{v/1e3:.0f}k' for k,v in top),flush=True)

pairs=sorted(zip(pred,yva),key=lambda t:t[0]); d10=max(1,len(pairs)//10)
dec=[float(np.mean([r for _,r in pairs[k*d10:(k+1)*d10]])*100) for k in range(10)]
print('十分组:',' '.join(f'D{k+1}:{v:+.2f}%' for k,v in enumerate(dec)),flush=True)
model.save_model(BASE+'/lgb_reg_v4d.txt')
json.dump({'split_date':str(split),'best_iteration':int(model.best_iteration),
 'ic_v4d':float(ic_v4d.mean()),'ic_base31':float(ic_b31.mean()),'pair_nw_t':float(mu/se),
 'pair_mean_diff':float(mu),'val_days':int(n),'pos_ratio_v4d':float((ic_v4d>0).mean()),
 'gain_top12':{k:float(v) for k,v in top},'deciles':dec},
 open(BASE+'/train_v4d_results.json','w'),indent=1)
print(f'完成 {time.time()-t0:.0f}s',flush=True)