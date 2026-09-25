#!/usr/bin/env python3
"""09-10 权重网格 z 标准化版：三路预测各自日截面z后加权，剥离幅值干扰。
与原始单位版(脚本 _weight_grid_10d_0910.py)对照，回答'10d提权'是真信号还是幅值假象。"""
import sqlite3, sys
import numpy as np
import pandas as pd
sys.path.insert(0, '/Users/zantao/.hermes/stockdb')
from core.db import TUSHARE_DB_PATH, _safe_connect

con = _safe_connect(TUSHARE_DB_PATH, read_only=True)
st = sqlite3.connect('/Users/zantao/.hermes/stockdb/signals.db')
sig_days = [r[0] for r in st.execute(
    "SELECT DISTINCT REPLACE(date,'-','') FROM signal_history "
    "WHERE reg10 IS NOT NULL AND reg20 IS NOT NULL AND reg40 IS NOT NULL "
    "AND fusion_score IS NOT NULL ORDER BY 1").fetchall()]
lo, hi = sig_days[0], sig_days[-1]
px = con.execute(f'''
    SELECT ts_code, trade_date, close FROM daily
    WHERE trade_date BETWEEN '{lo}' AND COALESCE((SELECT MIN(trade_date) FROM daily WHERE trade_date > '{hi}'), '{hi}')
      AND (ts_code LIKE '%.SZ' OR ts_code LIKE '%.SH')
''').df()
con.close()
pxw = px.pivot(index='trade_date', columns='ts_code', values='close').sort_index()
pxw.index = pxw.index.astype(str)
dates = list(pxw.index)
next_ret = pxw.shift(-1) / pxw - 1

def code_to_ts(c):
    c = str(c)
    return c + '.SH' if c.startswith(('600','601','602','603','604','605','688','9')) else c + '.SZ'

def nw_t(x, lag=10):
    x = np.asarray(x, float); n = len(x)
    if n < 8: return np.nan
    mu = x.mean(); e = x - mu
    s = (e @ e) / n
    for l in range(1, lag + 1):
        s += 2 * (1 - l / (lag + 1)) * ((e[l:] @ e[:-l]) / n)
    return mu / np.sqrt(s / n) if s > 0 else np.nan

days = []
for d in sig_days:
    df = pd.read_sql("SELECT stock_code, reg10, reg20, reg40, fusion_score FROM signal_history WHERE REPLACE(date,'-','')=?",
                     st, params=(d,))
    df['ts'] = df['stock_code'].map(code_to_ts)
    if d not in pxw.index: continue
    nxt = dates.index(d) + 1
    if nxt >= len(dates): continue
    fwd_ser = next_ret.loc[d]
    fwd = pd.DataFrame({'ts': np.asarray(fwd_ser.index, dtype=str), 'fwd': fwd_ser.to_numpy(float)})
    m = df.merge(fwd, left_on='ts', right_on='ts', how='inner')
    m = m.dropna(subset=['fwd','reg10','reg20','reg40','fusion_score'])
    if len(m) < 1000: continue
    R = m[['reg10','reg20','reg40']].to_numpy(float)
    Rz = (R - R.mean(0)) / (R.std(0) + 1e-12)
    days.append(dict(date=d, Rz=Rz, fwd=m['fwd'].to_numpy(float), base=m['fusion_score'].to_numpy(float)))
st.close()
print("成熟信号日:", len(days))

ics_base = np.array([np.corrcoef(d['base'], d['fwd'])[0,1] for d in days])
print(f"基线(生产fusion): 均值IC={ics_base.mean():.4f} NW-t(lag10)={nw_t(ics_base):.2f}")

grid = []
for w10 in [0,.1,.2,.3,.4,.5,.6,.7]:
    for w20 in [0,.1,.2,.3,.4,.5,.6,.7,.8,.9,1.0]:
        w40 = 1 - w10 - w20
        if w40 < -1e-9 or w40 > 1+1e-9: continue
        grid.append((round(w10,1), round(w20,1), round(w40,1)))
rows = []
for (w10,w20,w40) in grid:
    w = np.array([w10,w20,w40])
    ics = np.array([np.corrcoef(d['Rz'] @ w, d['fwd'])[0,1] for d in days])
    dif = ics - ics_base
    rows.append(dict(w10=w10,w20=w20,w40=w40,ic=ics.mean(),
                     ir=ics.mean()/(ics.std()+1e-12), win=(ics>0).mean(),
                     diff=dif.mean(), nwt=nw_t(dif)))
g = pd.DataFrame(rows).sort_values('ic', ascending=False)
pd.set_option('display.float_format', lambda v: f"{v:.4f}")
print("\n=== z版网格 TOP15 ===")
print(g.head(15).to_string(index=False))
print("\n=== z版: 0.7*reg40骨架让位x给reg10 (0.3reg20+(0.7-x)reg40+x*reg10) ===")
for x in [0,.1,.2,.3,.4]:
    w = np.array([x,.3,.7-x])
    ics = np.array([np.corrcoef(d['Rz'] @ w, d['fwd'])[0,1] for d in days])
    dif = ics - ics_base
    print(f"x={x:.1f}: IC={ics.mean():.4f} 差={dif.mean():+.4f} NW-t(lag10)={nw_t(dif):.2f}")
print("\n=== z版442(生产同构 w=.4/.4/.2) 与 433 ===")
for w in [(0.4,0.4,0.2),(0.4,0.3,0.3),(0.5,0.2,0.3),(0.3,0.3,0.4)]:
    w = np.array(w)
    ics = np.array([np.corrcoef(d['Rz'] @ w, d['fwd'])[0,1] for d in days])
    dif = ics - ics_base
    print(f"{w}: IC={ics.mean():.4f} 差={dif.mean():+.4f} NW-t(lag10)={nw_t(dif):.2f}")
g.to_csv('/Users/zantao/.hermes/stockdb/reports/weight_grid_10d_z_0910.csv', index=False)
print("\n已存 reports/weight_grid_10d_z_0910.csv")
