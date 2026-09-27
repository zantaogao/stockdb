#!/usr/bin/env python3
"""40d v3 综合对比：vs 旧模型 / vs v2 + 因子重要性"""
import sys, json
from pathlib import Path
import duckdb
import lightgbm as lgb
import numpy as np
from scipy import stats

BASE = Path.home() / '.hermes' / 'stockdb'
sys.path.insert(0, str(BASE))

from core.db import TUSHARE_DB_PATH
from core.scoring import _compute_ml_features

import sqlite3
c = sqlite3.connect(str(BASE / 'state.db'))
codes = [r[0] for r in c.execute("""
    SELECT stock_code FROM signal_history
    WHERE REPLACE(date,'-','') = (SELECT MAX(REPLACE(date,'-','')) FROM signal_history)
    ORDER BY RANDOM() LIMIT 200
""").fetchall()]
c.close()

conn = duckdb.connect(str(TUSHARE_DB_PATH), read_only=True)
feats = []
for code in codes:
    try:
        f29, _ = _compute_ml_features(code, conn, as_of_date='20260806')
        if f29 is not None:
            feats.append(f29)
    except Exception:
        pass
conn.close()
X = np.array(feats, dtype=np.float64)
print(f'样本: {len(X)} 只')

def normalize_batch(X, s):
    Xn = X.copy()
    for j in range(X.shape[1]):
        key = f'feat_{j}'
        if key in s and s[key]['std'] > 0:
            Xn[:, j] = np.clip(Xn[:, j], s[key]['low'], s[key]['high'])
            Xn[:, j] = (Xn[:, j] - s[key]['mean']) / s[key]['std']
    return np.nan_to_num(Xn, nan=0.0)

models = {
    '旧(生产)': ('retired_20260926/lgb_reg_40d_new_stkfactor.txt','retired_20260926/v6_norm_stats_40d_tushare_v2_stkfactor.json'),
    'v2(5000树)': ('lgb_reg_40d_mac_v2.txt', 'v40_mac_v2_stats.json'),
    'v3(2076树)': ('lgb_reg_40d_mac_v3.txt', 'v40_mac_v3_stats.json'),
}
preds = {}
for name, (mf, sf) in models.items():
    m = lgb.Booster(model_file=str(BASE / 'models' / mf))
    s = json.load(open(str(BASE / 'models' / sf)))
    preds[name] = m.predict(normalize_batch(X, s))
    print(f'{name}: {m.num_trees()} 树 | mean={preds[name].mean():+.3f} std={preds[name].std():.3f}')

print('\n=== 排序一致性（Spearman）===')
names = list(models.keys())
for i in range(len(names)):
    for j in range(i+1, len(names)):
        sp = stats.spearmanr(preds[names[i]], preds[names[j]])[0]
        sign = sum(1 for a, b in zip(preds[names[i]], preds[names[j]]) if (a >= 0) == (b >= 0)) / len(X)
        top_i = set(np.argsort(preds[names[i]])[-10:])
        top_j = set(np.argsort(preds[names[j]])[-10:])
        print(f'  {names[i]} vs {names[j]}: Spearman={sp:.4f} 符号一致={sign:.1%} top10交集={len(top_i & top_j)}/10')

print('\n=== v3 因子重要性（对比旧模型）===')
m3 = lgb.Booster(model_file=str(BASE / 'models/lgb_reg_40d_mac_v3.txt'))
imp3 = m3.feature_importance('gain')
factor3 = sum(imp3[26:29]) / imp3.sum() * 100
m_old = lgb.Booster(model_file=str(BASE / 'models/retired_20260926/lgb_reg_40d_new_stkfactor.txt'))
imp_old = m_old.feature_importance('gain')
factor_old = sum(imp_old[26:29]) / imp_old.sum() * 100
print(f'  旧模型因子权重: {factor_old:.1f}% | v3 因子权重: {factor3:.1f}%')
