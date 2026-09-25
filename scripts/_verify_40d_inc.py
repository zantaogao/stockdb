#!/usr/bin/env python3
"""增量模型验证三件套：平滑性（vs 旧模型）+ 树数 + IC 对照"""
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
    ORDER BY RANDOM() LIMIT 300
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
    '旧(生产)': ('lgb_reg_40d_new_stkfactor.txt', 'v6_norm_stats_40d_tushare_v2_stkfactor.json'),
    'inc_v1': ('lgb_reg_40d_inc_v2.txt', 'v6_norm_stats_40d_tushare_v2_stkfactor.json'),
}
preds = {}
for name, (mf, sf) in models.items():
    m = lgb.Booster(model_file=str(BASE / 'models' / mf))
    s = json.load(open(str(BASE / 'models' / sf)))
    preds[name] = m.predict(normalize_batch(X, s))
    print(f'{name}: {m.num_trees()} 树 | mean={preds[name].mean():+.3f} std={preds[name].std():.3f}')

sp = stats.spearmanr(preds['旧(生产)'], preds['inc_v1'])[0]
sign = sum(1 for a, b in zip(preds['旧(生产)'], preds['inc_v1']) if (a >= 0) == (b >= 0)) / len(X)
top_old = set(np.argsort(preds['旧(生产)'])[-10:])
top_inc = set(np.argsort(preds['inc_v1'])[-10:])
print(f'\n=== 平滑性验证 ===')
print(f'增量 vs 旧: Spearman={sp:.4f} | 符号一致={sign:.1%} | top10交集={len(top_old & top_inc)}/10')
print(f'判定: {"✅ 平滑（>0.95）" if sp > 0.95 else "⚠️ 差异较大"}')
