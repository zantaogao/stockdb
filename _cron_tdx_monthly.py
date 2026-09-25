#!/usr/bin/env python3
"""tail30_ret / rv_1m / amp_intra 分月 IC 稳定性验证 2026-08-08"""
import sqlite3, duckdb
import numpy as np
from scipy.stats import spearmanr
from collections import defaultdict

STATE = '/Users/zantao/.hermes/stockdb/state.db'
TUSHARE = '/Users/zantao/.hermes/stockdb/tushare.db'

s = sqlite3.connect(STATE)
t = duckdb.connect(TUSHARE, read_only=True)

tds = [str(r[0]) for r in t.execute("SELECT DISTINCT trade_date FROM daily WHERE trade_date >= '20260224' ORDER BY trade_date").fetchall()]
td_next = {d: tds[i+1] for i, d in enumerate(tds[:-1])}

feats = ['tail30_ret', 'rv_1m', 'amp_intra']
rows = s.execute("SELECT date, code, tail30_ret, rv_1m, amp_intra FROM tdx_intraday_feat").fetchall()
daily = defaultdict(dict)
for date, code, *vals in rows:
    daily[str(date)][code] = dict(zip(feats, vals))

def code_to_ts(c):
    return f"{c}.SH" if c.startswith(('6', '68', '9')) else f"{c}.SZ"

px = {}
for d, tc, cl in t.execute("SELECT trade_date, ts_code, close FROM daily WHERE trade_date >= '20260224'").fetchall():
    px.setdefault(str(d), {})[tc] = float(cl)

# 按月分组
monthly_ic = defaultdict(lambda: defaultdict(list))
for d, nx in td_next.items():
    month = d[:6]
    p0, p1 = px.get(d, {}), px.get(nx, {})
    for f in feats:
        fvals, rets = [], []
        for code, fv in daily.get(d, {}).items():
            v = fv[f]
            if v is None or (isinstance(v, float) and v != v):
                continue
            tc = code_to_ts(code)
            c0, c1 = p0.get(tc), p1.get(tc)
            if not c0 or not c1 or c0 <= 0 or c1 <= 0:
                continue
            rets.append((c1 / c0 - 1) * 100)
            fvals.append(v)
        if len(fvals) >= 500:
            monthly_ic[f][month].append(float(spearmanr(fvals, rets).statistic))

print(f"{'月份':<8}" + "".join(f"{f[:10]:>12}" for f in feats))
for month in sorted(monthly_ic[feats[0]].keys()):
    line = f"{month:<8}"
    for f in feats:
        ics = monthly_ic[f].get(month, [])
        m = np.mean(ics) if ics else float('nan')
        line += f"{m:>+12.4f}"
    print(line)
print("-" * 44)
print(f"{'全期':<8}", end="")
for f in feats:
    ics = [x for mth in monthly_ic[f].values() for x in mth]
    print(f"{np.mean(ics):>+12.4f}", end="")
print()

# 每月正/负天数
print("\ntail30_ret 每月 IC>0 天数:")
for month in sorted(monthly_ic[feats[0]].keys()):
    ics = monthly_ic['tail30_ret'].get(month, [])
    neg = sum(1 for x in ics if x < 0)
    print(f"  {month}: {neg}/{len(ics)} 天为负")
s.close(); t.close()
