# -*- coding: utf-8 -*-
"""reg20/reg40 的岗位在哪（2026-09-20）：不当选票腿，当排雷腿？
测试三种用法（fwd10/fwd20 双尺，top10口径）：
 A 纯选票:  reg20/reg40 当排序键（已知弱，基线）
 B 负向过滤: reg10 top30 → reg20/reg40 剔除最差10/15 → 取10（排雷保留制）
 C 反向持仓: reg20/reg40 最低的 bot10 表现（证明它们识别"该避开的票"能力）
 D 双门:    reg10 top50 ∩ reg40前50% → 取10"""
import sqlite3, duckdb, numpy as np, pandas as pd
from scipy import stats

sn = sqlite3.connect('/Users/zantao/.hermes/stockdb/signals.db')
sh = pd.read_sql("select date, stock_code, reg10, reg20, reg40 from signal_history", sn)
sh['date'] = sh['date'].str.replace('-', '')
du = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
px = du.execute("""select d.ts_code as code, d.trade_date as dt, d.close*a.adj_factor as c
 from daily d join adj_factor a on d.ts_code=a.ts_code and d.trade_date=a.trade_date
 where d.trade_date>='20260601'""").df().sort_values(['code', 'dt'])
for n in (10, 20):
    px[f'fwd{n}'] = px.groupby('code')['c'].transform(lambda s: s.shift(-n) / s - 1)
px['code6'] = px['code'].str[:6]
du.close()
m = sh.merge(px[['code6', 'dt', 'fwd10', 'fwd20']], left_on=['stock_code', 'date'], right_on=['code6', 'dt'])
m = m.dropna(subset=['fwd10', 'reg10'])
m = m[m['code6'].str.startswith(('60', '00', '30', '68'))]

def nw_t(x, lag=10):
    x = np.asarray(x, float); x = x[np.isfinite(x)]; n = len(x)
    m_ = x.mean(); xm = x - m_
    s = (xm @ xm) / n
    for l in range(1, lag + 1):
        s += 2 * (1 - l / (lag + 1)) * (xm[l:] @ xm[:-l]) / n
    return m_ / np.sqrt(s / n)

def run(col):
    out = {}
    A10, A20, B10, B20, C10, C20, D10, D20 = [], [], [], [], [], [], [], []
    for d, g in m.groupby('date'):
        if len(g) < 50: continue
        base10, base20 = g['fwd10'].dropna().mean(), g['fwd20'].dropna().mean()
        t30 = g.nlargest(30, 'reg10')
        out['A10'] = out.get('A10', [])
        # A: reg20/reg40 纯选票
        t1 = g.nlargest(10, 'reg20'); A10.append(t1['fwd10'].dropna().mean() - base10)
        t2 = g.nlargest(10, 'reg40'); A20.append(t2['fwd20'].dropna().mean() - base20)
        # B: reg10前30 里用 reg20/reg40 排雷后取10
        b = t30.nlargest(10, 'reg20'); B10.append(b['fwd10'].dropna().mean() - base10)
        b = t30.nlargest(10, 'reg40'); B20.append(b['fwd20'].dropna().mean() - base20)
        # C: 纯避开的票（reg20/reg40 bot10）
        c = g.nsmallest(10, 'reg20'); C10.append(c['fwd10'].dropna().mean() - base10)
        c = g.nsmallest(10, 'reg40'); C20.append(c['fwd20'].dropna().mean() - base20)
        # D: 双门
        dd = g.nlargest(50, 'reg10'); dd = dd.nlargest(10, 'reg40')
        D10.append(dd['fwd10'].dropna().mean() - base10)
        dd = g.nlargest(50, 'reg10'); dd = dd.nlargest(10, 'reg20')
        D20.append(dd['fwd20'].dropna().mean() - base20)
    for name, arr,尺 in [('A纯选票reg20/40', (A10, A20), 'fwd10/20混尺'),
                     ('B排雷制(reg10前30→reg20/reg40挑10)', (B10, B20), ''),
                     ('C避开制(bot10该避的票)', (C10, C20), ''),
                     ('D双门(reg10前50∩reg40/20挑10)', (D10, D20), '')]:
        e1, e2 = np.array(arr[0]), np.array(arr[1])
        print('  %-38s 前尺 %+6.2f%% (t%+5.2f) | 后尺 %+6.2f%% (t%+5.2f)' % (
            name, np.nanmean(e1)*100, nw_t(e1), np.nanmean(e2)*100, nw_t(e2)))
    # 对照：reg10 直接 top10
    r1, r2 = [], []
    for d, g in m.groupby('date'):
        if len(g) < 50: continue
        b10, b20 = g['fwd10'].dropna().mean(), g['fwd20'].dropna().mean()
        t = g.nlargest(10, 'reg10')
        r1.append(t['fwd10'].dropna().mean() - b10); r2.append(t['fwd20'].dropna().mean() - b20)
    e1, e2 = np.array(r1), np.array(r2)
    print('  %-38s 前尺 %+6.2f%% (t%+5.2f) | 后尺 %+6.2f%% (t%+5.2f)' % (
        '对照:reg10直接top10', np.nanmean(e1)*100, nw_t(e1), np.nanmean(e2)*100, nw_t(e2)))

print('=== reg20/reg40 岗位测试（前尺=fwd10、后尺=fwd20，超额对全池等权）===')
run(0)
