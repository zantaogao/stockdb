#!/usr/bin/env python3
"""40d 新旧模型对比：同批股票预测 Spearman/符号一致性/分布（部署前验证）"""
import sys, json, random
from pathlib import Path
import duckdb
import lightgbm as lgb
import numpy as np
from scipy import stats

BASE = Path.home() / '.hermes' / 'stockdb'
sys.path.insert(0, str(BASE))

from core.db import TUSHARE_DB_PATH
from core.scoring import _compute_ml_features, BASE_KEEP_INDICES, FACTOR_FIELDS


def normalize_batch(X, s):
    """批量标准化（与训练脚本 normalize 一致：clip 1%~99% + z-score）"""
    Xn = X.copy()
    for j in range(X.shape[1]):
        key = f'feat_{j}'
        if key in s and s[key]['std'] > 0:
            Xn[:, j] = np.clip(Xn[:, j], s[key]['low'], s[key]['high'])
            Xn[:, j] = (Xn[:, j] - s[key]['mean']) / s[key]['std']
    return np.nan_to_num(Xn, nan=0.0)

# 抽样 200 只（从 watchlist/signal_history 最新日抽，确保有近期评分）
import sqlite3
c = sqlite3.connect(str(BASE / 'state.db'))
codes = [r[0] for r in c.execute("""
    SELECT stock_code FROM signal_history
    WHERE REPLACE(date,'-','') = (SELECT MAX(REPLACE(date,'-','')) FROM signal_history)
    ORDER BY RANDOM() LIMIT 200
""").fetchall()]
c.close()
print(f'抽样 {len(codes)} 只')

# 特征（8/6 截止，as_of 防泄漏）
conn = duckdb.connect(str(TUSHARE_DB_PATH), read_only=True)
feats, preds_new, preds_old, failed = [], [], [], 0
for code in codes:
    try:
        f29, _ = _compute_ml_features(code, conn, as_of_date='20260806')
        if f29 is None:
            failed += 1
            continue
        feats.append(f29)
    except Exception:
        failed += 1
        continue
conn.close()
print(f'特征计算成功 {len(feats)} / 失败 {failed}')
if len(feats) < 50:
    print('样本不足，跳过对比'); sys.exit(0)

X = np.array(feats, dtype=np.float64)

# 新模型 + 新 stats
m_new = lgb.Booster(model_file=str(BASE / 'models/lgb_reg_40d_mac_v2.txt'))
s_new = json.load(open(str(BASE / 'models/v40_mac_v2_stats.json')))
preds_new = m_new.predict(normalize_batch(X, s_new))

# 旧模型 + 旧 stats
m_old = lgb.Booster(model_file=str(BASE / 'models/lgb_reg_40d_new_stkfactor.txt'))
s_old = json.load(open(str(BASE / 'models/v6_norm_stats_40d_tushare_v2_stkfactor.json')))
preds_old = m_old.predict(normalize_batch(X, s_old))

# 对比
sp = stats.spearmanr(preds_new, preds_old)[0]
sign_same = sum(1 for a, b in zip(preds_new, preds_old) if (a >= 0) == (b >= 0)) / len(preds_new)

print(f'\n=== 新旧模型对比（{len(preds_new)} 只）===')
print(f'Spearman 相关: {sp:.4f}')
print(f'符号一致性: {sign_same:.1%}')
print(f'\n分布对比:')
for name, p in [('新v2', preds_new), ('旧', preds_old)]:
    print(f'  {name}: mean={p.mean():+.3f} std={p.std():.3f} min={p.min():.2f} p25={np.percentile(p,25):.2f} p50={np.percentile(p,50):.2f} p75={np.percentile(p,75):.2f} max={p.max():.2f}')

# top10 交集（按各自预测排序前10）
top_new = set(np.argsort(preds_new)[-10:])
top_old = set(np.argsort(preds_old)[-10:])
print(f'\n新旧 top10 交集: {len(top_new & top_old)}/10')
print(f'\n结论: {"✅ 方向一致，可部署" if sp > 0.7 and sign_same > 0.85 else "⚠️ 差异较大，需谨慎评估"}')
