#!/usr/bin/env python3
"""09-10 权重调整测试：把 reg10 纳入融合权重的网格搜索（用户拍板"测试把10d安排上"）。

口径（与 09-06 特种钢实验/matlab 移植回测对齐）：
- 信号日 = signal_history 三列齐全 且 次日收益成熟
- 收益 = 次日close/信号日close-1（ic_daily 同口径），逐日 Pearson IC
- 单位纪律：reg10=小数×100 化百分点；reg20/reg40 原生百分点；加权前先打印各列 std 核单位
- 基线 = 当日存的 fusion_score（生产 0.7*reg40+0.3*reg20 线性原始分）
- 网格 = (W10,W20,W40) 步长10%，W10∈{0..0.6}；权重×原始百分点直接线性
- 检验 = 每格逐日IC均值/IR/胜率 + 与基线逐日差的 NW-t(lag=5)
- 注意：网格挑冠军是 in-sample 选择，报告同时给 expanding-OLS 无前视对照
"""
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
print("候选信号日:", len(sig_days), sig_days[0], "~", sig_days[-1])

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

def nw_t(x, lag=5):
    x = np.asarray(x, float); n = len(x)
    if n < 8: return np.nan
    mu = x.mean(); e = x - mu
    s = (e @ e) / n
    for l in range(1, lag + 1):
        s += 2 * (1 - l / (lag + 1)) * ((e[l:] @ e[:-l]) / n)
    return mu / np.sqrt(s / n) if s > 0 else np.nan

days = []
unit_logged = False
for d in sig_days:
    df = pd.read_sql("SELECT stock_code, reg10, reg20, reg40, fusion_score FROM signal_history WHERE REPLACE(date,'-','')=?",
                     st, params=(d,))
    df['ts'] = df['stock_code'].map(code_to_ts)
    if d not in pxw.index: continue
    nxt_idx = dates.index(d) + 1
    if nxt_idx >= len(dates): continue
    fwd_ser = next_ret.loc[d]
    fwd = pd.DataFrame({'ts': np.asarray(fwd_ser.index, dtype=str), 'fwd': fwd_ser.to_numpy(float)})
    m = df.merge(fwd, left_on='ts', right_on='ts', how='inner')
    m = m.dropna(subset=['fwd','reg10','reg20','reg40','fusion_score'])
    if len(m) < 1000: continue
    # 单位换算：reg10 小数×100
    r10 = m['reg10'].to_numpy(float) * 100.0
    r20 = m['reg20'].to_numpy(float)
    r40 = m['reg40'].to_numpy(float)
    if not unit_logged:
        print(f"单位核验 {d}: std reg10×100={r10.std():.3f} reg20={r20.std():.3f} reg40={r40.std():.3f}")
        unit_logged = True
    days.append(dict(date=d, R=np.column_stack([r10, r20, r40]),
                     fwd=m['fwd'].to_numpy(float),
                     base=m['fusion_score'].to_numpy(float)))
st.close()
print("成熟信号日:", len(days), days[0]['date'], "~", days[-1]['date'])

# 逐列单日IC均值（先回答10d到底有没有信息）
for j, nm in enumerate(['reg10×100','reg20','reg40']):
    ics = [np.corrcoef(d['R'][:,j], d['fwd'])[0,1] for d in days]
    ics = np.array(ics)
    print(f"{nm}: 日均IC={ics.mean():.4f} IR={ics.mean()/(ics.std()+1e-12):.3f} NW-t={nw_t(ics):.2f}")

# 网格
grid = []
for w10 in [0, .1, .2, .3, .4, .5, .6]:
    for w20 in [0, .1, .2, .3, .4, .5, .6, .7, .8, .9, 1.0]:
        w40 = 1 - w10 - w20
        if w40 < -1e-9 or w40 > 1 + 1e-9: continue
        grid.append((round(w10,1), round(w20,1), round(w40,1)))
ics_base = np.array([np.corrcoef(d['base'], d['fwd'])[0,1] for d in days])
print(f"\n基线(生产fusion): 均值IC={ics_base.mean():.4f} IR={ics_base.mean()/(ics_base.std()+1e-12):.3f} 胜率={(ics_base>0).mean():.0%}")
rows = []
for (w10, w20, w40) in grid:
    ics = np.array([np.corrcoef(d['R'] @ np.array([w10,w20,w40]), d['fwd'])[0,1] for d in days])
    dif = ics - ics_base
    rows.append(dict(w10=w10, w20=w20, w40=w40, ic=ics.mean(),
                     ir=ics.mean()/(ics.std()+1e-12), win=(ics>0).mean(),
                     diff=dif.mean(), nwt=nw_t(dif)))
g = pd.DataFrame(rows).sort_values('ic', ascending=False)
pd.set_option('display.float_format', lambda v: f"{v:.4f}")
print("\n=== 网格(按均值IC排序, 全部) ===")
print(g.to_string(index=False))
best = g.iloc[0]
print(f"\n冠军 {best.w10:.0%}/{best.w20:.0%}/{best.w40:.0%}: IC={best['ic']:.4f} 差基线={best['diff']:+.4f} NW-t={best.nwt:.2f}")

# 10d权重的边际曲线：固定 40/20→70/30 骨架，逐步从reg40挪给reg10
print("\n=== 边际曲线: 骨架0.3*reg20 + (0.7-x)*reg40 + x*reg10 ===")
for x in [0,.05,.1,.15,.2,.25,.3]:
    w = np.array([x, .3, .7-x])
    ics = np.array([np.corrcoef(d['R'] @ w, d['fwd'])[0,1] for d in days])
    dif = ics - ics_base
    print(f"x={x:.2f}: IC={ics.mean():.4f} 差={dif.mean():+.4f} NW-t={nw_t(dif):.2f}")

# expanding-OLS 无前视对照（堆叠回归, 只用早于d的成熟日）
print("\n=== expanding OLS 拟合权重(无前视) 逐日 ===")
fit_ics, fit_w = [], []
for t in range(len(days)):
    if t >= 10:
        X = np.vstack([d['R'] for d in days[:t]]); y = np.concatenate([d['fwd'] for d in days[:t]])
        w = np.linalg.lstsq(X, y, rcond=None)[0]
        wsum = w.sum(); w = w / wsum if wsum > 0 else np.array([0.,.3,.7])
    else:
        w = np.array([0.,.3,.7])
    ic = np.corrcoef(days[t]['R'] @ w, days[t]['fwd'])[0,1]
    fit_ics.append(ic); fit_w.append(w)
fit_ics = np.array(fit_ics); dif = fit_ics - ics_base
print(f"OLS权重均值: reg10={np.mean([w[0] for w in fit_w[10:]]):.3f} reg20={np.mean([w[1] for w in fit_w[10:]]):.3f} reg40={np.mean([w[2] for w in fit_w[10:]]):.3f}")
print(f"expanding-OLS: 均值IC={fit_ics.mean():.4f} 差基线={dif.mean():+.4f} NW-t={nw_t(dif):.2f}")

pd.DataFrame([dict(date=d['date'], ic_base=ic_b, ic_base2=ic_b) for d, ic_b in zip(days, ics_base)]).to_csv(
    '/Users/zantao/.hermes/stockdb/reports/weight_grid_10d_0910.csv', index=False)
g.to_csv('/Users/zantao/.hermes/stockdb/reports/weight_grid_10d_0910_grid.csv', index=False)
print("\n网格明细已存 reports/weight_grid_10d_0910_grid.csv")
