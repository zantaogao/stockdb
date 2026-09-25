#!/usr/bin/env python3
"""1b 组合信号分月稳定性验证: 尾盘跌+开盘强 → 次日 2026-08-08
口径A: tail30 < -0.5% 且 open30 > 全样本中位数 (原验证口径)
口径B: tail30 < -0.5% 且 open30 > 0 (开盘上涨, 更宽松)
"""
import sqlite3, duckdb
import numpy as np
import pandas as pd
from scipy import stats

STATE = '/Users/zantao/.hermes/stockdb/state.db'
TUSHARE = '/Users/zantao/.hermes/stockdb/tushare.db'
s = sqlite3.connect(STATE)
t = duckdb.connect(TUSHARE, read_only=True)

feat = pd.read_sql("SELECT date, code, open30_ret, tail30_ret FROM tdx_intraday_feat", s)
tds = [str(r[0]) for r in t.execute("SELECT DISTINCT trade_date FROM daily WHERE trade_date >= '20260224' ORDER BY trade_date").fetchall()]
nx = {d: tds[i+1] for i, d in enumerate(tds[:-1])}
def c2t(c): return f"{c}.SH" if str(c).startswith(("6","68","9")) else f"{c}.SZ"
px = {}
for d, tc, cl in t.execute("SELECT trade_date, ts_code, close FROM daily WHERE trade_date >= '20260224'").fetchall():
    px.setdefault(str(d), {})[tc] = float(cl)

rows = []
for _, r in feat.iterrows():
    dd, nxt = str(r['date']), nx.get(str(r['date']))
    if not nxt: continue
    tc = c2t(r['code'])
    c0, c1 = px.get(dd, {}).get(tc), px.get(nxt, {}).get(tc)
    if not c0 or not c1 or c0 <= 0: continue
    rows.append((r['date'], (c1/c0-1)*100, r['open30_ret'], r['tail30_ret']))
df = pd.DataFrame(rows, columns=['date','ret','open30','tail30'])
df['month'] = df['date'].astype(str).str[:6]
med_open = df['open30'].median()

print(f"样本: {len(df)} 行, 全样本 open30 中位 = {med_open:+.4f}")
print(f"\n{'月份':<8} | {'口径A n':>7} {'次日均值':>8} {'中位':>7} {'涨占比':>7} {'t':>6} | {'口径B n':>7} {'次日均值':>8} {'中位':>7} {'涨占比':>7} {'t':>6}")
print("-" * 95)
for m in sorted(df['month'].unique()):
    sub = df[df['month'] == m]
    res = []
    for cond in [(sub['tail30'] < -0.005) & (sub['open30'] > med_open),
                 (sub['tail30'] < -0.005) & (sub['open30'] > 0)]:
        g = sub[cond]['ret']
        if len(g) >= 50:
            tstat, p = stats.ttest_1samp(g, 0)
            res.append(f"{len(g):>7} {g.mean():>+8.2f} {g.median():>+7.2f} {np.mean(g>0):>7.1%} {tstat:>+6.1f}")
        else:
            res.append(f"{len(g):>7} {'—':>8}")
    print(f"{m:<8} | {res[0]} | {res[1]}")
print("-" * 95)
# 全期
for label, cond in [("口径A(尾盘跌+开盘>中位)", (df['tail30'] < -0.005) & (df['open30'] > med_open)),
                    ("口径B(尾盘跌+开盘>0)", (df['tail30'] < -0.005) & (df['open30'] > 0))]:
    g = df[cond]['ret']
    tstat, p = stats.ttest_1samp(g, 0)
    print(f"全期 {label}: n={len(g)} 均值 {g.mean():+.2f}% 中位 {g.median():+.2f}% 涨占比 {np.mean(g>0):.1%} t={tstat:+.1f} p={p:.2e}")
s.close(); t.close()
