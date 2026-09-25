# -*- coding: utf-8 -*-
"""CMMR 权重网格汇总：读 analysis/cmmr_grid_days/*.csv 逐年+全期 NW-t 排名"""
import glob, os
import numpy as np, pandas as pd
HOME = os.path.expanduser('~')
BASE = f'{HOME}/.hermes/stockdb/analysis/cmmr_grid_days'
d = pd.concat([pd.read_csv(f) for f in sorted(glob.glob(BASE+'/*.csv'))])
print('总明细行', len(d), '年份', sorted(d.year.unique()))

def nw_t(v, lag=10):
    v = np.asarray(v); n = len(v)
    if n < 30: return np.nan
    m = v.mean(); e = v - m
    g = sum(np.cov(e[j:], e[:-j], ddof=1)[0,1]*(1-j/(lag+1)) for j in range(1, lag+1))
    return m/np.sqrt((np.var(v, ddof=1)+2*g)/n)

rows=[]
for w, g in d.groupby('w'):
    g = g.sort_values('date')
    ex = g.ex.values*100
    yr = {}
    for y, gy in g.groupby('year'):
        if len(gy) >= 30: yr[int(y)] = round(float(gy.ex.mean()*100), 2)
    pos = sum(1 for v in yr.values() if v > 0)
    rows.append(dict(w=w, days=len(g), pool=int(g.pool_n.mean()),
        ex=round(float(ex.mean()),3), t_all=round(float(nw_t(ex)),2),
        win=round(float((ex>0).mean()),3), pos_yr=f'{pos}/{len(yr)}',
        worst_yr=min(yr.values()), best_yr=max(yr.values()), years=yr))
res = pd.DataFrame(rows).sort_values('t_all', ascending=False)
res.drop(columns=['years']).to_csv(f'{HOME}/.hermes/stockdb/analysis/cmmr_weight_grid_17y_0920.csv', index=False)
pd.set_option('display.width', 250)
print(res.drop(columns=['years']).head(15).to_string(index=False))
print()
print('=== 关键组 ===')
for k_ in ['40/40/20','40/20/40','20/40/40','30/40/30','50/30/20','25/50/25','0/50/50','0/100/0']:
    sub = res[res.w == k_]
    if len(sub):
        r = sub.iloc[0]
        print(f"{k_:<10} 池均{r.pool:<4} 日均超{r.ex:+.3f}pp t={r.t_all:+.2f} 胜率{r.win:.0%} 正年{r.pos_yr} 最差年{r.worst_yr:+.2f}")
        print(f"           分年: {r.years}")
