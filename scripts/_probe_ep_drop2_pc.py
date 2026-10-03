"""v2: 纠正列名后重测'越跌分越高'+ln_cap/ep/bp单列IC (2026-10-02)
正确映射: f17=ep f18=bp f19=ln_cap f2=chg20(原始值另取)"""
import numpy as np, pandas as pd, lightgbm as lgb
from scipy import stats as st
df = pd.read_parquet('C:/Users/zantan/mf40/samples_40d_mf.parquet')
df['date'] = df['date'].astype(str).str.replace('-', '', regex=False)
df = df.sort_values(['date', 'code']).reset_index(drop=True)
feats = ['f%d' % j for j in range(26)] + ['f31', 'f32', 'f33']
dts = df.date.to_numpy(); y = df.y40.to_numpy(float)
raw_cap = df.f19.to_numpy(float)    # ln_cap 原始
raw_ep = df.f17.to_numpy(float)     # ep 原始
raw_bp = df.f18.to_numpy(float)     # bp 原始
tr = dts < '20260101'; te = ~tr
Xt = df.loc[tr, feats].to_numpy(float).copy()
lo, hi = np.nanpercentile(Xt, 1, 0), np.nanpercentile(Xt, 99, 0)
mu = np.nanmean(Xt, 0); sd = np.nanstd(Xt, 0) + 1e-12
Xt = np.clip(Xt, lo, hi); Xt = np.where(np.isfinite(Xt), (Xt - mu) / sd, 0.0)
m = lgb.train(dict(objective='regression', metric='l2', num_leaves=15, learning_rate=0.01,
    feature_fraction=0.6, bagging_fraction=0.6, bagging_freq=5, min_data_in_leaf=300,
    lambda_l1=0.5, lambda_l2=2.0, max_depth=5, min_gain_to_split=0.2, verbose=-1, num_threads=8),
    lgb.Dataset(Xt, np.clip(y[tr], -1, 3)), num_boost_round=309)
Xe = df.loc[te, feats].to_numpy(float).copy()
Xe = np.clip(Xe, lo, hi); Xe = np.where(np.isfinite(Xe), (Xe - mu) / sd, 0.0)
pred = m.predict(Xe)
dte = dts[te]; yte = y[te]
rc, re_, rb = raw_cap[te], raw_ep[te], raw_bp[te]
c20 = df.f2.to_numpy(float)[te]     # chg20 原始(小数)
lnc = np.nan_to_num(rc, 22.0); e_ = np.nan_to_num(re_, 0.5); b_ = np.nan_to_num(rb, 0.5)
print(f'预测{len(pred):,}', flush=True)
for mo in ['2026' + m2 for m2 in ['01','02','03','04','05','06','07']]:
    acc = []
    for d in np.unique(dte[(dte >= mo + '01') & (dte < mo + '32')]):
        k = dte == d
        if k.sum() < 200: continue
        p_, y_, c_ = pred[k], yte[k], np.nan_to_num(c20[k], 0.0)
        lnk = np.nan_to_num(rc[k], 22.0); ek = np.nan_to_num(re_[k], 0.5)
        top = np.argsort(p_)[-int(k.sum() * 0.1):]
        acc.append([st.spearmanr(p_, c_)[0], st.spearmanr(p_, lnk)[0], st.spearmanr(p_, ek)[0],
                    st.spearmanr(lnk, y_)[0], st.spearmanr(ek, y_)[0],
                    c_[top].mean() * 100, c_.mean() * 100,
                    np.exp(lnk[top].mean()) / 1e8, np.exp(lnk.mean()) / 1e8])
    a = np.array(acc)
    print(f'{mo}: corr(分,chg20) {a[:,0].mean():+.3f} corr(分,市值) {a[:,1].mean():+.3f} corr(分,ep) {a[:,2].mean():+.3f} | '
          f'小市值IC {a[:,3].mean():+.4f} epIC {a[:,4].mean():+.4f} | '
          f'top10%近20涨幅 {a[:,5].mean():+.1f}% 市场 {a[:,6].mean():+.1f}% | '
          f'top10%均市值 {np.mean(a[:,7]):.0f}亿 市场均 {np.mean(a[:,8]):.0f}亿', flush=True)
print('DONE', flush=True)
