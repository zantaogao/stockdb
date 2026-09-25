#!/usr/bin/env python3
"""TDX 日内特征因子 IC 验证 2026-08-08
对每个日内特征: 全市场截面 Spearman(特征, 次日收益), 116 天滚动统计"""
import sqlite3, duckdb
import numpy as np
from scipy.stats import spearmanr
from collections import defaultdict

STATE = '/Users/zantao/.hermes/stockdb/state.db'
TUSHARE = '/Users/zantao/.hermes/stockdb/tushare.db'

s = sqlite3.connect(STATE)
t = duckdb.connect(TUSHARE, read_only=True)

# 交易日历
tds = [str(r[0]) for r in t.execute("SELECT DISTINCT trade_date FROM daily WHERE trade_date >= '20260224' ORDER BY trade_date").fetchall()]
td_next = {d: tds[i+1] for i, d in enumerate(tds[:-1])}

# 特征 + 次日收益
feats = ['open30_ret', 'tail30_ret', 'vwap_dev', 'rv_1m', 'amp_intra', 'vol_dist_am']
rows = s.execute("SELECT date, code, open30_ret, tail30_ret, vwap_dev, rv_1m, amp_intra, vol_dist_am FROM tdx_intraday_feat").fetchall()

# 每日截面: {date: {code: {feat: val}}}
daily = defaultdict(dict)
for date, code, *vals in rows:
    daily[str(date)][code] = dict(zip(feats, vals))

# 次日收益: {date: {code: ret}} —— 预加载 daily close 到内存（避免逐行查询）
def code_to_ts(c):
    return f"{c}.SH" if c.startswith(('6', '68', '9')) else f"{c}.SZ"

print("加载 daily close ...")
px = {}
for d, tc, cl in t.execute("SELECT trade_date, ts_code, close FROM daily WHERE trade_date >= '20260224'").fetchall():
    px.setdefault(str(d), {})[tc] = float(cl)

print(f"{'特征':<14} {'IC均值':>8} {'ICIR':>6} {'胜率':>6} {'样本日':>6} {'说明'}")
print("-" * 70)
for f in feats:
    ic_list = []
    for d, nx in td_next.items():
        fvals, rets = [], []
        p0, p1 = px.get(d, {}), px.get(nx, {})
        for code, fv in daily.get(d, {}).items():
            v = fv[f]
            if v is None or (isinstance(v, float) and (v != v)):
                continue
            tc = code_to_ts(code)
            c0, c1 = p0.get(tc), p1.get(tc)
            if not c0 or not c1 or c0 <= 0 or c1 <= 0:
                continue
            rets.append((c1 / c0 - 1) * 100)
            fvals.append(v)
        if len(fvals) >= 500:
            ic = float(spearmanr(fvals, rets).statistic)
            ic_list.append(ic)
    if ic_list:
        m = float(np.mean(ic_list))
        sd = float(np.std(ic_list, ddof=1))
        ir = m / sd if sd > 0 else 0
        win = sum(1 for x in ic_list if x > 0) / len(ic_list)
        note = ''
        if f == 'rv_1m': note = '波动率(负IC=低波动次日涨?)'
        if f == 'vol_dist_am': note = '早盘量占比'
        if f == 'open30_ret': note = '开盘30分钟动量'
        if f == 'tail30_ret': note = '尾盘30分钟动量'
        if f == 'vwap_dev': note = '收盘vs VWAP偏离'
        if f == 'amp_intra': note = '日内振幅'
        print(f"{f:<14} {m:>+8.4f} {ir:>6.2f} {win:>6.1%} {len(ic_list):>6} {note}")
s.close(); t.close()
