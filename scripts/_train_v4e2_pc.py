# -*- coding: utf-8 -*-
"""v4e2 公平对拍（2026-09-06）：样本限 date>=2025-04-08（分钟特征存在段），段内80/20时间切分。
v4e=40维(31+v4d_new5+min4) vs v4d36=36维，同切分同参数。修 v4e 首跑的切分缺陷
（全样本切分下训练段 f50-f53 100%NaN，LightGBM 不分箱，两模型逐bit相同）。"""
import json, time
import numpy as np, pandas as pd, lightgbm as lgb
from scipy import stats
BASE='C:/Users/zantan/v4e_retrain'
t0=time.time()
sm=pd.read_parquet(BASE+'/samples_v4e.parquet')
sm=sm[sm['date']>='2025-04-08'].reset_index(drop=True)
feats31=[f'f{j}' for j in range(31)]
NEW5=['f39_vol_diverge','f32_zha20','f34_overnight_share','f43_turn_cv20','f44_skew20']
NEW4=['f50_intraday_dd','f51_vol_burst','f52_downside_var','f53_kyle_illiq']
feats=feats31+NEW5+NEW4
print(f'重叠段样本 {len(sm):,}',flush=True)

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
model=lgb.train(params,lgb.Dataset(Xtr,ytr,feature_name=feats),num_boost_round=2500,
  valid_sets=[lgb.Dataset(Xva,yva)],valid_names=['val'],
  callbacks=[lgb.early_stopping(50),lgb.log_evaluation(200)])
pred=model.predict(Xva)
vd=va['date'].to_numpy()
def daily_ic(p):
    out={}
    for dte in np.unique(vd):
        m=vd==dte
        if m.sum()>=200: out[str(dte)]=float(stats.spearmanr(p[m],yva[m])[0])
    return pd.Series(out)
ic_a=daily_ic(pred); ic_a.to_csv(BASE+'/daily_ic_v4e2.csv')
print(f'v4e2(40维) IC {ic_a.mean():+.4f} (n={len(ic_a)}) 正占比 {(ic_a>0).mean()*100:.0f}% best_iter={model.best_iteration}',flush=True)

# v4d36 各自早停、各自打满（首版共用 best_iter=3 导致基座只3棵树≈空模型，对拍不公平——0906修正）
m36=lgb.train(params,lgb.Dataset(Xtr[:,:36],ytr,feature_name=feats[:36]),num_boost_round=2500,
  valid_sets=[lgb.Dataset(Xva[:,:36],yva)],valid_names=['val36'],
  callbacks=[lgb.early_stopping(50),lgb.log_evaluation(200)])
ic_b=daily_ic(m36.predict(Xva[:,:36])); ic_b.to_csv(BASE+'/daily_ic_v4e2_base36.csv')
print(f'v4d36(同段) IC {ic_b.mean():+.4f}',flush=True)

j=pd.concat([ic_a,ic_b],axis=1,keys=['a','b']).dropna()
dd=(j['a']-j['b']).to_numpy(); n=len(dd); mu=dd.mean(); x=dd-mu; l=10
gw=((x*x).sum()+sum(2*(1-i/(l+1))*(x[i:]*x[:-i]).sum() for i in range(1,l+1)))/n
se=np.sqrt(gw/n)
print(f'配对差 {mu:+.5f} NW-t {mu/se:+.2f} (n={n})',flush=True)

imp=model.feature_importance(importance_type='gain')
top=sorted(zip(feats,imp),key=lambda t:-t[1])[:15]
print('gain top15:',' '.join(f'{k}:{v/1e3:.0f}k' for k,v in top),flush=True)
print('min4 gain:',{feats[j_]:float(i_) for j_,i_ in zip(range(36,40),imp[36:40])},flush=True)

pairs=sorted(zip(pred,yva),key=lambda t:t[0]); d10=max(1,len(pairs)//10)
dec=[float(np.mean([r for _,r in pairs[k*d10:(k+1)*d10]])*100) for k in range(10)]
print('十分组:',' '.join(f'D{k+1}:{v:+.2f}%' for k,v in enumerate(dec)),flush=True)
model.save_model(BASE+'/lgb_reg_v4e2.txt')
json.dump(stats_dict, open(BASE+'/stats_v4e2.json','w'))
json.dump({'split_date':str(split),'best_iteration':int(model.best_iteration),
 'ic_v4e2':float(ic_a.mean()),'ic_v4d36':float(ic_b.mean()),'pair_nw_t':float(mu/se),
 'pair_mean_diff':float(mu),'val_days':int(n),'pos_ratio_v4e2':float((ic_a>0).mean()),
 'gain_min4':{feats[j_]:float(i_) for j_,i_ in zip(range(36,40),imp[36:40])},
 'gain_top15':{k:float(v) for k,v in top},'deciles':dec},
 open(BASE+'/train_v4e2_results.json','w'),indent=1)
print(f'完成 {time.time()-t0:.0f}s',flush=True)