import pandas as pd, numpy as np, lightgbm as lgb
df = pd.read_parquet('C:/Users/zantan/mf40/samples_40d_mf.parquet')
df['date'] = df['date'].astype(str).str.replace('-', '', regex=False)
feats = ['f%d' % j for j in range(26)]
tr = df[df.date < '20260101']
X = tr[feats].to_numpy(float).copy()
lo, hi = np.nanpercentile(X, 1, 0), np.nanpercentile(X, 99, 0)
mu = np.nanmean(X, 0); sd = np.nanstd(X, 0) + 1e-12
X = np.clip(X, lo, hi); X = np.where(np.isfinite(X), (X - mu) / sd, 0.0)
y = np.clip(tr.y40.to_numpy(float), -1, 3)
m = lgb.train(dict(objective='regression', metric='l2', num_leaves=15, learning_rate=0.01,
    feature_fraction=0.6, bagging_fraction=0.6, bagging_freq=5, min_data_in_leaf=300,
    lambda_l1=0.5, lambda_l2=2.0, max_depth=5, min_gain_to_split=0.2, verbose=-1, num_threads=8),
    lgb.Dataset(X, y), num_boost_round=309)
g = m.feature_importance('gain'); s = g.sum()
order = np.argsort(g)[::-1]
print('gain总和', float(s), flush=True)
cum = 0
for r, i in enumerate(order, 1):
    cum += g[i]
    print(f'{r:2d} {feats[i]} gain={float(g[i]):.3e} 累计占比 {float(cum/s)*100:.1f}%', flush=True)
# 列间相关性: 特征信息重叠度
Xf = np.nan_to_num(X, 0.0)
C = np.corrcoef(Xf.T)
off = C[~np.eye(26, dtype=bool)]
print(f'列间|corr|: 均值 {np.abs(off).mean():.2f} 中位 {np.median(np.abs(off)):.2f} >0.9的对数 {(np.abs(off)>0.9).sum()//2}', flush=True)
