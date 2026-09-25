# -*- coding: utf-8 -*-
"""有效增益终检：B-A差序列自相关结构 + Newey-West校正t（标签重叠修正）"""
import pandas as pd, numpy as np
from scipy import stats

a = pd.read_csv('/Users/zantao/.hermes/stockdb/analysis/ab_intraday/daily_ic_roll_A.csv')
b = pd.read_csv('/Users/zantao/.hermes/stockdb/analysis/ab_intraday/daily_ic_roll_B.csv')
for _d in (a, b):
    _d['date'] = pd.to_datetime(_d['date'].astype(str), format='%Y%m%d')
j = pd.concat([a.set_index('date')['ic'].rename('A'),
               b.set_index('date')['ic'].rename('B')], axis=1).dropna().sort_index()
d = (j['B'] - j['A']).to_numpy()
n = len(d)
print(f"n={n}  mean B-A = {d.mean():+.4f}")

# 自相关函数
print("\nB-A差序列自相关（lag1~12）:")
for lag in range(1, 13):
    r = np.corrcoef(d[:-lag], d[lag:])[0, 1]
    print(f"  lag{lag}: {r:+.3f}", end='')
    if lag % 4 == 0: print()
print()

# Newey-West t（带宽h=10 对应10日标签重叠）
for h in (5, 10):
    x = d - d.mean()
    s = x @ x / n
    for l in range(1, h + 1):
        w = 1 - l / (h + 1)
        s += 2 * w * (x[l:] @ x[:-l]) / n
    t_nw = d.mean() / np.sqrt(s / n)
    p = 2 * (1 - stats.t.cdf(abs(t_nw), n - 1))
    print(f"Newey-West h={h}: t={t_nw:+.2f} p={p:.4f}")

# 有效样本量估计（AR(1)近似 n_eff = n(1-r)/(1+r)）
r1 = np.corrcoef(d[:-1], d[1:])[0, 1]
n_eff = n * (1 - max(r1, 0)) / (1 + max(r1, 0))
t_naive = d.mean() / (d.std(ddof=1) / np.sqrt(n))
t_eff = d.mean() / (d.std(ddof=1) / np.sqrt(max(n_eff, 2)))
print(f"\nlag1自相关 r1={r1:+.3f}  有效样本量(AR1)≈{n_eff:.0f}  保守t={t_eff:+.2f} "
      f"p={2*(1-stats.t.cdf(abs(t_eff), max(n_eff-1,1))):.4f}")

# 增益来源分解：涨/跌环境下的贡献占比
print(f"\nB-A 逐周符号: +{ (j.groupby(j.index.to_period('W')).apply(lambda g:(g['B']-g['A']).mean())>0).sum() }周为负{ (j.groupby(j.index.to_period('W')).apply(lambda g:(g['B']-g['A']).mean())<=0).sum() }周(共19周)")