"""40d+mf20 单变量实验（2026-10-02 用户拍板"跑"）
两臂: A=旧29列基线(新训,同切分同参) B=30列(+mf20). 对拍=验证段配对日IC NW-t.
正解执行: ssh前台挂 + tee (0927纪律)."""
import os, json, time
import numpy as np, pandas as pd, lightgbm as lgb
from scipy import stats as st
BASE = __import__('pathlib').Path(os.environ.get('MF40_DIR', 'C:/Users/zantan/mf40'))
params = dict(objective='regression', metric='l2', num_leaves=15, learning_rate=0.01,
    feature_fraction=0.6, bagging_fraction=0.6, bagging_freq=5, min_data_in_leaf=300,
    lambda_l1=0.5, lambda_l2=2.0, max_depth=5, min_gain_to_split=0.2, verbose=1, num_threads=8)
FC29 = ['f%d'%j for j in range(26)] + ['f31','f32','f33']

def train(tag, parquet, feats, model_name):
    df = pd.read_parquet(BASE/parquet)
    df['date'] = df['date'].astype(str).str.replace('-','',regex=False)
    print(f'[{tag}] {len(df):,} 行 {len(feats)} 列', flush=True)
    dates = np.sort(df.date.unique()); split = dates[int(len(dates)*0.8)]
    tr, va = df[df.date<split], df[df.date>=split]
    Xtr, Xva = tr[feats].to_numpy(float).copy(), va[feats].to_numpy(float).copy()
    s = {}
    for j in range(len(feats)):
        v = Xtr[:,j]; v = v[np.isfinite(v)]
        lo, hi, mu, sd = np.percentile(v,1), np.percentile(v,99), float(v.mean()), float(v.std())
        s[f'feat_{j}'] = dict(mean=mu,std=sd,low=float(lo),high=float(hi))
        Xtr[:,j] = (np.clip(Xtr[:,j],lo,hi)-mu)/sd; Xva[:,j] = (np.clip(Xva[:,j],lo,hi)-mu)/sd
    Xtr = np.nan_to_num(Xtr,0.0); Xva = np.nan_to_num(Xva,0.0)
    t0=time.time()
    m = lgb.train(params, lgb.Dataset(Xtr, tr.y40.to_numpy(float)), num_boost_round=2000,
        valid_sets=[lgb.Dataset(Xtr,tr.y40.to_numpy(float)), lgb.Dataset(Xva,va.y40.to_numpy(float),)],
        valid_names=['train','val'], callbacks=[lgb.early_stopping(50), lgb.log_evaluation(200)])
    print(f'[{tag}] {time.time()-t0:.0f}s 树{m.num_trees()}', flush=True)
    pred = m.predict(Xva); vd = va.date.to_numpy(); y = va.y40.to_numpy(float)
    recs=[{'date':str(d),'rank_ic':float(st.spearmanr(pred[vd==d],y[vd==d])[0])} for d in np.unique(vd) if (vd==d).sum()>=200]
    pd.DataFrame(recs).to_csv(BASE/f'daily_ic_{tag}.csv', index=False)
    ics=[r['rank_ic'] for r in recs]
    json.dump(dict(tag=tag,n=len(df),split=str(split),trees=int(m.num_trees()),
        val_ic=float(np.mean(ics)),days=len(ics),pos=float(np.mean([i>0 for i in ics]))),
        open(BASE/f'result_{tag}.json','w'), indent=1)
    m.save_model(str(BASE/f'model_{tag}.txt')); json.dump(s, open(BASE/f'stats_{tag}.json','w'))
    print(f'[{tag}] 验证IC {np.mean(ics):+.4f} n={len(ics)}', flush=True)
    del df,tr,va,Xtr,Xva; return recs

ra = train('A_base29', 'samples_40d_mf.parquet', FC29, 'model_A_base29.txt')
rb = train('B_mf30', 'samples_40d_mf.parquet', FC29+['mf20'], 'model_B_mf30.txt')
da = {r['date']:r['rank_ic'] for r in ra}; db_ = {r['date']:r['rank_ic'] for r in rb}
com = sorted(set(da)&set(db_)); dif = np.array([db_[d]-da[d] for d in com])
def nw_t(x, lag=5):
    n = len(x); mu = x.mean(); xc = x - mu
    s0 = float((xc*xc).mean())
    longvar = s0 + 2.0*sum(float((xc[lag_i:]*xc[:-lag_i]).mean()) for lag_i in range(1, lag+1))
    longvar = max(longvar, s0)
    return mu/np.sqrt(longvar/n)
t = nw_t(dif)
print(f'配对 n={len(com)} 日均差 {dif.mean():+.5f} NW-t {t:+.2f}', flush=True)
json.dump(dict(n=len(com),mean_diff=float(dif.mean()),nw_t=float(t),
    ic_a=float(np.mean([da[d] for d in com])), ic_b=float(np.mean([db_[d] for d in com]))),
    open(BASE/'cmp_AB.json','w'), indent=1)
print('DONE', flush=True)
