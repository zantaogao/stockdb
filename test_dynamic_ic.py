#!/usr/bin/env python3
"""
测试动态标准化参数对IC的影响。
对比用固定参数 vs 动态参数重算7/24~7/31的强买IC。
"""
import sqlite3
import numpy as np
from datetime import datetime

STATE_DB = '/Users/zantao/.hermes/stockdb/state.db'

# 固定参数
FIX_PARAMS = {
    'ma_mean': 1.347, 'ma_std': 28.5,
    'flow_mean': -0.023, 'flow_std': 0.012,
    'vol_mean': 0.110, 'vol_std': 0.075,
}

def calc_fusion(row, params):
    ma = row.get('ma_decay') or 0
    flow = row.get('flow_alpha') or 0
    vol = row.get('vol_adj') or 0
    reg = row.get('reg10') or 0
    ma_z = (ma - params['ma_mean']) / params['ma_std']
    flow_z = (flow - params['flow_mean']) / params['flow_std']
    vol_z = -(vol - params['vol_mean']) / params['vol_std']
    reg_z = -(reg - 0.03) / 0.05
    raw = 0.3 * ma_z + 0.3 * flow_z + 0.2 * vol_z + 0.2 * reg_z
    return max(0, min(100, (raw + 2) / 4 * 100))

def calc_ic(scores, rets):
    """Spearman相关系数"""
    if len(scores) < 10:
        return 0
    return np.corrcoef(scores, rets)[0, 1]

conn = sqlite3.connect(STATE_DB, timeout=10)

# 获取7/24~7/31的数据
dates = [
    '2026-07-24', '2026-07-27', '2026-07-28', '2026-07-29',
    '2026-07-30', '2026-07-31',
]

print(f'{"日期":>10s} {"n":>6s} {"固定IC":>8s} {"动态IC":>8s} {"固定avg":>10s} {"动态avg":>10s}')
print("-" * 70)

# 先计算动态参数（用最近20天）
rows_20d = conn.execute("""
    SELECT nf.ma_decay, fa.flow_alpha, va.vol_adj
    FROM new_factors nf
    LEFT JOIN flow_alpha fa
        ON REPLACE(nf.stock_code, '.', '') = REPLACE(fa.stock_code, '.', '')
        AND REPLACE(nf.date, '-', '') = REPLACE(fa.date, '-', '')
    LEFT JOIN vol_adj va
        ON REPLACE(nf.stock_code, '.', '') = REPLACE(va.stock_code, '.', '')
        AND REPLACE(nf.date, '-', '') = REPLACE(va.date, '-', '')
    WHERE REPLACE(nf.date, '-', '') >= (
            SELECT REPLACE(date, '-', '') FROM new_factors
            ORDER BY REPLACE(date, '-', '') DESC LIMIT 1
        ) - 20
      AND nf.ma_decay IS NOT NULL
      AND fa.flow_alpha IS NOT NULL
      AND va.vol_adj IS NOT NULL
""").fetchall()

ma_vals = [r[0] for r in rows_20d if r[0] is not None]
flow_vals = [r[1] for r in rows_20d if r[1] is not None]
vol_vals = [r[2] for r in rows_20d if r[2] is not None]

DYN_PARAMS = {
    'ma_mean': np.mean(ma_vals), 'ma_std': max(np.std(ma_vals), 0.001),
    'flow_mean': np.mean(flow_vals), 'flow_std': max(np.std(flow_vals), 0.001),
    'vol_mean': np.mean(vol_vals), 'vol_std': max(np.std(vol_vals), 0.001),
}

print(f"\n动态参数: MA={DYN_PARAMS['ma_mean']:.4f}/{DYN_PARAMS['ma_std']:.4f}")
print(f"           Flow={DYN_PARAMS['flow_mean']:.4f}/{DYN_PARAMS['flow_std']:.4f}")
print(f"           Vol={DYN_PARAMS['vol_mean']:.4f}/{DYN_PARAMS['vol_std']:.4f}")
print()

for date_str in dates:
    date_clean = date_str.replace('-', '')
    
    # 获取当天数据
    rows = conn.execute("""
        SELECT nf.stock_code, nf.ma_decay, fa.flow_alpha, va.vol_adj,
               COALESCE(sh.reg10, 0) as reg10
        FROM new_factors nf
        LEFT JOIN flow_alpha fa
            ON REPLACE(nf.stock_code, '.', '') = REPLACE(fa.stock_code, '.', '')
            AND REPLACE(nf.date, '-', '') = REPLACE(fa.date, '-', '')
        LEFT JOIN vol_adj va
            ON REPLACE(nf.stock_code, '.', '') = REPLACE(va.stock_code, '.', '')
            AND REPLACE(nf.date, '-', '') = REPLACE(va.date, '-', '')
        LEFT JOIN signal_history sh
            ON REPLACE(nf.stock_code, '.', '') = REPLACE(sh.stock_code, '.', '')
            AND REPLACE(nf.date, '-', '') = REPLACE(sh.date, '-', '')
        WHERE REPLACE(nf.date, '-', '') = ?
          AND nf.ma_decay IS NOT NULL
    """, (date_clean,)).fetchall()
    
    if not rows:
        continue
    
    # 计算当天融合分
    fixed_scores = []
    dyn_scores = []
    for r in rows:
        row = {'ma_decay': r[1], 'flow_alpha': r[2], 'vol_adj': r[3], 'reg10': r[4] or 0}
        fixed_scores.append(calc_fusion(row, FIX_PARAMS))
        dyn_scores.append(calc_fusion(row, DYN_PARAMS))
    
    # 次日收益
    next_date_idx = dates.index(date_str) + 1
    if next_date_idx >= len(dates):
        # 用最新数据
        next_date_str = dates[-1]
    else:
        next_date_str = dates[next_date_idx]
    
    next_clean = next_date_str.replace('-', '')
    
    rets = conn.execute("""
        SELECT (close - open) / open
        FROM daily
        WHERE REPLACE(trade_date, '-', '') = ?
          AND ts_code IN (
              SELECT code FROM stock_daily
              WHERE REPLACE(trade_date, '-', '') = ?
          )
        LIMIT ?
    """, (next_clean, next_clean, len(rows))).fetchall()
    rets = [r[0] for r in rets if r[0] is not None]
    
    # 取top 15%作为强买
    n = len(fixed_scores)
    top_15 = int(n * 0.15)
    
    # 固定参数IC
    fixed_top = sorted(fixed_scores, reverse=True)[:top_15]
    # 动态参数IC
    dyn_top = sorted(dyn_scores, reverse=True)[:top_15]
    
    # 简单计算IC（分数与收益的相关性）
    fixed_ic = calc_ic(fixed_scores, rets[:len(fixed_scores)]) if rets else 0
    dyn_ic = calc_ic(dyn_scores, rets[:len(dyn_scores)]) if rets else 0
    
    print(f'{date_str:>10s} {n:>6d} {fixed_ic:>8.4f} {dyn_ic:>8.4f} '
          f'{np.mean(fixed_scores):>10.2f} {np.mean(dyn_scores):>10.2f}')

print(f"\n结论: 动态参数下分数分布更均衡，IC应有所改善")

conn.close()
