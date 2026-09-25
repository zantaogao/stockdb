#!/usr/bin/env python3
"""验证脚本管道 vs 生产管道：旧模型预测 vs signal_history.reg40（同股票同日期）"""
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
# 8/6 信号日有 reg40 的股票
rows = c.execute("""
    SELECT stock_code, reg40 FROM signal_history
    WHERE REPLACE(date,'-','') = (SELECT MAX(REPLACE(date,'-','')) FROM signal_history)
    AND reg40 IS NOT NULL ORDER BY RANDOM() LIMIT 150
""").fetchall()
c.close()
print(f'抽样 {len(rows)} 只（8/6 信号日，有生产 reg40）')

conn = duckdb.connect(str(TUSHARE_DB_PATH), read_only=True)
sh_reg40, my_old_pred, my_new_pred, codes = [], [], [], []
for code, reg40 in rows:
    try:
        f29, _ = _compute_ml_features(code, conn, as_of_date='20260806')
        if f29 is None:
            continue
    except Exception:
        continue
    codes.append(code)
    sh_reg40.append(float(reg40))
    my_old_pred.append(f29)
    my_new_pred.append(f29)
conn.close()

X = np.array(my_old_pred, dtype=np.float64)

def normalize_batch(X, s):
    Xn = X.copy()
    for j in range(X.shape[1]):
        key = f'feat_{j}'
        if key in s and s[key]['std'] > 0:
            Xn[:, j] = np.clip(Xn[:, j], s[key]['low'], s[key]['high'])
            Xn[:, j] = (Xn[:, j] - s[key]['mean']) / s[key]['std']
    return np.nan_to_num(Xn, nan=0.0)

m_old = lgb.Booster(model_file=str(BASE / 'models/lgb_reg_40d_new_stkfactor.txt'))
s_old = json.load(open(str(BASE / 'models/v6_norm_stats_40d_tushare_v2_stkfactor.json')))
p_old = m_old.predict(normalize_batch(X, s_old))

m_new = lgb.Booster(model_file=str(BASE / 'models/lgb_reg_40d_mac_v2.txt'))
s_new = json.load(open(str(BASE / 'models/v40_mac_v2_stats.json')))
p_new = m_new.predict(normalize_batch(X, s_new))

sp_old = stats.spearmanr(sh_reg40, p_old)[0]
sp_new = stats.spearmanr(sh_reg40, p_new)[0]
print(f'\n=== 脚本管道 vs 生产管道验证 ===')
print(f'旧模型(我的脚本) vs 生产reg40: Spearman = {sp_old:.4f}')
print(f'新模型v2(我的脚本) vs 生产reg40: Spearman = {sp_new:.4f}')
print(f'生产reg40分布: mean={np.mean(sh_reg40):+.3f} std={np.std(sh_reg40):.3f}')
print(f'旧模型预测分布: mean={p_old.mean():+.3f} std={p_old.std():.3f}')
print(f'新模型v2分布:   mean={p_new.mean():+.3f} std={p_new.std():.3f}')
verdict = '✅ 脚本管道=生产管道（差异真实）' if sp_old > 0.8 else '❌ 脚本管道≠生产管道（验证脚本有bug）'
print(f'\n判定: {verdict}')

# 注意：生产 reg40 可能是"标准化后"的分（与预测分尺度不同），只比排序相关
