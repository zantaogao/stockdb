# -*- coding: utf-8 -*-
"""v4c 训练：v4_big 参数完全照抄（lr/leaves/早停/按日期80%切分/训练段标准化）
特征 = 31维(f0..f30) + f31_touch20 + f32_wick20 + f33_pvcorr20
对照 = 同一验证段上 v4_big(31维) 的逐日IC（配对检验用同一批日）
输出 daily_ic_v4c.csv + A/B 配对 NW-t
"""
import json, time, os
import numpy as np, pandas as pd, lightgbm as lgb
from scipy import stats
BASE='/Users/zantao/.hermes/stockdb/analysis/retrain_10d_v4'
t0=time.time()
df=pd.read_parquet(BASE+'/samples_v4c.parquet')
feats31=[f'f{j}' for j in range(31)]
feats=feats31+['f31_touch20','f32_wick20','f33_pvcorr20']
print(f'样本 {len(df):,}  日期 {df.date.min()} ~ {df.date.max()}',flush=True)

dates=np.sort(df['date'].unique())
split=dates[int(len(dates)*0.8)]
tr=df[df['date']<split]; va=df[df['date']>=split]
print(f'切分日 {split}  训练 {len(tr):,} / 验证 {len(va):,}',flush=True)

Xtr=tr[feats].to_numpy(float).copy(); Xva=va[feats].to_numpy(float).copy()
ytr=tr['y'].to_numpy(float); yva=va['y'].to_numpy(float)
stats_dict={}
for j in range(len(feats)):
    v=Xtr[:,j]; v=v[np.isfinite(v)]
    lo2,hi2=np.percentile(v,1),np.percentile(v,99)
    mu,sd=float(v.mean()),float(v.std())
    stats_dict[feats[j]]={'mean':mu,'std':sd,'low':float(lo2),'high':float(hi2)}
    Xtr[:,j]=(np.clip(Xtr[:,j],lo2,hi2)-mu)/sd
    Xva[:,j]=(np.clip(Xva[:,j],lo2,hi2)-mu)/sd
Xtr=np.nan_to_num(Xtr,nan=0.0); Xva=np.nan_to_num(Xva,nan=0.0)

params={'objective':'regression','metric':'l2','num_leaves':15,'learning_rate':0.008,
 'feature_fraction':0.6,'bagging_fraction':0.6,'bagging_freq':5,'min_data_in_leaf':300,
 'lambda_l1':0.5,'lambda_l2':2.0,'max_depth':5,'min_gain_to_split':0.2,'verbose':1,'num_threads':8}
model=lgb.train(params,lgb.Dataset(Xtr,ytr),num_boost_round=2000,
  valid_sets=[lgb.Dataset(Xtr,ytr),lgb.Dataset(Xva,yva)],valid_names=['train','val'],
  callbacks=[lgb.early_stopping(50),lgb.log_evaluation(200)])
pred=model.predict(Xva)
print(f'训练 {time.time()-t0:.0f}s 树数 {model.num_trees()}',flush=True)

# 逐日IC
vd=va['date'].to_numpy()
recs=[]
for dte in np.unique(vd):
    m=vd==dte
    if m.sum()>=200:
        recs.append({'date':str(dte),'n':int(m.sum()),
                     'rank_ic':float(stats.spearmanr(pred[m],yva[m])[0])})
ic=pd.DataFrame(recs); ic.to_csv(BASE+'/daily_ic_v4c.csv',index=False)
ics=ic['rank_ic'].to_numpy()
print(f'v4c 验证日IC {ics.mean():+.4f} (n={len(ics)}) 正占比 {(ics>0).mean()*100:.0f}%',flush=True)

# 对照: 31维单独打分（同一切分/同标准化口径）
X31va=Xva[:,:31].copy(); X31tr=Xtr[:,:31].copy()
m31=lgb.train(params,lgb.Dataset(X31tr,ytr),num_boost_round=model.best_iteration if model.best_iteration>0 else model.num_trees()//2+1,
  callbacks=[lgb.log_evaluation(1000)])
p31=m31.predict(X31va)
recs31=[]
for dte in np.unique(vd):
    m=vd==dte
    if m.sum()>=200:
        recs31.append({'date':str(dte),'rank_ic':float(stats.spearmanr(p31[m],yva[m])[0])})
b=pd.DataFrame(recs31); b.to_csv(BASE+'/daily_ic_v4c_base31.csv',index=False)
print(f'base31 验证日IC {b["rank_ic"].mean():+.4f}',flush=True)

# 配对 Newey-West t (lag=10)
j=ic.merge(b,on='date'); dd=(j['rank_ic_x']-j['rank_ic_y']).to_numpy()
n=len(dd); mu=dd.mean(); x=dd-mu
l=10
s0=(x*x).sum()/n
gw=s0
for i in range(1,l+1):
    w=1-i/(l+1); c=(x[i:]*x[:-i]).sum()/n
    gw+=2*w*c
se=np.sqrt(gw/n)
print(f'配对差 {mu:+.5f}  NW-se {se:.5f}  NW-t {mu/se:+.2f} (lag=10, n={n})',flush=True)

# 十分组 v4c
pairs=sorted(zip(pred,yva),key=lambda t:t[0]); d10=max(1,len(pairs)//10)
dec=[float(np.mean([r for _,r in pairs[k*d10:(k+1)*d10]])*100) for k in range(10)]
print('十分组:',' '.join(f'D{k+1}:{v:+.2f}%' for k,v in enumerate(dec)),flush=True)

model.save_model(BASE+'/lgb_reg_v4c.txt')
json.dump(stats_dict,open(BASE+'/v10_v4c_stats.json','w'))
json.dump({'n_samples':int(len(df)),'split_date':str(split),'best_iteration':int(model.best_iteration),
 'val_ic_v4c':float(ics.mean()),'val_ic_base31':float(b['rank_ic'].mean()),
 'pair_nw_t':float(mu/se),'pair_mean_diff':float(mu),'val_days':int(n),
 'pos_ratio_v4c':float((ics>0).mean()),'deciles':dec},
 open(BASE+'/train_v4c_results.json','w'),indent=1,ensure_ascii=False)
print(f'完成 {time.time()-t0:.0f}s',flush=True)