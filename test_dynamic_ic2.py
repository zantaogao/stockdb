#!/usr/bin/env python3
"""
直接对比固定 vs 动态参数重算7/31强买IC。
用当前fusion_3f_signals表的数据，按两种参数重新计算分数。
"""
import sqlite3
import numpy as np

conn = sqlite3.connect('/Users/zantao/.hermes/stockdb/state.db')

# 获取7/31所有数据
rows = conn.execute("""
    SELECT stock_code, ma_decay, flow_alpha, vol_adj, 
           reg10, fusion_3f_score, signal
    FROM fusion_3f_signals
    WHERE REPLACE(date, '-', '') = '20260731'
""").fetchall()

print(f"样本数: {len(rows)}")

# 固定参数
FIX = {'ma_mean': 1.347, 'ma_std': 28.5, 'flow_mean': -0.023, 'flow_std': 0.012, 'vol_mean': 0.110, 'vol_std': 0.075}
# 动态参数
DYN = {'ma_mean': 0.2334, 'ma_std': 5.0350, 'flow_mean': 0.0304, 'flow_std': 0.0428, 'vol_mean': 0.1606, 'vol_std': 0.1766}

def calc(row, p):
    ma = row['ma_decay'] or 0
    flow = row['flow_alpha'] or 0
    vol = row['vol_adj'] or 0
    reg = row['reg10'] or 0
    ma_z = (ma - p['ma_mean']) / p['ma_std']
    flow_z = (flow - p['flow_mean']) / p['flow_std']
    vol_z = -(vol - p['vol_mean']) / p['vol_std']
    reg_z = -(reg - 0.03) / 0.05
    raw = 0.3 * ma_z + 0.3 * flow_z + 0.2 * vol_z + 0.2 * reg_z
    return max(0, min(100, (raw + 2) / 4 * 100))

# 重新计算分数
fixed_scores = [calc({'ma_decay': r[1], 'flow_alpha': r[2], 'vol_adj': r[3], 'reg10': r[4]}, FIX) for r in rows]
dyn_scores = [calc({'ma_decay': r[1], 'flow_alpha': r[2], 'vol_adj': r[3], 'reg10': r[4]}, DYN) for r in rows]

# 强买组（当前signal）
strong_buy_idx = [i for i, r in enumerate(rows) if r[6] == '强买']

print(f"\n=== 强买组（当前signal）===")
print(f"固定参数: avg={np.mean([fixed_scores[i] for i in strong_buy_idx]):.2f}, "
      f"min={min(fixed_scores[i] for i in strong_buy_idx):.2f}, "
      f"max={max(fixed_scores[i] for i in strong_buy_idx):.2f}")
print(f"动态参数: avg={np.mean([dyn_scores[i] for i in strong_buy_idx]):.2f}, "
      f"min={min(dyn_scores[i] for i in strong_buy_idx):.2f}, "
      f"max={max(dyn_scores[i] for i in strong_buy_idx):.2f}")

# 全市场
print(f"\n=== 全市场 ===")
print(f"固定参数: avg={np.mean(fixed_scores):.2f}, p75={np.percentile(fixed_scores, 75):.2f}")
print(f"动态参数: avg={np.mean(dyn_scores):.2f}, p75={np.percentile(dyn_scores, 75):.2f}")

# 计算IC（用fusion_score作为代理）
print(f"\n=== 分数 vs reg10 相关性（越强买reg10越低越好）===")
fb_scores = [fixed_scores[i] for i in strong_buy_idx]
fb_rets = [- (r[4] or 0) for r in [rows[i] for i in strong_buy_idx]]  # reg10低=收益高
db_scores = [dyn_scores[i] for i in strong_buy_idx]
db_rets = [- (r[4] or 0) for r in [rows[i] for i in strong_buy_idx]]

fixed_ic = np.corrcoef(fb_scores, fb_rets)[0, 1]
dyn_ic = np.corrcoef(db_scores, db_rets)[0, 1]

print(f"固定IC: {fixed_ic:.4f}")
print(f"动态IC: {dyn_ic:.4f}")

# 检查分数区分度
print(f"\n=== 分数区分度 ===")
print(f"固定: 强买avg-全市场p25 = {np.mean(fb_scores) - np.percentile(fixed_scores, 25):.2f}")
print(f"动态: 强买avg-全市场p25 = {np.mean(db_scores) - np.percentile(dyn_scores, 25):.2f}")

# 强买组内分数标准差
print(f"固定强买std: {np.std(fb_scores):.2f}")
print(f"动态强买std: {np.std(db_scores):.2f}")

conn.close()
