# -*- coding: utf-8 -*-
import lightgbm as lgb, numpy as np, pandas as pd
m = pd.read_parquet('samples_v4e.parquet')
f31 = ['f%d' % i for i in range(31)]
NEW5 = ['f39_vol_diverge','f32_zha20','f34_overnight_share','f43_turn_cv20','f44_skew20']
NEW4 = ['f50_intraday_dd','f51_vol_burst','f52_downside_var','f53_kyle_illiq']
feats = f31 + NEW5 + NEW4
X = m[feats].to_numpy(dtype=float)
print('X shape', X.shape, flush=True)
for j in range(31, 40):
    col = X[:, j]; fin = np.isfinite(col)
    vals, cnt = np.unique(col[fin], return_counts=True)
    print(feats[j], 'finite%%=%.1f' % (fin.mean()*100), 'min=%.6g max=%.6g' % (col[fin].min(), col[fin].max()),
          'std=%.6g' % col[fin].std(), 'nunique=%d' % len(vals), 'top3=%s' % [float(v) for v in vals[np.argsort(-cnt)[:3]]], flush=True)
ds = lgb.Dataset(X[:200000], label=m['y'].to_numpy()[:200000], feature_name=feats)
ds.construct()
print('bin used feats:', sum(1 for n in ds.feature_name), flush=True)
print('num_total_bin:', ds.num_total_bin if hasattr(ds,'num_total_bin') else 'n/a', flush=True)