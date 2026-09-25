#!/usr/bin/env python3
"""新维度验证: 尾盘量占比判别器 + 隔夜跳空 2026-08-08"""
import sqlite3, duckdb
import numpy as np
import pandas as pd

STATE = '/Users/zantao/.hermes/stockdb/state.db'
TUSHARE = '/Users/zantao/.hermes/stockdb/tushare.db'
s = sqlite3.connect(STATE)
t = duckdb.connect(TUSHARE, read_only=True)

feat = pd.read_sql("SELECT date, code, open30_ret, tail30_ret, vwap_dev, vol_dist_am, vol_dist_tail FROM tdx_intraday_feat", s)
tds = [str(r[0]) for r in t.execute("SELECT DISTINCT trade_date FROM daily WHERE trade_date >= '20260212' ORDER BY trade_date").fetchall()]
nx = {d: tds[i+1] for i, d in enumerate(tds[:-1])}
def c2t(c): return f"{c}.SH" if str(c).startswith(("6","68","9")) else f"{c}.SZ"
px = {}
for d, tc, cl in t.execute("SELECT trade_date, ts_code, close FROM daily WHERE trade_date >= '20260212'").fetchall():
    px.setdefault(str(d), {})[tc] = float(cl)
# 开盘价 + pre_close（隔夜跳空）
opn = {}
for d, tc, op, pc in t.execute("SELECT trade_date, ts_code, open, pre_close FROM daily WHERE trade_date >= '20260212'").fetchall():
    opn.setdefault(str(d), {})[tc] = (float(op), float(pc))

rows = []
for _, r in feat.iterrows():
    dd, nxt = str(r['date']), nx.get(str(r['date']))
    tc = c2t(r['code'])
    c0, c1 = (px.get(dd, {}).get(tc), px.get(nxt, {}).get(tc)) if nxt else (None, None)
    ret = (c1/c0-1)*100 if c0 and c1 and c0 > 0 else None
    gap = None
    od = opn.get(dd, {}).get(tc)
    if od and od[1] and od[1] > 0:
        gap = (od[0]/od[1] - 1)*100
    rows.append((r['date'], r['tail30_ret'], r['vwap_dev'], r['vol_dist_am'], r['vol_dist_tail'], ret, gap))
df = pd.DataFrame(rows, columns=['date','tail30','vwap','voldist_am','voldist_tail','ret','gap'])
df = df.dropna(subset=['ret'])
print(f"样本: {len(df)}")

def rep(label, m, base=None):
    g = df[m]['ret']
    if len(g) < 200: print(f"  {label}: n={len(g)} 不足"); return
    b = base if base is not None else 0
    print(f"  {label}: n={len(g):>7} 次日均值 {g.mean():>+6.2f}% 中位 {g.median():>+6.2f}% 涨占比 {np.mean(g>0):.1%}")

print("\n【A1: 尾盘量占比 × 急拉 —— 第二个判别器】")
t_hi = df['voldist_tail'].quantile(0.75)
t_lo = df['voldist_tail'].quantile(0.25)
# 急拉(>1.5%)中: 放量 vs 缩量
rep("急拉+尾盘放量(>P75)", (df['tail30']>0.015)&(df['voldist_tail']>t_hi))
rep("急拉+尾盘缩量(<P25)", (df['tail30']>0.015)&(df['voldist_tail']<t_lo))
rep("急拉+VWAP正偏+放量", (df['tail30']>0.015)&(df['vwap']>0)&(df['voldist_tail']>t_hi))
print("  —— 低吸端: 尾盘下跌是放量(恐慌)还是缩量(惜售)? ——")
rep("尾盘跌+放量(恐慌抛售)", (df['tail30']<-0.005)&(df['voldist_tail']>t_hi))
rep("尾盘跌+缩量(惜售/洗盘)", (df['tail30']<-0.005)&(df['voldist_tail']<t_lo))

print("\n【B2: 隔夜跳空 gap → 次日】(A股经典: 隔夜强+日内弱)")
df['gap'] = pd.to_numeric(df['gap'], errors='coerce')
dfg = df.dropna(subset=['gap'])
g_hi = dfg['gap'].quantile(0.9)
g_lo = dfg['gap'].quantile(0.1)
rep("大幅高开(>P90)", dfg['gap']>g_hi)
rep("大幅低开(<P10)", dfg['gap']<g_lo)
rep("平开", (dfg['gap']>-0.5)&(dfg['gap']<0.5))
# gap 与当日 tail30 关系
g1 = dfg[dfg['gap']>g_hi]['tail30'].mean()
g2 = dfg[dfg['gap']<g_lo]['tail30'].mean()
print(f"  高开组当日tail30 {g1:+.4f} vs 低开组 {g2:+.4f} (高开当日尾盘?)")
# 高开+尾盘涨 → 次日（双重强）
rep("高开+尾盘涨(强强)", (dfg['gap']>g_hi)&(dfg['tail30']>0.005))
rep("低开+尾盘涨(弱转强)", (dfg['gap']<g_lo)&(dfg['tail30']>0.005))
s.close(); t.close()
