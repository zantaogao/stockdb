# -*- coding: utf-8 -*-
"""A/B 验证集逐日IC 配对t检验 + 分月拆解（用户要求：分环境，不接受混合平均）"""
import pandas as pd, numpy as np
from scipy import stats

a = pd.read_csv('daily_ic_A_base.csv', parse_dates=['date']).set_index('date')['ic']
b = pd.read_csv('daily_ic_B_intraday.csv', parse_dates=['date']).set_index('date')['ic']
j = pd.concat([a.rename('A'), b.rename('B')], axis=1).dropna()
d = j['B'] - j['A']
print(f"验证日数 n={len(j)}  区间 {j.index.min():%m-%d}~{j.index.max():%m-%d}")
print(f"A mean IC {j['A'].mean():+.4f} (t={j['A'].mean()/(j['A'].std(ddof=1)/np.sqrt(len(j))):+.2f})")
print(f"B mean IC {j['B'].mean():+.4f} (t={j['B'].mean()/(j['B'].std(ddof=1)/np.sqrt(len(j))):+.2f})")
t, p = stats.ttest_1samp(d, 0)
print(f"配对差 B-A: mean {d.mean():+.4f}  t={t:+.2f}  p={p:.4f}")
w = stats.wilcoxon(d)
print(f"Wilcoxon符号秩: stat={w.statistic:.1f} p={w.pvalue:.4f}")
j['ym'] = j.index.to_period('M')
print("\n分月（日均IC）:")
print(j.groupby('ym')[['A','B']].mean().round(4))
gd = j.groupby('ym').apply(lambda g: (g['B']-g['A']).mean(), include_groups=False)
print("分月 B-A:", gd.round(4).to_dict())
print(f"\nB跑赢A的天数: {(d>0).sum()}/{len(d)}")