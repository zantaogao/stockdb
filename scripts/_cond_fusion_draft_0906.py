#!/usr/bin/env python3
"""09-06 特种钢实验（草案）：按市场波动分档的条件权重融合 vs 现行冻结 70/30。

方法（无前视）：
- 信号日 = signal_history 有完整 reg10/20/40 且次日收益已成熟的交易日
- 收益 = 次日close/信号日close - 1（与 ic_daily 同口径，Pearson IC 逐日）
- 基线 = 当日存储的 fusion_score（现行 0.7*reg40+0.3*reg20 产线口径）
- 工况变量 = 全市场当日截面收益率std（信号日收盘可得，无前视）
- 分档 = expanding 三分位：只用 d 之前已成熟日的工况分布给 d 定档（无前视）
- 条件权重 = 对与 d 同档、且成熟日早于 d 的历史日做 OLS(w on 日内z分 reg10/20/40)；
  同档样本 < 8 天时回退全局 expanding OLS，再不足回退现行 70/30
- 对照 = 全局 expanding OLS（不分档），分离"分档"与"只是重拟合"的贡献
- 检验 = 逐日 IC 差（条件-基线）的 Newey-West t（lag=5）
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

# 一次拉全窗口日线 close（约5000票×70日）
lo, hi = sig_days[0], sig_days[-1]
px = con.execute(f'''
    SELECT ts_code, trade_date, close FROM daily
    WHERE trade_date BETWEEN '{lo}' AND COALESCE((SELECT MIN(trade_date) FROM daily WHERE trade_date > '{hi}'), '{hi}')
      AND (ts_code LIKE '%.SZ' OR ts_code LIKE '%.SH')
''').df()
con.close()
pxw = px.pivot(index='trade_date', columns='ts_code', values='close').sort_index()
pxw.index = pxw.index.astype(str)   # trade_date 可能是整数，统一字符串
dates = list(pxw.index)
ret = pxw.pct_change()          # 当日收益（截面std用）
next_ret = pxw.shift(-1) / pxw - 1   # d -> d+1 收益

def code_to_ts(c):
    c = str(c)
    return c + '.SH' if c.startswith(('600','601','602','603','604','605','688','9')) else c + '.SZ'

def nw_t(x, lag=5):
    x = np.asarray(x, float); n = len(x)
    if n < 8: return np.nan
    mu = x.mean()
    e = x - mu
    g0 = (e @ e) / n
    s = g0
    for l in range(1, lag + 1):
        c = (e[l:] @ e[:-l]) / n
        s += 2 * (1 - l / (lag + 1)) * c
    return mu / np.sqrt(s / n) if s > 0 else np.nan

def fit_w(days_data, idx_list):
    """在同档历史日集合上 OLS（日内z分后堆叠）. 返回 (w10,w20,w40) 或 None"""
    Xs, ys = [], []
    for i in idx_list:
        regs = days_data[i]['regs']; fwd = days_data[i]['fwd']
        Xs.append(regs); ys.append(fwd)
    X = np.vstack(Xs); y = np.concatenate(ys)
    w = np.linalg.lstsq(X, y, rcond=None)[0]
    return w

# 组装逐日矩阵
days = []   # (date, regs_z[N,3] (10,20,40), fwd[N], baseline[N], mkt_std)
for d in sig_days:
    df = pd.read_sql("SELECT stock_code, reg10, reg20, reg40, fusion_score FROM signal_history WHERE REPLACE(date,'-','')=?",
                     st, params=(d,))   # date列混有带横杠/无横杠两种格式，统一REPLACE查
    df['ts'] = df['stock_code'].map(code_to_ts)
    if d not in pxw.index:
        print('SKIP-notidx', d); continue
    nxt_idx = dates.index(d) + 1
    if nxt_idx >= len(dates): continue   # 次日收益未成熟
    nd = dates[nxt_idx]
    fwd_ser = next_ret.loc[d]
    fwd = pd.DataFrame({'ts': np.asarray(fwd_ser.index, dtype=str), 'fwd': fwd_ser.to_numpy(float)})
    m = df.merge(fwd, left_on='ts', right_on='ts', how='inner')
    m = m.dropna(subset=['fwd','reg10','reg20','reg40','fusion_score'])
    if len(m) < 1000:
        print('SKIP', d, 'merge后', len(m), 'df', len(df)); continue
    R = m[['reg10','reg20','reg40']].to_numpy(float)
    Rz = (R - R.mean(0)) / (R.std(0) + 1e-12)
    days.append(dict(date=d, regs=Rz, fwd=m['fwd'].to_numpy(float),
                     base=m['fusion_score'].to_numpy(float),
                     std=ret.loc[d].std()))
st.close()
print("成熟信号日:", len(days), days[0]['date'], "~", days[-1]['date'])

# 逐日 IC
res = []
mature_std = [x['std'] for x in days]
for t in range(len(days)):
    d = days[t]
    ic_base = np.corrcoef(d['base'], d['fwd'])[0,1]
    # expanding 分位阈值（只用 t 之前的日）
    if t >= 6:
        hist = np.array(mature_std[:t])
        q = np.quantile(hist, [1/3, 2/3])
        regime = 0 if d['std'] <= q[0] else (1 if d['std'] <= q[1] else 2)
    else:
        regime = -1
    # 同档历史日（成熟收益早于 d）
    same = [i for i in range(t) if days[i].get('regime_eff') == regime and regime >= 0]
    # regime_eff: 给历史日也按其当时可得的 expanding 分位定档（避免前视）
    if t >= 6:
        days[t]['regime_eff'] = regime
    if len(same) >= 8:
        w_cond = fit_w(days, same)
    elif t >= 15:
        w_cond = fit_w(days, list(range(t)))     # 全局 expanding
    else:
        w_cond = np.array([0.0, 0.3, 0.7])
    cond = d['regs'] @ w_cond
    ic_cond = np.corrcoef(cond, d['fwd'])[0,1]
    gl = fit_w(days, list(range(t))) if t >= 15 else np.array([0.0,0.3,0.7])
    ic_glob = np.corrcoef(d['regs'] @ gl, d['fwd'])[0,1] if t >= 15 else ic_base
    res.append(dict(date=d['date'], regime=regime, std=d['std'],
                    w=','.join(f"{v:.2f}" for v in w_cond),
                    ic_base=ic_base, ic_cond=ic_cond, ic_glob=ic_glob))

df = pd.DataFrame(res).dropna(subset=['ic_base'])
print(df.to_string(index=False, float_format=lambda v: f"{v:.4f}"))
n = len(df)
print(f"\n样本成熟日 n={n}")
for label in ['ic_base','ic_cond','ic_glob']:
    s = df[label].dropna()
    print(f"{label}: 均值IC={s.mean():.4f} IR={s.mean()/(s.std()+1e-12):.3f} 胜率>0={ (s>0).mean():.0%} NW-t(均值)={nw_t(s):.2f}")
dif = (df['ic_cond'] - df['ic_base']).dropna()
print(f"差(条件-基线): 均值={dif.mean():.4f} NW-t={nw_t(dif):.2f}")
dif2 = (df['ic_glob'] - df['ic_base']).dropna()
print(f"差(全局重拟合-基线): 均值={dif2.mean():.4f} NW-t={nw_t(dif2):.2f}")
print("\n按档拆解(条件-基线 逐档IC均值):")
for r in [0,1,2]:
    sub = df[df['regime']==r]
    if len(sub):
        print(f"  档{r}({'低' if r==0 else '中' if r==1 else '高'}波动) n={len(sub)}: base={sub.ic_base.mean():.4f} cond={sub.ic_cond.mean():.4f} 差={ (sub.ic_cond-sub.ic_base).mean():.4f}")
        print(f"    近期权重样例: {sub['w'].tolist()[-3:]}")
df.to_csv('/Users/zantao/.hermes/stockdb/reports/cond_fusion_0906.csv', index=False)
print("\n明细已存 reports/cond_fusion_0906.csv")