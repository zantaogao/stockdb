#!/usr/bin/env python3
"""急拉×VWAP 交互: VWAP正偏是否加强急拉负信号 2026-08-08"""
import sqlite3, duckdb
import numpy as np
import pandas as pd

STATE = '/Users/zantao/.hermes/stockdb/state.db'
TUSHARE = '/Users/zantao/.hermes/stockdb/tushare.db'
s = sqlite3.connect(STATE)
t = duckdb.connect(TUSHARE, read_only=True)
feat = pd.read_sql("SELECT date, code, tail30_ret, vwap_dev FROM tdx_intraday_feat", s)
tds = [str(r[0]) for r in t.execute("SELECT DISTINCT trade_date FROM daily WHERE trade_date >= '20260212' ORDER BY trade_date").fetchall()]
nx = {d: tds[i+1] for i, d in enumerate(tds[:-1])}
def c2t(c): return f"{c}.SH" if str(c).startswith(("6","68","9")) else f"{c}.SZ"
px = {}
for d, tc, cl in t.execute("SELECT trade_date, ts_code, close FROM daily WHERE trade_date >= '20260212'").fetchall():
    px.setdefault(str(d), {})[tc] = float(cl)
rows = []
for _, r in feat.iterrows():
    dd, nxt = str(r['date']), nx.get(str(r['date']))
    tc = c2t(r['code'])
    c0, c1 = (px.get(dd, {}).get(tc), px.get(nxt, {}).get(tc)) if nxt else (None, None)
    ret = (c1/c0-1)*100 if c0 and c1 and c0 > 0 else None
    if ret is not None:
        rows.append((r['tail30_ret'], r['vwap_dev'], ret))
df = pd.DataFrame(rows, columns=['tail30','vwap','ret'])
print(f"样本: {len(df)}")

print(f"\n{'分组':<34} {'n':>8} {'次日均值':>9} {'中位':>8} {'涨占比':>7}")
groups = [
    ("急拉>1.5% 且 VWAP正偏", (df['tail30']>0.015)&(df['vwap']>0)),
    ("急拉>1.5% 且 VWAP非正偏", (df['tail30']>0.015)&(df['vwap']<=0)),
    ("急拉1~1.5% 且 VWAP正偏", (df['tail30']>0.01)&(df['tail30']<=0.015)&(df['vwap']>0)),
    ("急拉1~1.5% 且 VWAP非正偏", (df['tail30']>0.01)&(df['tail30']<=0.015)&(df['vwap']<=0)),
    ("尾盘涨0.5~1% 且 VWAP正偏", (df['tail30']>0.005)&(df['tail30']<=0.01)&(df['vwap']>0)),
    ("尾盘涨0.5~1% 且 VWAP非正偏", (df['tail30']>0.005)&(df['tail30']<=0.01)&(df['vwap']<=0)),
    ("对照: 尾盘正常(|tail30|<0.5%)", df['tail30'].abs()<0.005),
]
for label, m in groups:
    g = df[m]['ret']
    if len(g) > 100:
        print(f"{label:<34} {len(g):>8} {g.mean():>+9.2f} {g.median():>+8.2f} {np.mean(g>0):>7.1%}")
s.close(); t.close()
