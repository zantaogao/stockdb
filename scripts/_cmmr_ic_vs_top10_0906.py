#!/usr/bin/env python3
"""拆解：CMMR 全截面IC为负 vs cmmr>0 Top10 等权收益为正，矛盾吗？
对 5 个成熟20d窗口信号日(20260803-0807)：
 1) 全截面 Spearman IC（产线口径复现）
 2) cmmr>0 子集内的 Spearman IC（Top10同子集）
 3) cmmr>0 子集分10组，各组等权20d收益（看单调性/尾部反转）
 4) 全市场等权基准（同期）→ Top10超额
"""
import sqlite3
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

st = sqlite3.connect('/Users/zantao/.hermes/stockdb/signals.db')
td = sqlite3.connect('/Users/zantao/.hermes/stockdb/tushare.db')
import duckdb
td = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)

tdays = [str(r[0]) for r in td.execute(
    "SELECT DISTINCT trade_date FROM daily ORDER BY trade_date").fetchall()]
tidx = {d: i for i, d in enumerate(tdays)}

sig_dates = ['20260803', '20260804', '20260805', '20260806', '20260807']

def code_to_ts(c):
    return c + ('.SH' if c.startswith(('6', '9')) else '.SZ')

rows_out = []
for sd in sig_dates:
    i0 = tidx[sd]
    end = tdays[i0 + 20]
    sig = st.execute(
        "SELECT stock_code, cmmr_score FROM signal_history "
        "WHERE REPLACE(date,'-','')=? AND cmmr_score IS NOT NULL", (sd,)).fetchall()
    codes = [code_to_ts(r[0]) for r in sig]
    sc = {tc: float(r[1]) for tc, r in zip(codes, sig) if r[1] is not None}
    p0 = {r[0]: float(r[1]) for r in td.execute(
        "SELECT ts_code, close FROM daily WHERE trade_date=?", (sd,)).fetchall()}
    p1 = {r[0]: float(r[1]) for r in td.execute(
        "SELECT ts_code, close FROM daily WHERE trade_date=?", (end,)).fetchall()}
    both = [tc for tc in sc if tc in p0 and tc in p1 and p0[tc] > 0 and p1[tc] > 0]
    ret = {tc: p1[tc] / p0[tc] - 1 for tc in both}
    # 全市场等权基准（daily当日全部票）
    all_b = [ret[tc] for tc in both]
    mkt = np.mean(all_b)
    # 1) 全截面 IC
    s_all = [sc[tc] for tc in both]
    r_all = [ret[tc] for tc in both]
    ic_all = spearmanr(s_all, r_all).correlation
    # 2) cmmr>0 子集 IC
    pos = [tc for tc in both if sc[tc] > 0]
    ic_pos = spearmanr([sc[tc] for tc in pos], [ret[tc] for tc in pos]).correlation
    # 3) 正子集分10组
    pos_sorted = sorted(pos, key=lambda tc: sc[tc])
    q = len(pos_sorted) // 10
    grp = [np.mean([ret[tc] for tc in pos_sorted[i*q:(i+1)*q]]) * 100 for i in range(10)]
    # 4) top10 与超额
    top = sorted(pos, key=lambda tc: sc[tc], reverse=True)[:10]
    top_ret = np.mean([ret[tc] for tc in top]) * 100
    rows_out.append(dict(sd=sd, end=end, n_all=len(both), n_pos=len(pos),
                         mkt=round(mkt*100, 2), ic_all=round(ic_all, 4),
                         ic_pos=round(ic_pos, 4), top10=round(top_ret, 2),
                         excess=round(top_ret - mkt*100, 2),
                         g1=round(grp[0],2), g5=round(grp[4],2), g9=round(grp[8],2),
                         g10=round(grp[9],2)))
    print(rows_out[-1])

df = pd.DataFrame(rows_out)
print()
print('=== 汇总（5天均值） ===')
print(df[['mkt','ic_all','ic_pos','top10','excess','g1','g5','g9','g10']].mean().round(3).to_string())
df.to_csv('/Users/zantao/.hermes/stockdb/reports/cmmr_ic_vs_top10_0906.csv', index=False)