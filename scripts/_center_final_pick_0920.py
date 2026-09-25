# -*- coding: utf-8 -*-
"""中枢当"终选层"有没有数据支持（2026-09-20）
假说：中枢全池排序弱但会挑尖子 → 用法=短腿出30只名单、中枢挑10只。
实测（成熟日按 fwd10 齐；配对日差分 vs 对照=reg10直接top10，NW-t lag10）：
 T1: reg10 top30 → 中枢score挑10
 T2: reg10 top30 → 中枢挑10（名单剔中枢尾30%后挑，即中枢有一票否决）
 T3: clf10 top30 → 中枢挑10
 T4: 中枢自己 top30 → 中枢挑10（=中枢top10基线，检验肥尾来自哪层）
 T5: reg10 top30 → clf10挑10（对称对照：clf10当终选层行不行）
附：名单内中枢分的截面IC（前10天vs后10天分段）——假说的直接证据：30只小名单里
中枢分还有没有区分度，全池弱≠名单内弱。"""
import sqlite3, duckdb, numpy as np, pandas as pd
from scipy import stats

sn = sqlite3.connect('/Users/zantao/.hermes/stockdb/signals.db')
sh = pd.read_sql("select date, stock_code, reg10 from signal_history", sn)
sh['date'] = sh['date'].str.replace('-', '')
c10 = pd.read_sql("select date, code stock_code, score clf10 from shadow_clf10_scores", sn)
c10['date'] = c10['date'].str.replace('-', '')
ctr = pd.read_sql("select date, stock_code, score ctr from fusion_center_signals", sn)
du = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
px = du.execute("""select d.ts_code code6, d.trade_date dt, d.close*a.adj_factor c
 from daily d join adj_factor a on d.ts_code=a.ts_code and d.trade_date=a.trade_date
 where d.trade_date>='20260725'""").df().sort_values(['code6', 'dt'])
px['code6'] = px['code6'].str[:6]
px['fwd10'] = px.groupby('code6')['c'].transform(lambda s: s.shift(-10) / s - 1)
du.close()
m = sh.merge(px[['code6', 'dt', 'fwd10']], left_on=['stock_code', 'date'], right_on=['code6', 'dt'], how='inner')
m = m[m['code6'].str[:2].isin(['60', '00', '30', '68'])].dropna(subset=['fwd10', 'reg10'])
m = m.merge(ctr, on=['date', 'stock_code'], how='left').merge(c10, on=['date', 'stock_code'], how='left')

def nw_t(x, lag=10):
    x = np.asarray(x, float); x = x[np.isfinite(x)]; n = len(x)
    if n < 5: return np.nan
    mu = x.mean(); xm = x - mu
    s = (xm @ xm) / n
    for l in range(1, lag + 1):
        s += 2 * (1 - l / (lag + 1)) * (xm[l:] @ xm[:-l]) / n
    return mu / np.sqrt(s / n)

tests = {
 '对照:reg10直接top10': lambda g: g.nlargest(10, 'reg10'),
 'T1 reg30→中枢挑10':   lambda g: g.nlargest(30, 'reg10').nlargest(10, 'ctr'),
 'T2 reg30剔中枢尾30%挑10': lambda g: (lambda t: t.nlargest(10, 'ctr'))(g.nlargest(30, 'reg10').pipe(lambda x: x[x['ctr'].rank(pct=True) > 0.30])),
 'T3 clf30→中枢挑10':   lambda g: g.nlargest(30, 'clf10').nlargest(10, 'ctr'),
 'T4 中枢top30→挑10':   lambda g: g.nlargest(30, 'ctr').nlargest(10, 'ctr'),
 'T5 reg30→clf10挑10':  lambda g: g.nlargest(30, 'reg10').nlargest(10, 'clf10'),
}
rows, ics30 = [], []
for d, g in m.groupby('date'):
    g = g.dropna(subset=['ctr'])
    if len(g) < 1000: continue
    base = g['fwd10'].mean()
    rec = {'date': d}
    for name, fn in tests.items():
        rec[name] = fn(g)['fwd10'].mean() - base
    rows.append(rec)
    t30 = g.nlargest(30, 'reg10').dropna(subset=['ctr'])
    if len(t30) >= 15:
        ics30.append((d, stats.spearmanr(t30['ctr'], t30['fwd10']).statistic,
                      stats.spearmanr(g['ctr'], g['fwd10']).statistic))
r = pd.DataFrame(rows).sort_values('date')
print('成熟日 %d（fwd10口径，超额=对全池等权）' % len(r))
ctrl = '对照:reg10直接top10'
for name in tests:
    if name == ctrl:
        print('%-22s 超额 %+6.2f%%/日 (t%+5.2f) 赢池天数 %2d/%d' % (name, r[name].mean()*100, nw_t(r[name]), (r[name]>0).sum(), len(r)))
    else:
        diff = r[name] - r[ctrl]
        print('%-22s 超额 %+6.2f%%/日 (t%+5.2f) | vs对照配对差 %+6.3f%% (t%+5.2f) 差>0 %2d/%d' % (
            name, r[name].mean()*100, nw_t(r[name]), diff.mean()*100, nw_t(diff), (diff>0).sum(), len(diff)))
print()
ic = pd.DataFrame(ics30, columns=['date', 'ic_ctr_top30', 'ic_ctr_pool']).sort_values('date')
print('=== 假说直接证据：中枢分在 reg10 top30 名单内 vs 全池的截面IC（fwd10）===')
h = len(ic)//2
print('前半段(%s~%s n=%d): 名单内IC %+0.3f | 全池IC %+0.3f' % (ic.date.iloc[0], ic.date.iloc[h-1], h, ic.ic_ctr_top30.iloc[:h].mean(), ic.ic_ctr_pool.iloc[:h].mean()))
print('后半段(%s~%s n=%d): 名单内IC %+0.3f | 全池IC %+0.3f' % (ic.date.iloc[h], ic.date.iloc[-1], len(ic)-h, ic.ic_ctr_top30.iloc[h:].mean(), ic.ic_ctr_pool.iloc[h:].mean()))
print('名单内IC>0占比 %.0f%% | 全池IC>0占比 %.0f%%' % ((ic.ic_ctr_top30>0).mean()*100, (ic.ic_ctr_pool>0).mean()*100))
