# 40d v7 上线冒烟验证（2026-09-26）
import sys, json, numpy as np
sys.path.insert(0, '/Users/zantao/.hermes/stockdb')
from core import scoring as sc
sc._load_models()
print('40d模型: 树数', sc._reg40_model.num_trees(), '特征数', sc._reg40_model.num_feature(), '(v7应=165/30)')
print('40d stats keys:', len(sc._stats40), 'feat_29存在:', 'feat_29' in sc._stats40)
for code in ('600519', '300750', '920002'):
    f29, f38 = sc._compute_ml_features(code, sc._safe_connect())
    if f38 is None: print(code, 'f38=None'); continue
    f40 = np.append(f29, float(f38[23]))
    f40 = np.nan_to_num(sc._standardize(f40, sc._stats40), nan=0.0)
    print(code, 'ex5=', round(float(f38[23]), 4), 'v7分=', round(float(sc._reg40_model.predict(f40)[0]), 3))
