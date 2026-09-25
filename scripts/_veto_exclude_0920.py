# -*- coding: utf-8 -*-
"""否决制的正确姿势：只排雷、不重排（2026-09-20）
上一轮"重排制"(reg40再挑top10)被配对差分证伪。本脚本测排除制：
 V1: 剔除 reg40 bot10% 后 reg10 选 top10
 V2: 剔除 reg20 bot10% 后 reg10 选 top10
 V3: 剔除 reg20∪reg40 bot10%（并集）后 reg10 选 top10
 V4: 剔除 reg20 bot20% ∪ reg40 bot20%（宽阈）
对照 = reg10 直接 top10。全部用**配对日差分** NW-t（fwd10 lag10 / fwd20 lag20）。"""
import sqlite3, duckdb, numpy as np, pandas as pd

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

def nw_t(x, lag):
    x = np.asarray(x, float); x = x[np.isfinite(x)]; n = len(x)
    if n < 5: return np.nan
    mu = x.mean(); xm = x - mu
    s = (xm @ xm) / n
    for l in range(1, lag + 1):
        s += 2 * (1 - l / (lag + 1)) * (xm[l:] @ xm[:-l]) / n
    return mu / np.sqrt(s / n)

variants = {'V1剔reg40尾10%': lambda g: g['reg40'].rank(pct=True) > 0.10,
            'V2剔reg20尾10%': lambda g: g['reg20'].rank(pct=True) > 0.10,
            'V3剔并集尾10%': lambda g: (g['reg40'].rank(pct=True) > 0.10) & (g['reg20'].rank(pct=True) > 0.10),
            'V4剔并集尾20%': lambda g: (g['reg40'].rank(pct=True) > 0.20) & (g['reg20'].rank(pct=True) > 0.20)}
rows = []
for d, g in m.groupby('date'):
    if len(g) < 50: continue
    rec = {'date': d}
    ctrl = g.nlargest(10, 'reg10')
    rec['c10'] = ctrl['fwd10'].dropna().mean(); rec['c20'] = ctrl['fwd20'].dropna().mean()
    for name, keep in variants.items():
        gg = g[keep(g)]
        t = gg.nlargest(10, 'reg10')
        k = name[:2]
        rec[k + '10'] = t['fwd10'].dropna().mean(); rec[k + '20'] = t['fwd20'].dropna().mean()
        rec[k + 'ov'] = len(set(t['stock_code']) & set(ctrl['stock_code']))
    rows.append(rec)
r = pd.DataFrame(rows).sort_values('date')
print('成熟日 %d | 对照=reg10直接top10: fwd10 %+.2f%% fwd20 %+.2f%%（绝对收益，配对差分见下）' % (
    len(r), r.c10.mean() * 100, r.c20.mean() * 100))
print()
for name in variants:
    k = name[:2]
    d10 = r[k + '10'] - r['c10']; d20 = r[k + '20'] - r['c20']
    print('%-16s 与对照重合 %.1f/10 | fwd10配对差 %+6.3f%% (t%+5.2f) 差>0 %2d/%d | fwd20配对差 %+6.3f%% (t%+5.2f) 差>0 %2d/%d' % (
        name, r[k + 'ov'].mean(),
        d10.dropna().mean() * 100, nw_t(d10, 10), (d10 > 0).sum(), r[k + '10'].notna().sum(),
        d20.dropna().mean() * 100, nw_t(d20, 20), (d20 > 0).sum(), r[k + '20'].notna().sum()))
