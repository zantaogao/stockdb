import pandas as pd, numpy as np, lightgbm as lgb
df = pd.read_parquet('C:/Users/zantan/mf40/samples_40d_mf.parquet')
df['date'] = df['date'].astype(str)
f = ['f%d' % j for j in range(26)] + ['mf20']
tr = df[df.date < '20250101']
X = tr[f].to_numpy(float)
print('mf20 nan率', float(np.isnan(X[:, -1]).mean()), '非零率', float((np.nan_to_num(X[:, -1]) != 0).mean()), 'std', float(np.nanstd(X[:, -1])), flush=True)
X = np.array(X, dtype=float, copy=True); X[~np.isfinite(X)] = 0.0; y = tr.y40.to_numpy(float)
m = lgb.train(dict(objective='regression', metric='l2', num_leaves=15, learning_rate=0.01,
    feature_fraction=0.6, bagging_fraction=0.6, bagging_freq=5, min_data_in_leaf=300,
    lambda_l1=0.5, lambda_l2=2.0, max_depth=5, min_gain_to_split=0.2, verbose=-1, num_threads=8),
    lgb.Dataset(X, y), num_boost_round=309)
g = m.feature_importance('gain')
print('mf20 gain', float(g[-1]), 'gain排名', int((g > g[-1]).sum()) + 1, '/', len(g), flush=True)
print('gain最低5列', sorted([(float(x), f[i]) for i, x in enumerate(g)])[:5], flush=True)
