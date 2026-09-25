# -*- coding: utf-8 -*-
"""滚动窗 A/B：90 验证日配对t检验 + 分月/分折拆解"""
import pandas as pd, numpy as np, json
from scipy import stats

a = pd.read_csv('daily_ic_roll_A.csv', parse_dates=['date']).set_index('date')['ic']
b = pd.read_csv('daily_ic_roll_B.csv', parse_dates=['date']).set_index('date')['ic']
j = pd.concat([a.rename('A'), b.rename('B')], axis=1).dropna()
d = j['B'] - j['A']
n = len(j)
print(f"验证日数 n={n}  区间 {j.index.min():%m-%d}~{j.index.max():%m-%d}")
print(f"A mean IC {j['A'].mean():+.4f} (t={j['A'].mean()/(j['A'].std(ddof=1)/np.sqrt(n)):+.2f})")
print(f"B mean IC {j['B'].mean():+.4f} (t={j['B'].mean()/(j['B'].std(ddof=1)/np.sqrt(n)):+.2f})")
t, p = stats.ttest_1samp(d, 0)
print(f"配对差 B-A: mean {d.mean():+.4f}  t={t:+.2f}  p={p:.4f}")
w = stats.wilcoxon(d)
print(f"Wilcoxon: stat={w.statistic:.1f} p={w.pvalue:.4f}")
print(f"B跑赢天数: {(d>0).sum()}/{n} = {(d>0).mean()*100:.0f}%")
j['ym'] = j.index.to_period('M')
g = j.groupby('ym').agg(A=('A','mean'), B=('B','mean'), days=('A','size'),
                        win=('A', lambda x: 0))
g['B-A'] = g['B'] - g['A']
g['win_rate'] = j.groupby('ym').apply(lambda x: (x['B']>x['A']).mean(), include_groups=False)
print("\n分月:")
print(g[['A','B','B-A','days','win_rate']].round(4))
# 95% CI of paired diff
ci = stats.t.interval(0.95, n-1, loc=d.mean(), scale=stats.sem(d))
print(f"\nB-A 95%CI [{ci[0]:+.4f}, {ci[1]:+.4f}]")