#!/usr/bin/env python3
"""tail30_ret 分布 + 急拉次日表现 2026-08-08"""
import sqlite3, duckdb
import numpy as np
from collections import defaultdict

STATE = '/Users/zantao/.hermes/stockdb/state.db'
TUSHARE = '/Users/zantao/.hermes/stockdb/tushare.db'
s = sqlite3.connect(STATE)
t = duckdb.connect(TUSHARE, read_only=True)

# 分布
vals = np.array([r[0] for r in s.execute("SELECT tail30_ret FROM tdx_intraday_feat WHERE tail30_ret IS NOT NULL").fetchall()])
print(f"样本: {len(vals)}")
print("分位:", {p: f"{np.percentile(vals, p):+.4f}" for p in [1,5,10,25,50,75,90,95,99]})
print(f"急拉>+1%: {(vals>0.01).mean()*100:.1f}%  >+1.5%: {(vals>0.015).mean()*100:.1f}%  >+2%: {(vals>0.02).mean()*100:.1f}%")
print(f"急跌<-1%: {(vals<-0.01).mean()*100:.1f}%")

# 次日表现（内存预加载）
tds = [str(r[0]) for r in t.execute("SELECT DISTINCT trade_date FROM daily WHERE trade_date >= '20260224' ORDER BY trade_date").fetchall()]
nx = {d: tds[i+1] for i, d in enumerate(tds[:-1])}
px = defaultdict(dict)
for d, tc, cl in t.execute("SELECT trade_date, ts_code, close FROM daily WHERE trade_date >= '20260224'").fetchall():
    px[str(d)][tc] = float(cl)
def c2t(c): return f"{c}.SH" if c.startswith(("6","68","9")) else f"{c}.SZ"

rows = s.execute("SELECT date, code, tail30_ret FROM tdx_intraday_feat WHERE tail30_ret IS NOT NULL").fetchall()
res = {"急拉>1.5%": [], "急拉1-1.5%": [], "正常": [], "急跌<-1%": []}
for d, code, r30 in rows:
    dd, nxt = str(d), nx.get(str(d))
    if not nxt: continue
    tc = c2t(code)
    c0, c1 = px[dd].get(tc), px[nxt].get(tc)
    if not c0 or not c1 or c0 <= 0: continue
    ret = (c1/c0-1)*100
    if r30 > 0.015: res["急拉>1.5%"].append(ret)
    elif r30 > 0.01: res["急拉1-1.5%"].append(ret)
    elif r30 < -0.01: res["急跌<-1%"].append(ret)
    else: res["正常"].append(ret)
print(f"\n{'分组':<12} {'n':>7} {'次日均值':>9} {'次日中位':>9} {'上涨占比':>8}")
for k, v in res.items():
    if v:
        print(f"{k:<12} {len(v):>7} {np.mean(v):>+9.2f}% {np.median(v):>+9.2f}% {np.mean(np.array(v)>0):>8.1%}")
s.close(); t.close()
