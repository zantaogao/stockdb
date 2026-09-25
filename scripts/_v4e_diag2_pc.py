# -*- coding: utf-8 -*-
# 验证假设：f50-f53 在训练段(全量切分 split=2025-03-05 之前) 100% NaN → LightGBM 不分箱 → 未使用
import numpy as np, pandas as pd, lightgbm as lgb
m = pd.read_parquet('samples_v4e.parquet')
NEW4 = ['f50_intraday_dd','f51_vol_burst','f52_downside_var','f53_kyle_illiq']
tr = m[m['date'] < '2025-03-05']; va = m[m['date'] >= '2025-03-05']
for c in NEW4:
    print(c, 'train段覆盖率 %.4f' % tr[c].notna().mean(), ' val段覆盖率 %.4f' % va[c].notna().mean(), flush=True)
X = m[['f0'] + NEW4].to_numpy(dtype=float)
ds = lgb.Dataset(X[:200000], label=m['y'].to_numpy()[:200000], feature_name=['f0'] + NEW4)
ds.construct()
# 看每列分箱数：全NaN列 bin 数为 0
summary = ds.get_feature_names() if hasattr(ds, 'get_feature_names') else None
print('feature_name:', summary, flush=True)
print('DONE', flush=True)