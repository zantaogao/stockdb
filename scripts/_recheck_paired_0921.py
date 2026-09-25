# -*- coding: utf-8 -*-
"""复检②：从修正后 CSV 复算 17 年均值/NW-t/正年数/配对(vs 40/40/20)，核对上轮报告的表格数字"""
import glob, os
import numpy as np, pandas as pd
HOME = os.path.expanduser('~')
d = pd.concat([pd.read_csv(f) for f in sorted(glob.glob(f'{HOME}/.hermes/stockdb/analysis/cmmr_grid_days/*.csv'))],
              ignore_index=True)
d['date'] = d['date'].astype(int)
d['ex'] = d.ex * 100
cur = d[d.w == '40/40/20'].set_index('date').ex
def nw_t(v, lag=10):
    v = np.asarray(v, float); nn = len(v); m = v.mean(); e = v - m
    g = sum(np.cov(e[j:], e[:-j], ddof=1)[0, 1] * (1 - j / (lag + 1)) for j in range(1, lag + 1))
    return m / np.sqrt((np.var(v, ddof=1) + 2 * g) / nn) if (np.var(v, ddof=1) + 2 * g) > 0 else float('nan')
print(f"{'权重':<10}{'日均ex':>8}{'t':>7}{'正年':>6}{'赢年vs现行':>10}{'配对t':>8}")
for w in ['40/40/20', '40/20/40', '20/40/40', '20/50/30', '0/50/50', '0/100/0']:
    s = d[d.w == w].groupby('date').ex.mean()
    yr = s.groupby(s.index // 10000).mean()
    cur_yr = cur.groupby(cur.index // 10000).mean()
    j = pd.DataFrame({'a': s, 'b': cur}).dropna()
    dif = j.a - j.b
    wy = (yr.reindex(cur_yr.index) > cur_yr).sum()
    print(f"{w:<10}{s.mean():>+8.3f}{nw_t(s.values):>7.2f}{(yr>0).sum():>4}/18{wy:>8}/18{nw_t(dif.values):>+8.2f}")
